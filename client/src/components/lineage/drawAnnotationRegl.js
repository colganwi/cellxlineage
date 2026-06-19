/*
Draw the leaf annotation bar as an instanced strip of quads — one quad per
leaf, colored exactly like the UMAP (per-leaf color), and dimmed (low alpha)
when the leaf's cell is not in the current selection. A unit-quad geometry is
shared across instances; per-leaf attributes are the leaf y position, color,
and selection flag. Scales to >1M leaves via instancing.

Requires the ANGLE_instanced_arrays extension (requested when regl is created).
*/
export default function drawAnnotationRegl(regl) {
  return regl({
    vert: `
    precision mediump float;
    attribute vec2 corner;     // shared unit quad, [0,1]^2
    attribute float leafY;     // per-instance leaf position in [0,1]
    attribute vec3 color;      // per-instance rgb (0..1)
    attribute float selected;  // per-instance: 1 = bright, 0 = dimmed
    attribute float highlighted; // per-instance: 1 = hovered category
    uniform mat3 projection;
    uniform float stripX0, stripWidth;  // pixels
    uniform float yM, yB;               // leafY -> pixel center
    uniform float cellHalf;             // half-height of a leaf cell, pixels
    uniform float dimAlpha;
    uniform float highlightScale;       // width multiplier for hovered category
    varying vec4 fragColor;
    void main() {
      // Hovered-category leaves widen (and stay fully opaque) so they stand out.
      float w = stripWidth * (highlighted > 0.5 ? highlightScale : 1.0);
      float px = stripX0 + corner.x * w;
      float cy = yM * leafY + yB;
      float py = cy + (corner.y - 0.5) * 2.0 * cellHalf;
      vec3 xy = projection * vec3(px, py, 1.);
      gl_Position = vec4(xy.xy, 0., 1.);
      float alpha = (selected > 0.5 || highlighted > 0.5) ? 1.0 : dimAlpha;
      fragColor = vec4(color, alpha);
    }`,

    frag: `
    precision mediump float;
    varying vec4 fragColor;
    void main() { gl_FragColor = fragColor; }`,

    attributes: {
      corner: regl.prop("corner"),
      leafY: { buffer: regl.prop("leafY"), divisor: 1 },
      color: { buffer: regl.prop("color"), divisor: 1 },
      selected: { buffer: regl.prop("selected"), divisor: 1 },
      highlighted: { buffer: regl.prop("highlighted"), divisor: 1 },
    },

    uniforms: {
      projection: regl.prop("projection"),
      stripX0: regl.prop("stripX0"),
      stripWidth: regl.prop("stripWidth"),
      yM: regl.prop("yM"),
      yB: regl.prop("yB"),
      cellHalf: regl.prop("cellHalf"),
      dimAlpha: regl.prop("dimAlpha"),
      highlightScale: regl.prop("highlightScale"),
    },

    scissor: { enable: true, box: regl.prop("scissorBox") },

    count: 6,
    instances: regl.prop("instances"),
    primitive: "triangles",

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
