/*
Action creators for ancestral linkage (pycea.tl.ancestral_linkage, metric="path").

Two entry points, triggered from the top-left of the lineage tree panel:
  * selected  — target-mode linkage: distance from every cell to the nearest
    currently-selected cell, added as a new continuous obs column and used to
    color the UMAP + tree.
  * pairwise  — pairwise-mode linkage over the current categorical color-by
    attribute (restricted to the cells in play — subset ∩ selection), shown as a
    clustered heatmap in the bottom-right window.
*/
import * as globals from "../globals";

async function _postJSON(path, body) {
  const res = await fetch(
    `${globals.API.prefix}${globals.API.version}${path}`,
    {
      method: "POST",
      headers: new Headers({
        "Content-Type": "application/json",
        Accept: "application/json",
      }),
      body: JSON.stringify(body),
      credentials: "include",
    }
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `request failed (${res.status})`);
  }
  return res.json();
}

// Name selected-linkage columns "Pop1 ancestral linkage", "Pop2 ...", picking the
// lowest unused index so removing one frees its slot.
function _nextPopColumnName(schema) {
  const exists = (n) => !!schema.annotations.obsByName[n];
  let i = 1;
  while (exists(`Pop${i} ancestral linkage`)) i += 1;
  return `Pop${i} ancestral linkage`;
}

/*
Target-mode linkage. Requires a proper subset of cells to be selected (the
target set). Adds the result as a new continuous obs column and colors by it.
*/
export const ancestralLinkageSelectedAction =
  () => async (dispatch, getState) => {
    const { annoMatrix, obsCrossfilter, lineageChoice } = getState();
    if (!annoMatrix || !obsCrossfilter) return;

    const nSelected = obsCrossfilter.countSelected();
    if (nSelected === 0 || nSelected >= annoMatrix.nObs) {
      dispatch({
        type: "ancestral linkage: error",
        error: new Error(
          "Select a subset of cells to use as the linkage target."
        ),
      });
      return;
    }
    const selected = Array.from(obsCrossfilter.allSelectedLabels());

    dispatch({ type: "ancestral linkage: selected start" });
    try {
      const { values } = await _postJSON("lineage/ancestral-linkage/selected", {
        selected,
        tree: lineageChoice?.current ?? null,
        depthKey: lineageChoice?.currentDepthKey ?? "depth",
      });

      // Full-obs Float32Array (null -> NaN); the base annoMatrix stores it and
      // any active subset view slices it lazily.
      const n = annoMatrix.base().nObs;
      const arr = new Float32Array(n);
      for (let i = 0; i < n; i += 1) {
        const v = values[i];
        arr[i] = v === null || v === undefined ? Number.NaN : v;
      }

      const name = _nextPopColumnName(annoMatrix.schema);
      const newObsCrossfilter = obsCrossfilter.addObsContinuousColumn(
        name,
        arr
      );
      dispatch({
        type: "ancestral linkage: selected success",
        annoMatrix: newObsCrossfilter.annoMatrix,
        obsCrossfilter: newObsCrossfilter,
      });
      // Color the UMAP + tree by the new continuous attribute.
      dispatch({ type: "color by continuous metadata", colorAccessor: name });
    } catch (error) {
      dispatch({ type: "ancestral linkage: error", error });
    }
  };

/*
Pairwise-mode linkage over the current categorical color-by attribute. The cells
in play (current subset ∩ current selection) become the category source; when the
whole dataset is in play the server uses all cells.
*/
export const ancestralLinkagePairwiseAction =
  () => async (dispatch, getState) => {
    const { annoMatrix, obsCrossfilter, colors, lineageChoice } = getState();
    if (!annoMatrix || !obsCrossfilter) return;

    if (
      colors?.colorMode !== "color by categorical metadata" ||
      !colors?.colorAccessor
    ) {
      dispatch({
        type: "ancestral linkage: error",
        error: new Error(
          "Color by a categorical attribute before running pairwise linkage."
        ),
      });
      return;
    }
    const groupby = colors.colorAccessor;

    // Cells in play: subset ∩ selection. Send null only when the whole dataset
    // is in play (no subset, no selection).
    const inPlay = Array.from(obsCrossfilter.allSelectedLabels());
    const isFull = inPlay.length === annoMatrix.schema.dataframe.nObs;
    const selected = isFull ? null : inPlay;

    dispatch({ type: "ancestral linkage: pairwise start" });
    try {
      const result = await _postJSON("lineage/ancestral-linkage/pairwise", {
        groupby,
        selected,
        tree: lineageChoice?.current ?? null,
        depthKey: lineageChoice?.currentDepthKey ?? "depth",
      });
      dispatch({
        type: "ancestral linkage: pairwise success",
        groupby,
        ...result,
      });
    } catch (error) {
      dispatch({ type: "ancestral linkage: error", error });
    }
  };

/*
Remove a "PopN ancestral linkage" continuous column (via the three-dot menu next
to its color-by button). If it is the active color-by, reset the color scale.
*/
export const ancestralLinkageRemoveColumnAction =
  (field) => (dispatch, getState) => {
    const { obsCrossfilter, colors } = getState();
    if (!obsCrossfilter) return;
    const newObsCrossfilter = obsCrossfilter.dropObsContinuousColumn(field);
    dispatch({
      type: "ancestral linkage: column removed",
      annoMatrix: newObsCrossfilter.annoMatrix,
      obsCrossfilter: newObsCrossfilter,
    });
    if (colors?.colorAccessor === field) {
      dispatch({ type: "reset colorscale" });
    }
  };

/*
Rename a "PopN ancestral linkage" continuous column. Keeps it as the active
color-by if it was one.
*/
export const ancestralLinkageRenameColumnAction =
  (field, newName) => (dispatch, getState) => {
    const { annoMatrix, obsCrossfilter, colors } = getState();
    if (!annoMatrix || !obsCrossfilter) return;
    const name = (newName || "").trim();
    if (!name || name === field) return;
    if (annoMatrix.schema.annotations.obsByName[name]) {
      dispatch({
        type: "ancestral linkage: error",
        error: new Error(`'${name}' is already in use.`),
      });
      return;
    }
    const wasColorBy = colors?.colorAccessor === field;
    const newObsCrossfilter = obsCrossfilter.renameObsContinuousColumn(
      field,
      name
    );
    dispatch({
      type: "ancestral linkage: column renamed",
      annoMatrix: newObsCrossfilter.annoMatrix,
      obsCrossfilter: newObsCrossfilter,
    });
    if (wasColorBy) {
      dispatch({ type: "color by continuous metadata", colorAccessor: name });
    }
  };

export const ancestralLinkageToggleMinimizeAction = () => ({
  type: "ancestral linkage: toggle minimize",
});

export const ancestralLinkageCloseAction = () => ({
  type: "ancestral linkage: close",
});
