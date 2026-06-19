import actions from "../../actions";

/*
Rectangular drag selector over the tree canvas. Acts as a rectangle (not a
lasso): the drag's vertical extent selects the leaves whose cells fall within
it, which are then selected in the shared crossfilter so the UMAP dims to
match. A small/no drag clears the selection.

canvas pixel size is kept equal to its CSS size (see Lineage.measure), so
client coordinates map 1:1 to the leaf pixel geometry.
*/
const CLICK_THRESHOLD = 3; // px — below this a drag is treated as a clear

export default function setupTreeSelector(
  canvas,
  { getLeafGeometry, getMode, dispatch }
) {
  const parent = canvas.parentNode;
  let startX = null;
  let startY = null;
  let rectEl = null;
  let dragging = false;

  const getXY = (e) => {
    const rect = canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  };

  const onMove = (e) => {
    if (!dragging) return;
    const [x, y] = getXY(e);
    rectEl.style.left = `${Math.min(startX, x)}px`;
    rectEl.style.top = `${Math.min(startY, y)}px`;
    rectEl.style.width = `${Math.abs(x - startX)}px`;
    rectEl.style.height = `${Math.abs(y - startY)}px`;
  };

  const onUp = (e) => {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    if (rectEl) {
      rectEl.remove();
      rectEl = null;
    }
    if (!dragging) return;
    dragging = false;

    const [x, y] = getXY(e);
    if (
      Math.abs(x - startX) < CLICK_THRESHOLD &&
      Math.abs(y - startY) < CLICK_THRESHOLD
    ) {
      dispatch(actions.lineageRectSelectAction(null)); // clear
      return;
    }

    const geom = getLeafGeometry();
    if (!geom) return;
    const { leafY, leafObs, yM, yB } = geom;
    const yMin = Math.min(startY, y);
    const yMax = Math.max(startY, y);
    const rows = [];
    for (let i = 0, n = leafY.length; i < n; i += 1) {
      const py = yM * leafY[i] + yB;
      if (py >= yMin && py <= yMax) rows.push(leafObs[i]);
    }
    dispatch(actions.lineageRectSelectAction(rows));
  };

  const onDown = (e) => {
    if (e.button !== 0) return;
    if (getMode && getMode() !== "select") return; // zoom tool handles its own drag
    [startX, startY] = getXY(e);
    dragging = true;
    rectEl = document.createElement("div");
    rectEl.style.cssText =
      "position:absolute;border:1px dashed #137cbd;" +
      "background:rgba(19,124,189,0.1);pointer-events:none;z-index:10;";
    parent.appendChild(rectEl);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  canvas.addEventListener("mousedown", onDown);

  return {
    detach() {
      canvas.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    },
  };
}
