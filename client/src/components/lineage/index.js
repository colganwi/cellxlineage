import React from "react";
import { connect, shallowEqual } from "react-redux";
import _regl from "regl";
import { mat3 } from "gl-matrix";
import memoize from "memoize-one";
import Async from "react-async";
import {
  AnchorButton,
  Button,
  ButtonGroup,
  Tooltip,
  Position,
} from "@blueprintjs/core";

import * as globals from "../../globals";
import actions from "../../actions";
import _drawBranches from "./drawBranchesRegl";
import _drawAnnotation from "./drawAnnotationRegl";
import _drawNodes from "./drawNodesRegl";
import LineageChoices from "./choices";
import setupTreeSelector from "./setupTreeSelector";
import setupTreeZoom from "./setupTreeZoom";
import TreeScrollbar from "./scrollbar";
import {
  createColorTable,
  createColorQuery,
} from "../../util/stateManager/colorHelpers";
import renderThrottle from "../../util/renderThrottle";

const DIM_ALPHA = 0.15; // opacity of unselected cells in the annotation bar
const MISSING_COLOR = [0.83, 0.83, 0.83]; // nodes/leaves with no obs mapping
const BRANCH_COLOR = [0.25, 0.25, 0.25, 1];
const MARGIN = { left: 6, right: 6, top: 6, bottom: 6 };
const STRIP_WIDTH = 21; // annotation bar width, px
const STRIP_GAP = 6; // gap between tree and bar, px
const HIGHLIGHT_SCALE = 2; // hovered-category leaves widen by this factor
// Extra right-edge reservation so the widened highlight clears the vertical
// scrollbar (TreeScrollbar sits in the rightmost ~10px: right:2 + width:8).
const SCROLLBAR_CLEARANCE = 8;
// Max zoom-in shows at least this many leaves (only caps trees with more leaves).
const MAX_ZOOM_LEAVES = 100;

function createProjectionTF(viewportWidth, viewportHeight) {
  const m = mat3.create();
  return mat3.projection(m, viewportWidth, viewportHeight);
}

@connect((state) => ({
  annoMatrix: state.annoMatrix,
  colors: state.colors,
  crossfilter: state.obsCrossfilter,
  genesets: state.genesets.genesets,
  lineageData: state.lineageData,
  lineageChoice: state.lineageChoice,
  ancestralLinkage: state.ancestralLinkage,
  pointDilation: state.pointDilation,
  graphInteractionMode: state.controls.graphInteractionMode,
}))
class Lineage extends React.PureComponent {
  static createReglState(canvas) {
    if (!canvas) return {};
    const regl = _regl({
      canvas,
      extensions: ["ANGLE_instanced_arrays"],
    });
    const drawBranches = _drawBranches(regl);
    const drawAnnotation = _drawAnnotation(regl);
    const drawNodes = _drawNodes(regl);

    // static unit-quad geometry shared across annotation instances
    const cornerBuffer = regl.buffer(
      new Float32Array([0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1])
    );
    const branchBuffer = regl.buffer();
    const leafYBuffer = regl.buffer();
    const leafColorBuffer = regl.buffer();
    const leafSelectedBuffer = regl.buffer();
    const leafHighlightBuffer = regl.buffer();
    const nodeBuffer = regl.buffer();
    const nodeColorBuffer = regl.buffer();
    const nodeSelectedBuffer = regl.buffer();

    return {
      regl,
      drawBranches,
      drawAnnotation,
      drawNodes,
      cornerBuffer,
      branchBuffer,
      leafYBuffer,
      leafColorBuffer,
      leafSelectedBuffer,
      leafHighlightBuffer,
      nodeBuffer,
      nodeColorBuffer,
      nodeSelectedBuffer,
    };
  }

  static watchAsync(props, prevProps) {
    return !shallowEqual(props.watchProps, prevProps.watchProps);
  }

  /* interleave branch segment endpoints into a flat [x0,y0,x1,y1,...] buffer */
  computeBranchPositions = memoize((branches) => {
    const { x0, y0, x1, y1 } = branches;
    const n = x0.length;
    const positions = new Float32Array(4 * n);
    for (let i = 0; i < n; i += 1) {
      positions[4 * i] = x0[i];
      positions[4 * i + 1] = y0[i];
      positions[4 * i + 2] = x1[i];
      positions[4 * i + 3] = y1[i];
    }
    return positions;
  });

