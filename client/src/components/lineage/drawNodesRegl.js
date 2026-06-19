/*
Draw internal nodes as colored points. Used when the TreeData alignment is not
"leaves" — observations map to internal nodes, so nodes are colored like the
UMAP instead of drawing a leaf annotation bar (mirrors pycea.pl.nodes).
Positions are data coordinates (x = depth, y in [0,1]) mapped to pixels in the
shader, matching drawBranchesRegl.
*/
export default function drawNodesRegl(regl) {
  return regl({
    vert: `
    precision mediump float;
    attribute vec2 position;
    attribute vec3 color;
    attribute float selected;
    uniform mat3 projection;
    uniform float xM, xB, yM, yB;
    uniform float pointSize, dimAlpha;
    varying vec4 fragColor;
    void main() {
      float px = xM * position.x + xB;
      float py = yM * position.y + yB;
      vec3 xy = projection * vec3(px, py, 1.);
      gl_Position = vec4(xy.xy, 0., 1.);
      gl_PointSize = pointSize;
      float alpha = selected > 0.5 ? 1.0 : dimAlpha;
      fragColor = vec4(color, alpha);
    }`,

    frag: `
    precision mediump float;
    varying vec4 fragColor;
    void main() {
      if (length(gl_PointCoord.xy - 0.5) > 0.5) discard;
      gl_FragColor = fragColor;
    }`,

    attributes: {
      position: regl.prop("position"),
      color: regl.prop("color"),
      selected: regl.prop("selected"),
    },

    uniforms: {
      projection: regl.prop("projection"),
      xM: regl.prop("xM"),
      xB: regl.prop("xB"),
      yM: regl.prop("yM"),
      yB: regl.prop("yB"),
      pointSize: regl.prop("pointSize"),
      dimAlpha: regl.prop("dimAlpha"),
    },

    scissor: { enable: true, box: regl.prop("scissorBox") },

    count: regl.prop("count"),
    primitive: "points",

    blend: {
      enable: true,
      func: {
        srcRGB: "src alpha",
        srcAlpha: 1,
        dstRGB: "one minus src alpha",
        dstAlpha: "one minus src alpha",
      },
    },
  });
}
