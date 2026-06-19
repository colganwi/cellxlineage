/*
Draw tree branches as GL line segments. Positions are supplied in data
coordinates (x = depth, y = leaf position in [0,1]) and mapped to pixels in the
shader via the (xM,xB,yM,yB) uniforms, so a resize only changes uniforms — the
position buffer is uploaded once per layout fetch.
*/
export default function drawBranchesRegl(regl) {
  return regl({
    vert: `
    precision mediump float;
    attribute vec2 position;
    uniform mat3 projection;
    uniform float xM, xB, yM, yB;
    void main() {
      float px = xM * position.x + xB;
      float py = yM * position.y + yB;
      vec3 xy = projection * vec3(px, py, 1.);
      gl_Position = vec4(xy.xy, 0., 1.);
    }`,

    frag: `
    precision mediump float;
    uniform vec4 color;
    void main() { gl_FragColor = color; }`,

    attributes: {
      position: regl.prop("position"),
    },

    uniforms: {
      projection: regl.prop("projection"),
      color: regl.prop("color"),
      xM: regl.prop("xM"),
      xB: regl.prop("xB"),
      yM: regl.prop("yM"),
      yB: regl.prop("yB"),
    },

    scissor: { enable: true, box: regl.prop("scissorBox") },

    count: regl.prop("count"),
    primitive: "lines",
    lineWidth: 1,

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