  /* interleave node x,y into a flat [x,y,...] buffer */
  computeNodePositions = memoize((nodes) => {
    const { x, y } = nodes;
    const positions = new Float32Array(2 * x.length);
    for (let i = 0, n = x.length; i < n; i += 1) {
      positions[2 * i] = x[i];
      positions[2 * i + 1] = y[i];
    }
    return positions;
  });

  /* x extent (depth axis) across all branch endpoints */
  computeExtents = memoize((branches) => {
    const { x0, x1 } = branches;
    let xMin = Infinity;
    let xMax = -Infinity;
    for (let i = 0, n = x0.length; i < n; i += 1) {
      if (x0[i] < xMin) xMin = x0[i];
      if (x0[i] > xMax) xMax = x0[i];
      if (x1[i] < xMin) xMin = x1[i];
      if (x1[i] > xMax) xMax = x1[i];
    }
    if (!Number.isFinite(xMin)) {
      xMin = 0;
      xMax = 1;
    }
    return { xMin, xMax };
  });

  /* per-item rgb buffer, indexed by obs row position (matches the UMAP) */
  computeColors = memoize((rgb, obsIdx) => {
    const colors = new Float32Array(3 * obsIdx.length);
    for (let i = 0, n = obsIdx.length; i < n; i += 1) {
      const c = obsIdx[i] >= 0 ? rgb[obsIdx[i]] : undefined;
      const src = c ?? MISSING_COLOR;
      colors[3 * i] = src[0];
      colors[3 * i + 1] = src[1];
      colors[3 * i + 2] = src[2];
    }
    return colors;
  });

  /* per-item selection flag from the crossfilter mask (1 = selected/bright) */
  computeSelected = memoize((crossfilter, obsIdx) => {
    const mask = crossfilter.allSelectedMask();
    const selected = new Float32Array(obsIdx.length);
    for (let i = 0, n = obsIdx.length; i < n; i += 1) {
      const o = obsIdx[i];
      selected[i] = o >= 0 && mask[o] ? 1 : 0;
    }
    return selected;
  });

  /* per-item highlight flag: 1 when the leaf's cell is in one of the hovered
     categories (mirrors the UMAP point-dilation highlight; one category for a
     left-sidebar hover, two for a pairwise linkage heatmap cell hover) */
  computeHighlight = memoize((dilationData, labels, obsIdx) => {
    const highlight = new Float32Array(obsIdx.length);
    if (dilationData && labels?.length) {
      const labelSet = new Set(labels);
      for (let i = 0, n = obsIdx.length; i < n; i += 1) {
        const o = obsIdx[i];
        if (o >= 0 && labelSet.has(dilationData[o])) highlight[i] = 1;
      }
    }
    return highlight;
  });

  constructor(props) {
    super(props);
    this.reglCanvas = null;
    this.canvasSize = { width: 1, height: 1 };
    this.renderCache = null;
    this.resizeObserver = null;
    this.lasso = null;
    this.zoom = null;
    this.yView = { lo: 0, hi: 1 }; // visible leaf window (vertical zoom)
    this.lastData = null;
    this.state = { regl: null };
  }

  componentDidMount() {
    this._mounted = true;
  }

  componentWillUnmount() {
    this._mounted = false;
    if (this.resizeObserver) this.resizeObserver.disconnect();
    if (this.lasso) this.lasso.detach();
    if (this.zoom) this.zoom.detach();
  }

  // Update the vertical zoom window: `this.yView` is the synchronous source of
  // truth (read during rapid wheel/drag events); forceUpdate re-renders the
  // scrollbar to track it, and renderCanvas redraws the tree.
  setYView = (v) => {
    this.yView = v;
    this.renderCanvas();
    if (this._mounted) this.forceUpdate();
  };

  setReglCanvas = (canvas) => {
    this.reglCanvas = canvas;
    if (canvas) {
      this.measure();
      this.setState({ ...Lineage.createReglState(canvas) });
      this.attachSelector();
    }
  };

  setCanvasArea = (ref) => {
    this.canvasAreaRef = ref;
    if (ref && !this.resizeObserver) {
      this.resizeObserver = new ResizeObserver(() => this.handleResize());
      this.resizeObserver.observe(ref);
    }
  };

  handleResize = () => {
    this.measure();
    this.renderCanvas();
  };

