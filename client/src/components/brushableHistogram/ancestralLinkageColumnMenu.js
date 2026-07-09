import React from "react";
import { connect } from "react-redux";
import {
  Button,
  Classes,
  Dialog,
  Icon,
  InputGroup,
  Intent,
  Menu,
  MenuItem,
  Popover,
  Position,
} from "@blueprintjs/core";
import { IconNames } from "@blueprintjs/icons";

import actions from "../../actions";

/*
Three-dot actions menu shown next to the color-by button of a "PopN ancestral
linkage" continuous obs column, mirroring the edit-name / delete menu that
user-created categorical annotations get. Edit-name opens a small rename dialog.
*/
@connect((state) => ({
  schema: state.annoMatrix?.schema,
}))
class AncestralLinkageColumnMenu extends React.PureComponent {
  constructor(props) {
    super(props);
    this.state = { renaming: false, name: props.field, error: null };
  }

  openRename = () => {
    const { field } = this.props;
    this.setState({ renaming: true, name: field, error: null });
  };

  closeRename = () => this.setState({ renaming: false });

  handleNameChange = (e) => {
    const name = e.target.value;
    const { schema, field } = this.props;
    let error = null;
    if (!name || name.trim().length === 0) {
      error = "Name required";
    } else if (name !== field && schema?.annotations?.obsByName?.[name]) {
      error = "Name already in use";
    }
    this.setState({ name, error });
  };

  handleRename = () => {
    const { dispatch, field } = this.props;
    const { name, error } = this.state;
    if (error || !name || name.trim() === field) {
      this.closeRename();
      return;
    }
    dispatch(actions.ancestralLinkageRenameColumnAction(field, name.trim()));
    this.closeRename();
  };

  handleDelete = () => {
    const { dispatch, field } = this.props;
    dispatch(actions.ancestralLinkageRemoveColumnAction(field));
  };

  render() {
    const { field } = this.props;
    const { renaming, name, error } = this.state;
    return (
      <>
        <Popover
          position={Position.BOTTOM}
          content={
            <Menu>
              <MenuItem
                icon="edit"
                text="Edit name"
                data-testid={`${field}:edit-name`}
                onClick={this.openRename}
              />
              <MenuItem
                icon={IconNames.TRASH}
                intent={Intent.DANGER}
                text="Delete this attribute"
                data-testid={`${field}:delete`}
                onClick={this.handleDelete}
              />
            </Menu>
          }
        >
          <Button
            minimal
            icon={<Icon icon="more" iconSize={12} />}
            data-testid={`${field}:see-actions`}
            style={{ marginRight: 2 }}
          />
        </Popover>
        <Dialog
          isOpen={renaming}
          onClose={this.closeRename}
          title="Edit attribute name"
        >
          <div className={Classes.DIALOG_BODY}>
            <InputGroup
              value={name}
              onChange={this.handleNameChange}
              intent={error ? Intent.DANGER : Intent.NONE}
              // eslint-disable-next-line jsx-a11y/no-autofocus -- rename dialog
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") this.handleRename();
              }}
            />
            {error ? (
              <div style={{ color: "red", marginTop: 6 }}>{error}</div>
            ) : null}
          </div>
          <div className={Classes.DIALOG_FOOTER}>
            <div className={Classes.DIALOG_FOOTER_ACTIONS}>
              <Button onClick={this.closeRename}>Cancel</Button>
              <Button
                intent={Intent.PRIMARY}
                onClick={this.handleRename}
                disabled={!!error}
              >
                Rename
              </Button>
            </div>
          </div>
        </Dialog>
      </>
    );
  }
}

export default AncestralLinkageColumnMenu;
