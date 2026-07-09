/*
Reducer for the pairwise ancestral-linkage heatmap window (bottom-right of the
UMAP pane) and the selected-linkage button's in-flight state.

State:
  selectedLoading - true while a target-mode ("selected") request is in flight.
  pairwiseLoading - true while a pairwise request is in flight.
  error           - last error (Error), or null.
  visible         - whether the heatmap window is shown.
  minimized       - whether the heatmap window is collapsed.
  groupby         - the categorical attribute the matrix was computed over.
  labels          - ordered category labels (rows == columns).
  matrix          - ordered, symmetrized normalized-enrichment values (row-major,
                    may contain nulls).
  vmin, vmax      - diverging color-scale bounds (symmetric about 0).
*/

const init = {
  selectedLoading: false,
  pairwiseLoading: false,
  error: null,
  visible: false,
  minimized: false,
  groupby: null,
  labels: null,
  matrix: null,
  vmin: -1,
  vmax: 1,
};

const AncestralLinkage = (state = init, action) => {
  switch (action.type) {
    case "ancestral linkage: selected start":
      return { ...state, selectedLoading: true, error: null };

    case "ancestral linkage: selected success":
      return { ...state, selectedLoading: false, error: null };

    case "ancestral linkage: pairwise start":
      return {
        ...state,
        pairwiseLoading: true,
        error: null,
        visible: true,
        minimized: false,
      };

    case "ancestral linkage: pairwise success":
      return {
        ...state,
        pairwiseLoading: false,
        error: null,
        visible: true,
        minimized: false,
        groupby: action.groupby,
        labels: action.labels,
        matrix: action.matrix,
        vmin: action.vmin,
        vmax: action.vmax,
      };

    case "ancestral linkage: error":
      return {
        ...state,
        selectedLoading: false,
        pairwiseLoading: false,
        error: action.error,
      };

    case "ancestral linkage: toggle minimize":
      return { ...state, minimized: !state.minimized };

    case "ancestral linkage: close":
      return { ...init };

    // A change to the cell population invalidates the computed matrix.
    case "subset to selection":
    case "reset subset":
      return { ...init };

    default:
      return state;
  }
};

export default AncestralLinkage;