  fetchAsyncProps = async (props) => {
    const {
      annoMatrix,
      colors,
      crossfilter,
      genesets,
      lineageData,
      pointDilation,
    } = props.watchProps;
    const data = lineageData?.data;
    if (!data) return { data: null };

    // Color exactly like the UMAP: same query + memoized color table.
    const query = createColorQuery(
      colors.colorMode,
      colors.colorAccessor,
      annoMatrix.schema,
      genesets
    );
    const colorDf = query ? await annoMatrix.fetch(...query) : null;
    const colorTable = createColorTable(
      colors.colorMode,
      colors.colorAccessor,
      colorDf,
      annoMatrix.schema,
      colors.userColors
    );
    const { rgb } = colorTable;

    // Cell metadata column + value(s) being hovered (left-sidebar category, or a
    // pairwise linkage heatmap cell → two categories), if any.
    const { metadataField, categoryFields } = pointDilation ?? {};
    let dilationData = null;
    if (metadataField) {
      const df = await annoMatrix.fetch("obs", metadataField);
      dilationData = df?.col(metadataField)?.asArray();
    }

    const branchPositions = this.computeBranchPositions(data.branches);
    const extents = this.computeExtents(data.branches);

    const leafObs = data.leaves.obs;
    const result = {
      data,
      hasNodes: !!data.nodes,
      branchPositions,
      branchCount: branchPositions.length / 2,
      extents,
      leafY: data.leaves.y,
      leafObs,
      nLeaves: leafObs.length,
      leafColors: this.computeColors(rgb, leafObs),
      leafSelected: this.computeSelected(crossfilter, leafObs),
      leafHighlight: this.computeHighlight(
        dilationData,
        categoryFields,
        leafObs
      ),
    };

    if (data.nodes) {
      result.nodePositions = this.computeNodePositions(data.nodes);
      result.nodeCount = data.nodes.x.length;
      result.nodeColors = this.computeColors(rgb, data.nodes.obs);
      result.nodeSelected = this.computeSelected(crossfilter, data.nodes.obs);
    }
    return result;
  };

  measure() {
    const ref = this.canvasAreaRef;
    if (!ref || !this.reglCanvas) return;
    const width = Math.max(1, Math.floor(ref.clientWidth));
    const height = Math.max(1, Math.floor(ref.clientHeight));
    this.canvasSize = { width, height };
    this.reglCanvas.width = width;
    this.reglCanvas.height = height;
  }

  attachSelector() {
    // Rectangular selection over the tree (lasso/"select" tool) → select the
    // enclosed leaves in the shared crossfilter (the UMAP then dims to match).
    const { dispatch } = this.props;
    const getMode = () => {
      const { graphInteractionMode } = this.props;
      return graphInteractionMode;
    };
    this.lasso = setupTreeSelector(this.reglCanvas, {
      getLeafGeometry: () => this.leafGeometry(),
      getMode,
      dispatch,
    });
    // Vertical zoom/pan (the "zoom" tool) — subsets the visible leaves.
    this.zoom = setupTreeZoom(this.reglCanvas, {
      getMode,
      getView: () => this.yView,
      setView: this.setYView,
      getPlotRect: () => ({
        yTop: MARGIN.top,
        yBot: this.canvasSize.height - MARGIN.bottom,
      }),
      // Cap max zoom so at most MAX_ZOOM_LEAVES leaves fill the pane on large
      // trees; smaller trees keep the default fine zoom.
      getMinRange: () => {
        const n = this.renderCache?.nLeaves;
        return n && n > MAX_ZOOM_LEAVES ? MAX_ZOOM_LEAVES / n : null;
      },
    });
  }

  /* pixel y of each leaf + its obs row, for rectangular hit-testing.
     Uses the current zoom window so hit-testing matches what is drawn. */
  leafGeometry() {
    if (!this.renderCache) return null;
    const { leafY, leafObs } = this.renderCache;
    const { height } = this.canvasSize;
    const yTop = MARGIN.top;
    const yBot = height - MARGIN.bottom;
    const { lo, hi } = this.yView;
    const yM = (yBot - yTop) / (hi - lo);
    const yB = yTop - lo * yM;
    return { leafY, leafObs, yM, yB };
  }

