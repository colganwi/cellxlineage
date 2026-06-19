import React from "react";
import { connect } from "react-redux";
import Categorical from "../categorical";
import * as globals from "../../globals";
import DynamicScatterplot from "../scatterplot/scatterplot";
import TopLeftLogoAndTitle from "./topLeftLogoAndTitle";
import Continuous from "../continuous/continuous";
import GeneExpression from "../geneExpression";

@connect((state) => ({
  scatterplotXXaccessor: state.controls.scatterplotXXaccessor,
  scatterplotYYaccessor: state.controls.scatterplotYYaccessor,
}))
class LeftSideBar extends React.Component {
  constructor(props) {
    super(props);
    this.state = { splitPct: 50, isDragging: false };
    this.splitContainerRef = React.createRef();
  }

  componentWillUnmount() {
    window.removeEventListener("mousemove", this.handleMouseMove);
    window.removeEventListener("mouseup", this.handleMouseUp);
  }

  handleDividerMouseDown = (e) => {
    e.preventDefault();
    this.setState({ isDragging: true });
    window.addEventListener("mousemove", this.handleMouseMove);
    window.addEventListener("mouseup", this.handleMouseUp);
  };

  handleMouseMove = (e) => {
    const { isDragging } = this.state;
    if (!isDragging || !this.splitContainerRef.current) return;
    const rect = this.splitContainerRef.current.getBoundingClientRect();
    const pct = Math.min(
      Math.max(((e.clientY - rect.top) / rect.height) * 100, 10),
      90
    );
    this.setState({ splitPct: pct });
  };

  handleMouseUp = () => {
    this.setState({ isDragging: false });
    window.removeEventListener("mousemove", this.handleMouseMove);
    window.removeEventListener("mouseup", this.handleMouseUp);
  };

  render() {
    const { scatterplotXXaccessor, scatterplotYYaccessor } = this.props;
    const { splitPct, isDragging } = this.state;

    return (
      <div
        style={{
          borderRight: `1px solid ${globals.lightGrey}`,
          display: "flex",
          flexDirection: "column",
          height: "100%",
        }}
      >
        <TopLeftLogoAndTitle />
        <div
          ref={this.splitContainerRef}
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            minHeight: 0,
          }}
        >
          <div
            style={{
              flex: `0 0 ${splitPct}%`,
              width: globals.leftSidebarWidth,
              overflowY: "auto",
              minHeight: 0,
            }}
          >
            <Categorical />
            <Continuous />
          </div>
          {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- divider is mouse-only, no keyboard interaction needed */}
          <div
            onMouseDown={this.handleDividerMouseDown}
            style={{
              flexShrink: 0,
              height: 6,
              cursor: "row-resize",
              backgroundColor: isDragging
                ? "rgb(180,180,180)"
                : "rgb(210,210,210)",
              borderTop: `1px solid rgb(180,180,180)`,
              borderBottom: `1px solid rgb(180,180,180)`,
            }}
          />
          <div
            style={{
              flex: 1,
              width: globals.leftSidebarWidth,
              overflowY: "auto",
              minHeight: 0,
              padding: globals.leftSidebarSectionPadding,
            }}
          >
            <GeneExpression />
          </div>
        </div>
        {scatterplotXXaccessor && scatterplotYYaccessor ? (
          <DynamicScatterplot />
        ) : null}
      </div>
    );
  }
}

export default LeftSideBar;
