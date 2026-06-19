/*
Vertical zoom/pan for the tree, active when the "zoom" interaction tool is
selected. Zoom changes only the vertical scale — the depth (horizontal) axis
always shows the full root→leaves span. Zooming subsets the visible leaves to a
[lo, hi] window in leaf space [0,1]:
  - wheel: zoom in/out centered on the cursor's leaf position
  - drag: pan the window vertically
  - double-click: reset to the full tree
The window is read/written via callbacks so the Lineage component owns the
state and re-renders on change.
*/
const MIN_RANGE = 0.004; // smallest visible fraction of leaves
const ZOOM_STEP = 0.85; // wheel-up shrinks the window to 85%

export default function setupTreeZoom(
  canvas,
  { getMode, getView, setView, getPlotRect }
) {
  let panning = false;
  let lastY = 0;

  const cursorY = (e) => e.clientY - canvas.getBoundingClientRect().top;

  // pixel y → leaf position in the current view window
  const pxToLeaf = (py) => {
    const { yTop, yBot } = getPlotRect();
    const { lo, hi } = getView();
    return lo + ((py - yTop) / (yBot - yTop)) * (hi - lo);
  };

  const clampView = (loIn, hiIn) => {
    let lo = loIn;
    let hi = hiIn;
    if (hi - lo >= 1) return { lo: 0, hi: 1 };
    if (hi - lo < MIN_RANGE) {
      const mid = (lo + hi) / 2;
      lo = mid - MIN_RANGE / 2;
      hi = mid + MIN_RANGE / 2;
    }
    if (lo < 0) {
      hi -= lo;
      lo = 0;
    }
    if (hi > 1) {
      lo -= hi - 1;
      hi = 1;
    }
    return { lo, hi };
  };

  const onWheel = (e) => {
    if (getMode() !== "zoom") return;
    e.preventDefault();
    const { lo, hi } = getView();
    const focus = pxToLeaf(cursorY(e));
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    setView(
      clampView(focus - (focus - lo) * factor, focus + (hi - focus) * factor)
    );
  };

  const onMove = (e) => {
    if (!panning) return;
    const py = cursorY(e);
    const { yTop, yBot } = getPlotRect();
    const { lo, hi } = getView();
    const dLeaf = ((py - lastY) / (yBot - yTop)) * (hi - lo);
    lastY = py;
    setView(clampView(lo - dLeaf, hi - dLeaf));
  };

  const onUp = () => {
    panning = false;
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  };

  const onDown = (e) => {
    if (e.button !== 0 || getMode() !== "zoom") return;
    panning = true;
    lastY = cursorY(e);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const onDblClick = () => {
    if (getMode() !== "zoom") return;
    setView({ lo: 0, hi: 1 });
  };

  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("mousedown", onDown);
  canvas.addEventListener("dblclick", onDblClick);

  return {
    detach() {
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("dblclick", onDblClick);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    },
  };
}