  updateReglAndRender(asyncProps) {
    this.renderCache = asyncProps;
    if (!asyncProps?.data) {
      this.renderCanvas();
      return;
    }
    // Reset the zoom window when the tree layout changes (new tree/depth key),
    // but preserve it across color/selection updates.
    if (asyncProps.data !== this.lastData) {
      this.lastData = asyncProps.data;
      const wasZoomed = this.yView.lo !== 0 || this.yView.hi !== 1;
      this.yView = { lo: 0, hi: 1 };
      // This runs inside the Async render path, so defer the scrollbar
      // re-render (forceUpdate during render is not allowed).
      if (wasZoomed) {
        Promise.resolve().then(() => {
          if (this._mounted) this.forceUpdate();
        });
      }
    }
    const {
      branchBuffer,
      leafYBuffer,
      leafColorBuffer,
      leafSelectedBuffer,
      leafHighlightBuffer,
      nodeBuffer,
      nodeColorBuffer,
      nodeSelectedBuffer,
    } = this.state;
    branchBuffer({ data: asyncProps.branchPositions, dimension: 2 });
    leafYBuffer({ data: asyncProps.leafY, dimension: 1 });
    leafColorBuffer({ data: asyncProps.leafColors, dimension: 3 });
    leafSelectedBuffer({ data: asyncProps.leafSelected, dimension: 1 });
    leafHighlightBuffer({ data: asyncProps.leafHighlight, dimension: 1 });
    if (asyncProps.hasNodes) {
      nodeBuffer({ data: asyncProps.nodePositions, dimension: 2 });
      nodeColorBuffer({ data: asyncProps.nodeColors, dimension: 3 });
      nodeSelectedBuffer({ data: asyncProps.nodeSelected, dimension: 1 });
    }
    this.renderCanvas();
  }

  renderCanvas = renderThrottle(() => {
    const {
      regl,
      drawBranches,
      drawAnnotation,
      drawNodes,
      cornerBuffer,
      branchBuffer,
      leafYBuffer,
      leafColorBuffer,
      leafSelectedBuffer,
      leafHighlightBuffer,
      nodeBuffer,
      nodeColorBuffer,
      nodeSelectedBuffer,
    } = this.state;
    if (!regl || !this.reglCanvas) return;

    regl.poll();
    regl.clear({ color: [1, 1, 1, 1], depth: 1 });

    const cache = this.renderCache;
    if (!cache?.data) return;

    const { width, height } = this.canvasSize;
    const projection = createProjectionTF(width, height);

    const { xMin } = cache.extents;
    let { xMax } = cache.extents;
    if (xMax === xMin) xMax = xMin + 1;

    const stripWidthPx = cache.hasNodes ? 0 : STRIP_WIDTH;
    const gapPx = cache.hasNodes ? 0 : STRIP_GAP;
    // Reserve whitespace to the right of the bar so hovered-category leaves can
    // widen (HIGHLIGHT_SCALE×) without spilling off the canvas.
    const growRoomPx = cache.hasNodes ? 0 : STRIP_WIDTH * (HIGHLIGHT_SCALE - 1);
    const treeLeft = MARGIN.left;
    const treeRight =
      width -
      MARGIN.right -
      SCROLLBAR_CLEARANCE -
      growRoomPx -
      gapPx -
      stripWidthPx;
    const xM = (treeRight - treeLeft) / (xMax - xMin);
    const xB = treeLeft - xM * xMin;
    const yTop = MARGIN.top;
    const yBot = height - MARGIN.bottom;
    // Vertical zoom: map the visible leaf window [lo,hi] onto the plot rect.
    // Horizontal (depth) is unaffected, so root and leaves are always shown.
    const { lo, hi } = this.yView;
    const yM = (yBot - yTop) / (hi - lo);
    const yB = yTop - lo * yM;

    // clip to the plot rect (GL framebuffer y is measured from the bottom)
    const scissorBox = {
      x: 0,
      y: MARGIN.bottom,
      width,
      height: Math.max(0, yBot - yTop),
    };

    drawBranches({
      position: branchBuffer,
      count: cache.branchCount,
      projection,
      color: BRANCH_COLOR,
      xM,
      xB,
      yM,
      yB,
      scissorBox,
    });

    if (cache.hasNodes) {
      drawNodes({
        position: nodeBuffer,
        color: nodeColorBuffer,
        selected: nodeSelectedBuffer,
        count: cache.nodeCount,
        projection,
        xM,
        xB,
        yM,
        yB,
        pointSize: 4,
        dimAlpha: DIM_ALPHA,
        scissorBox,
      });
    } else {
      const cellHalf = Math.max(yM / cache.nLeaves / 2, 0.5);
      drawAnnotation({
        corner: cornerBuffer,
        leafY: leafYBuffer,
        color: leafColorBuffer,
        selected: leafSelectedBuffer,
        highlighted: leafHighlightBuffer,
        instances: cache.nLeaves,
        projection,
        stripX0: treeRight + gapPx,
        stripWidth: stripWidthPx,
        yM,
        yB,
        cellHalf,
        dimAlpha: DIM_ALPHA,
        highlightScale: HIGHLIGHT_SCALE,
        scissorBox,
      });
    }
    regl._gl.flush();
  });

