/*
State for the lineage tree panel selectors: which trees to plot and which
node attribute to use as the depth axis. Initialized from /lineage/meta.
*/
const LineageChoice = (
  state = {
    available: [], // all tree names (tdata.obst keys)
    current: [], // currently selected tree names
    hasOverlap: false, // trees share observations → single-select only
    alignment: "leaves", // "leaves" | "nodes" | "subset"
    availableDepthKeys: [], // numeric node attributes usable as depth axis
    currentDepthKey: "depth",
  },
  action
) => {
  switch (action.type) {
    case "lineage: meta loaded": {
      const {
        names,
        defaultTrees,
        depthKeys,
        defaultDepthKey,
        hasOverlap,
        alignment,
      } = action.meta;
      return {
        ...state,
        available: names,
        current: defaultTrees,
        availableDepthKeys: depthKeys,
        currentDepthKey: defaultDepthKey,
        hasOverlap,
        alignment,
      };
    }

    case "set lineage tree choice":
      return { ...state, current: action.current };

    case "set lineage depth key":
      return { ...state, currentDepthKey: action.currentDepthKey };

    default:
      return state;
  }
};

export default LineageChoice;
