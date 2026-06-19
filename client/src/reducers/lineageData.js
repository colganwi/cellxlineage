/*
Decoded lineage tree layout: branch segments, leaf positions + obs row
indices, and (when alignment != "leaves") internal node positions + obs row
indices. Refetched only when the tree selection or depth key changes.
*/
const LineageData = (
  state = {
    loading: false,
    error: null,
    data: null, // { branches: {x0,y0,x1,y1}, leaves: {y,obs}, nodes: {x,y,obs}|null }
  },
  action
) => {
  switch (action.type) {
    case "lineage: data load start":
      return { ...state, loading: true, error: null };

    case "lineage: data loaded":
      return { loading: false, error: null, data: action.data };

    case "lineage: data load error":
      return { ...state, loading: false, error: action.error };

    default:
      return state;
  }
};

export default LineageData;