  render() {
    const {
      dispatch,
      annoMatrix,
      colors,
      crossfilter,
      genesets,
      lineageData,
      lineageChoice,
      ancestralLinkage,
      pointDilation,
      graphInteractionMode,
    } = this.props;
    const { regl } = this.state;

    // Ancestral-linkage buttons (top-left of the tree pane).
    // "selected" needs a proper subset of cells selected as the target;
    // "pairwise" needs a categorical color-by active as the groupby.
    const nSelected = crossfilter?.countSelected?.() ?? 0;
    const nObs = annoMatrix?.nObs ?? 0;
    const hasSelection = nSelected > 0 && nSelected < nObs;
    const hasCategoricalColorBy =
      colors?.colorMode === "color by categorical metadata" &&
      !!colors?.colorAccessor;
    const selectedLoading = ancestralLinkage?.selectedLoading;
    const pairwiseLoading = ancestralLinkage?.pairwiseLoading;

    // No trees in this dataset (plain AnnData) → keep the sidebar empty.
    if (!lineageChoice?.available?.length) {
      return (
        <div
          style={{
            borderLeft: `1px solid ${globals.lightGrey}`,
            height: "inherit",
            width: "inherit",
          }}
        />
      );
    }

    return (
      <div
        style={{
          borderLeft: `1px solid ${globals.lightGrey}`,
          height: "inherit",
          width: "inherit",
          display: "flex",
          flexDirection: "column",
          position: "relative",
        }}
      >
        <div
          ref={this.setCanvasArea}
          style={{ flex: 1, position: "relative", minHeight: 0 }}
        >
          <ButtonGroup
            style={{
              position: "absolute",
              top: 8,
              left: 8,
              zIndex: 10,
            }}
          >
            <Tooltip
              content="Ancestral linkage to selected cells"
              position={Position.BOTTOM}
            >
              <AnchorButton
                type="button"
                data-testid="ancestral-linkage-selected"
                icon="route"
                loading={selectedLoading}
                disabled={!hasSelection}
                onClick={() =>
                  dispatch(actions.ancestralLinkageSelectedAction())
                }
              />
            </Tooltip>
            <Tooltip
              content="Pairwise ancestral linkage between selected categories"
              position={Position.BOTTOM}
            >
              <AnchorButton
                type="button"
                data-testid="ancestral-linkage-pairwise"
                icon="heat-grid"
                loading={pairwiseLoading}
                disabled={!hasCategoricalColorBy}
                onClick={() =>
                  dispatch(actions.ancestralLinkagePairwiseAction())
                }
              />
            </Tooltip>
          </ButtonGroup>
          <canvas
            data-testid="lineage-canvas"
            style={{
              width: "100%",
              height: "100%",
              display: "block",
              cursor: graphInteractionMode === "zoom" ? "move" : "crosshair",
            }}
            ref={this.setReglCanvas}
          />
          <Async
            watchFn={Lineage.watchAsync}
            promiseFn={this.fetchAsyncProps}
            watchProps={{
              annoMatrix,
              colors,
              crossfilter,
              genesets,
              lineageData,
              pointDilation,
            }}
          >
            <Async.Fulfilled>
              {(asyncProps) => {
                if (regl && !shallowEqual(asyncProps, this.renderCache)) {
                  this.updateReglAndRender(asyncProps);
                }
                return null;
              }}
            </Async.Fulfilled>
          </Async>
          <TreeScrollbar
            view={this.yView}
            onChange={this.setYView}
            top={MARGIN.top}
            bottom={MARGIN.bottom}
          />
          {lineageData?.loading ? (
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                display: "flex",
                alignItems: "center",
                fontWeight: 500,
                pointerEvents: "none",
                zIndex: 5,
              }}
            >
              <Button minimal loading intent="primary" />
              <span style={{ fontStyle: "italic" }}>Loading trees</span>
            </div>
          ) : null}
        </div>
        <LineageChoices
          dispatch={dispatch}
          lineageChoice={lineageChoice}
          loading={lineageData?.loading}
        />
      </div>
    );
  }
}

export default Lineage;
