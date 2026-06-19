/*
action creators related to the lineage tree panel
*/
import * as globals from "../globals";

/*
Fetch the decoded layout for the current tree selection + depth key and
dispatch it. Color and selection are handled client-side, so this is the only
network call the panel makes (on tree/depth-key change).
*/
async function _fetchLineageData(dispatch, getState) {
  const { annoMatrix, lineageChoice } = getState();
  if (!annoMatrix || !lineageChoice?.current?.length) return;
  dispatch({ type: "lineage: data load start" });
  try {
    // When a subset view is active, send the surviving obs row positions (the
    // view's row labels, in view order) so the server prunes each tree to the
    // induced subtree of those leaves. The returned obs indices are then in the
    // subset's coordinate space, matching the panel's color/selection arrays.
    const isSubset = annoMatrix.nObs < annoMatrix.schema.dataframe.nObs;
    const keepObs = isSubset ? annoMatrix.rowIndex.labels() : null;
    const data = await annoMatrix
      .base()
      .fetchLineage(
        lineageChoice.current,
        lineageChoice.currentDepthKey,
        keepObs
      );
    dispatch({ type: "lineage: data loaded", data });
  } catch (error) {
    dispatch({ type: "lineage: data load error", error });
  }
}

/*
Re-fetch the tree layout for the current view. Dispatched after the subset /
reset-subset actions so the panel switches to (or back from) the induced
subtree of the selected leaves.
*/
export const lineageRefetchAction = () => async (dispatch, getState) => {
  await _fetchLineageData(dispatch, getState);
};

/*
On initial load, fetch tree metadata for the selectors. If the dataset has no
trees (plain AnnData) the panel stays hidden. Otherwise load the default layout.
*/
export const lineageInitialLoad = () => async (dispatch, getState) => {
  try {
    const res = await fetch(
      `${globals.API.prefix}${globals.API.version}lineage/meta`,
      {
        method: "GET",
        headers: new Headers({ Accept: "application/json" }),
        credentials: "include",
      }
    );
    if (!res.ok) return;
    const meta = await res.json();
    if (!meta?.names?.length) return; // no trees → hide panel
    dispatch({ type: "lineage: meta loaded", meta });
    await _fetchLineageData(dispatch, getState);
  } catch (error) {
    dispatch({ type: "lineage: data load error", error });
  }
};

export const lineageTreeChoiceAction =
  (current) => async (dispatch, getState) => {
    dispatch({ type: "set lineage tree choice", current });
    await _fetchLineageData(dispatch, getState);
  };

export const lineageDepthKeyChoiceAction =
  (currentDepthKey) => async (dispatch, getState) => {
    dispatch({ type: "set lineage depth key", currentDepthKey });
    await _fetchLineageData(dispatch, getState);
  };

/*
Rectangular selection over the tree: select exactly the leaves' cells in the
shared crossfilter (by obs label), so the UMAP dims to match. obsRows are obs
positions in the current annoMatrix view (matching the leaf obs indices the
server emits for that view). Pass null/[] to clear the selection.
*/
export const lineageRectSelectAction =
  (obsRows) => async (dispatch, getState) => {
    const { annoMatrix, obsCrossfilter: prev } = getState();
    const indexName = annoMatrix.schema.annotations.obs.index;
    let obsCrossfilter;
    if (!obsRows || obsRows.length === 0) {
      obsCrossfilter = await prev.select("obs", indexName, { mode: "all" });
    } else {
      // Map the view-relative obsRows to obs index values (cell names) via the
      // current view's index, then select by exact name. Using the current
      // view (not base) keeps this correct whether or not a subset is active.
      const indexDf = await annoMatrix.fetch("obs", indexName);
      const names = indexDf.col(indexName).asArray();
      const values = obsRows.map((r) => names[r]);
      obsCrossfilter = await prev.select("obs", indexName, {
        mode: "exact",
        values,
      });
    }
    dispatch({ type: "lineage rect select", obsCrossfilter });
  };
