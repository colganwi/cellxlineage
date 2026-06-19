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
    // keep at least one tree selected, preserving the available order
    const next = available.filter((n) => set.has(n));
    if (next.length) dispatch(actions.lineageTreeChoiceAction(next));
  };

  const treeLabel =
    current.length === available.length
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
        available.map((name) => (
          <Checkbox
            key={name}
            label={name}
            checked={current.includes(name)}
            onChange={() => handleMultiTreeToggle(name)}
          />
        ))
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
