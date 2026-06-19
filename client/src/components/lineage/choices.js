import React from "react";
import {
  Button,
  ButtonGroup,
  Checkbox,
  H6,
  Popover,
  Position,
  Radio,
  RadioGroup,
} from "@blueprintjs/core";

import actions from "../../actions";

/*
Bottom-of-panel selectors for the lineage tree, modeled on the embedding
selector (components/embedding). One picks which tree(s) to plot, the other
picks the depth_key (x-axis). Multiple trees may be selected only when they
do not share observations (hasOverlap === false).
*/
const LineageChoices = ({ dispatch, lineageChoice, loading }) => {
  const {
    available,
    current,
    hasOverlap,
    availableDepthKeys,
    currentDepthKey,
  } = lineageChoice;

  const handleDepthKeyChange = (e) => {
    dispatch(actions.lineageDepthKeyChoiceAction(e.currentTarget.value));
  };

  const handleSingleTreeChange = (e) => {
    dispatch(actions.lineageTreeChoiceAction([e.currentTarget.value]));
  };

  const handleMultiTreeToggle = (name) => {
    const set = new Set(current);
    if (set.has(name)) set.delete(name);
    else set.add(name);
    // preserve the available order; an empty selection is allowed (clears the panel)
    const next = available.filter((n) => set.has(n));
    dispatch(actions.lineageTreeChoiceAction(next));
  };

  const handleSelectAllTrees = () => {
    dispatch(actions.lineageTreeChoiceAction(available));
  };

  const handleClearTrees = () => {
    // Deselect all so a single tree can then be picked without unchecking many.
    dispatch(actions.lineageTreeChoiceAction([]));
  };

  const treeLabel =
    current.length === 0
      ? "Select tree"
      : current.length === available.length
      ? "All trees"
      : current.length === 1
      ? current[0]
      : `${current.length} trees`;

  const treeContent = (
    <div style={{ padding: 10, maxHeight: 300, overflowY: "auto" }}>
      <H6>Tree</H6>
      {hasOverlap ? (
        <RadioGroup
          onChange={handleSingleTreeChange}
          selectedValue={current[0]}
        >
          {available.map((name) => (
            <Radio label={name} value={name} key={name} />
          ))}
        </RadioGroup>
      ) : (
        <>
          <ButtonGroup minimal style={{ marginBottom: 6 }}>
            <Button small text="All" onClick={handleSelectAllTrees} />
            <Button small text="None" onClick={handleClearTrees} />
          </ButtonGroup>
          {available.map((name) => (
            <Checkbox
              key={name}
              label={name}
              checked={current.includes(name)}
              onChange={() => handleMultiTreeToggle(name)}
            />
          ))}
        </>
      )}
    </div>
  );

  const depthContent = (
    <div style={{ padding: 10, maxHeight: 300, overflowY: "auto" }}>
      <H6>Depth</H6>
      <RadioGroup
        onChange={handleDepthKeyChange}
        selectedValue={currentDepthKey}
      >
        {availableDepthKeys.map((key) => (
          <Radio label={key} value={key} key={key} />
        ))}
      </RadioGroup>
    </div>
  );

  return (
    <ButtonGroup
      style={{
        padding: 8,
        display: "flex",
        justifyContent: "flex-start",
      }}
    >
      <Popover position={Position.TOP_LEFT} content={treeContent}>
        <Button
          type="button"
          icon="diagram-tree"
          rightIcon="caret-up"
          data-testid="lineage-tree-choice"
          loading={loading}
        >
          {treeLabel}
        </Button>
      </Popover>
      <Popover position={Position.TOP_LEFT} content={depthContent}>
        <Button
          type="button"
          icon="horizontal-distribution"
          rightIcon="caret-up"
          data-testid="lineage-depth-choice"
        >
          {currentDepthKey}
        </Button>
      </Popover>
    </ButtonGroup>
  );
};

export default LineageChoices;
