/*
Vertical scrollbar overlaid on the right edge of the tree plot. It mirrors the
tree's vertical zoom window (`view = {lo, hi}` in leaf space [0,1]) and lets the
user pan that window by dragging the thumb — this works in ANY interaction mode
(select, zoom, …), so cells can be panned while the selection tool is active.
Hidden when the full tree is visible (nothing to scroll).
*/
import React from "react";

const TRACK_WIDTH = 8; // px

export default class TreeScrollbar extends React.PureComponent {
  constructor(props) {
    super(props);
    this.trackRef = React.createRef();
    this.drag = null; // {startY, startLo, size} while dragging the thumb
  }

  componentWillUnmount() {
    this.endDrag();
  }

  onThumbDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation(); // don't start a lasso/zoom on the canvas underneath
    const { view } = this.props;
    this.drag = {
      startY: e.clientY,
      startLo: view.lo,
      size: view.hi - view.lo,
    };
    window.addEventListener("mousemove", this.onMove);
    window.addEventListener("mouseup", this.endDrag);
  };

  onMove = (e) => {
    if (!this.drag) return;
    const h = this.trackHeight();
    if (h <= 0) return;
    const { onChange } = this.props;
    const { size, startLo, startY } = this.drag;
    let lo = startLo + (e.clientY - startY) / h;
    lo = Math.max(0, Math.min(1 - size, lo));
    onChange({ lo, hi: lo + size });
  };

  endDrag = () => {
    this.drag = null;
    window.removeEventListener("mousemove", this.onMove);
    window.removeEventListener("mouseup", this.endDrag);
  };

  // Click in the empty track (above/below the thumb) pages the window by one
  // window-height toward the click, like a native scrollbar.
  onTrackDown = (e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const track = this.trackRef.current;
    const h = this.trackHeight();
    if (!track || h <= 0) return;
    const { view, onChange } = this.props;
    const size = view.hi - view.lo;
    const frac = (e.clientY - track.getBoundingClientRect().top) / h;
    let lo = view.lo + (frac < view.lo ? -size : size);
    lo = Math.max(0, Math.min(1 - size, lo));
    onChange({ lo, hi: lo + size });
  };

  trackHeight() {
    const track = this.trackRef.current;
    return track ? track.clientHeight : 0;
  }

  render() {
    const { view, top, bottom } = this.props;
    const size = view.hi - view.lo;
    if (size >= 1) return null; // full tree visible → nothing to scroll

    return (
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- scrollbar is mouse-only, no keyboard interaction needed
      <div
        ref={this.trackRef}
        onMouseDown={this.onTrackDown}
        style={{
          position: "absolute",
          top,
          bottom,
          right: 2,
          width: TRACK_WIDTH,
          borderRadius: TRACK_WIDTH / 2,
          background: "rgba(0,0,0,0.06)",
          zIndex: 2,
        }}
      >
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- scrollbar thumb is mouse-only, no keyboard interaction needed */}
        <div
          onMouseDown={this.onThumbDown}
          style={{
            position: "absolute",
            left: 0,
            width: "100%",
            top: `${view.lo * 100}%`,
            height: `${size * 100}%`,
            borderRadius: TRACK_WIDTH / 2,
            background: "rgba(0,0,0,0.28)",
            cursor: "grab",
          }}
        />
      </div>
    );
  }
}
