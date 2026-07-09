import React from "react";
import { connect } from "react-redux";
import { Button, ButtonGroup, Spinner } from "@blueprintjs/core";

import * as globals from "../../globals";
import actions from "../../actions";
import { linkageDivergingColor } from "../../util/stateManager/colorHelpers";

const MISSING = "#d9d9d9"; // null / undiagonalizable cells

// Diverging ramp, t=0 -> red (low value = more related), t=1 -> blue. Same ramp
// used to color the UMAP/tree by "PopN ancestral linkage" columns (see
// colorHelpers.linkageDivergingColor).
function rampColor(t) {
  return linkageDivergingColor(Math.max(0, Math.min(1, t)));
}

function truncate(s, n = 16) {
  const str = String(s);
  return str.length > n ? `${str.slice(0, n - 1)}…` : str;
}

const CELL = 15; // px per matrix cell
const LEFT = 118; // row-label gutter
const BOTTOM = 96; // col-label gutter
const TOP = 8;
const CBAR_W = 14; // colorbar width
const CBAR_GAP = 20;
const CBAR_LABELS = 34;

class AncestralLinkageHeatmap extends React.PureComponent {
  renderHeatmap() {
    const { matrix, labels, vmin, vmax } = this.props;
    if (!matrix || !labels || labels.length === 0) return null;
    const n = labels.length;
    const grid = n * CELL;
    const cbarX = LEFT + grid + CBAR_GAP;
    const width = cbarX + CBAR_W + CBAR_LABELS;
    const height = TOP + grid + BOTTOM;
    const range = vmax - vmin || 1;

    const cells = [];
    for (let i = 0; i < n; i += 1) {
      for (let j = 0; j < n; j += 1) {
        const v = matrix[i][j];
        const fill =
          v === null || v === undefined
            ? MISSING
            : rampColor((v - vmin) / range);
        cells.push(
          <rect
            key={`c-${labels[i]}-${labels[j]}`}
            x={LEFT + j * CELL}
            y={TOP + i * CELL}
            width={CELL}
            height={CELL}
            fill={fill}
            shapeRendering="crispEdges"
          />
        );
      }
    }

    const rowLabels = labels.map((lab, i) => (
      <text
        key={`r-${lab}`}
        x={LEFT - 4}
        y={TOP + i * CELL + CELL / 2}
        textAnchor="end"
        dominantBaseline="central"
        fontSize={9}
        fill="#333"
      >
        {/* native tooltip: full name on hover, since long names are clipped */}
        <title>{lab}</title>
        {truncate(lab)}
      </text>
    ));
    const colLabels = labels.map((lab, j) => {
      const cx = LEFT + j * CELL + CELL / 2;
      const cy = TOP + grid + 4;
      return (
        <text
          key={`col-${lab}`}
          x={cx}
          y={cy}
          textAnchor="end"
          dominantBaseline="central"
          fontSize={9}
          fill="#333"
          transform={`rotate(-45 ${cx} ${cy})`}
        >
          <title>{lab}</title>
          {truncate(lab, 14)}
        </text>
      );
    });

    // Vertical colorbar (top = vmax, bottom = vmin) via 24 stacked bands.
    const bands = 24;
    const cbar = [];
    for (let k = 0; k < bands; k += 1) {
      const t = 1 - k / (bands - 1); // top band = high
      cbar.push(
        <rect
          key={`cb-${t.toFixed(4)}`}
          x={cbarX}
          y={TOP + (k * grid) / bands}
          width={CBAR_W}
          height={grid / bands + 1}
          fill={rampColor(t)}
        />
      );
    }
    const cbarTicks = [
      { t: 0, v: vmax },
      { t: 0.5, v: (vmin + vmax) / 2 },
      { t: 1, v: vmin },
    ].map((tick) => (
      <text
        key={`ct-${tick.t}`}
        x={cbarX + CBAR_W + 3}
        y={TOP + tick.t * grid}
        textAnchor="start"
        dominantBaseline="central"
        fontSize={9}
        fill="#333"
      >
        {tick.v.toFixed(1)}
      </text>
    ));

    return (
      <svg width={width} height={height} style={{ display: "block" }}>
        {cells}
        {rowLabels}
        {colLabels}
        {cbar}
        {cbarTicks}
      </svg>
    );
  }

  render() {
    const { dispatch, visible, minimized, pairwiseLoading, groupby } =
      this.props;
    if (!visible) return null;

    return (
      <div
        id="ancestral-linkage-heatmap"
        data-testid="ancestral-linkage-heatmap"
        style={{
          position: "fixed",
          bottom: 48 /* bottom toolbar gutter, matches the scatterplot panel */,
          right: globals.rightSidebarWidth + globals.scatterplotMarginLeft,
          background: "white",
          boxShadow: "0px 0px 3px 2px rgba(153,153,153,0.2)",
          borderRadius: "3px 3px 0px 0px",
          zIndex: 3,
          padding: "6px 8px 8px 8px",
          // Fill the UMAP pane: from the left sidebar to just left of the right
          // sidebar (where this panel is anchored), and up to 90% of the height.
          maxWidth: `calc(100vw - ${
            globals.leftSidebarWidth +
            globals.rightSidebarWidth +
            globals.scatterplotMarginLeft
          }px)`,
          maxHeight: "90vh",
          overflow: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <span style={{ fontWeight: 500, fontSize: 12, paddingRight: 24 }}>
            {`pairwise linkage${groupby ? `: ${groupby}` : ""}`}
          </span>
          <ButtonGroup minimal>
            <Button
              small
              icon={minimized ? "maximize" : "minimize"}
              data-testid="ancestral-linkage-minimize"
              onClick={() =>
                dispatch(actions.ancestralLinkageToggleMinimizeAction())
              }
            />
            <Button
              small
              icon="cross"
              data-testid="ancestral-linkage-close"
              onClick={() => dispatch(actions.ancestralLinkageCloseAction())}
            />
          </ButtonGroup>
        </div>
        {!minimized &&
          (pairwiseLoading ? (
            <div style={{ padding: 24 }}>
              <Spinner size={24} />
            </div>
          ) : (
            this.renderHeatmap()
          ))}
      </div>
    );
  }
}

export default connect((state) => ({
  visible: state.ancestralLinkage.visible,
  minimized: state.ancestralLinkage.minimized,
  pairwiseLoading: state.ancestralLinkage.pairwiseLoading,
  groupby: state.ancestralLinkage.groupby,
  labels: state.ancestralLinkage.labels,
  matrix: state.ancestralLinkage.matrix,
  vmin: state.ancestralLinkage.vmin,
  vmax: state.ancestralLinkage.vmax,
}))(AncestralLinkageHeatmap);
