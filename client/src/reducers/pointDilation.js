const initialState = {
  metadataField: "",
  categoryField: "",
  // The set of category labels (of metadataField) to dilate/highlight. A single
  // label for the left-sidebar category hover; two labels for a pairwise linkage
  // heatmap cell hover. `null` when nothing is hovered.
  categoryFields: null,
};

const pointDialation = (state = initialState, action) => {
  const { metadataField, label: categoryField } = action;

  switch (action.type) {
    case "category value mouse hover start":
      return {
        ...state,
        metadataField,
        categoryField,
        categoryFields: [categoryField],
      };

    case "category value mouse hover end":
      if (
        metadataField === state.metadataField &&
        categoryField === state.categoryField
      ) {
        return initialState;
      }
      return state;

    // Highlight several categories of one field at once (pairwise linkage
    // heatmap cell hover → the cell's row + column categories).
    case "category values mouse hover start":
      return {
        metadataField: action.metadataField,
        categoryField: "",
        categoryFields: action.labels,
      };

    case "category values mouse hover end":
      return initialState;

    default:
      return state;
  }
};

export default pointDialation;
