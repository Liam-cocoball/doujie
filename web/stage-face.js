import * as T from 'three';

const EYES = /^(Upper_liner|Eye_whites|Iris_outer_ring|Coffee_iris|Amber_lower_iris|Round_pupil|Square_catchlight|Subtle_catchlight|Upper_lash_line|Small_outer_lash|Lower_lash_accent)/i;
const IRIS = /^(Iris_outer_ring|Coffee_iris|Amber_lower_iris|Round_pupil|Square_catchlight|Subtle_catchlight)/i;
// Paired eye heights, brow offsets, gaze, lip width, smile curvature and one-sided curl.
const faces = {
  neutral:   {eyes:[1,1], brows:[0,0], gaze:0, width:.049, smile:.006, curl:0},
  happy:     {eyes:[.76,.8], brows:[.022,.023], gaze:0, width:.069, smile:.027, curl:.002},
  surprised: {eyes:[1.14,1.15], brows:[.048,.050], gaze:0, width:.033, smile:-.001, curl:0},
  grumpy:    {eyes:[.61,.72], brows:[-.021,-.024], gaze:.007, width:.060, smile:-.016, curl:.003},
  skeptical: {eyes:[.96,.56], brows:[.060,-.015], gaze:.024, width:.048, smile:-.004, curl:.012},
  smirk:     {eyes:[.68,.91], brows:[-.008,.036], gaze:-.017, width:.061, smile:.009, curl:.021},
  deadpan:   {eyes:[.55,.57], brows:[-.006,-.006], gaze:0, width:.058, smile:-.002, curl:0},
  soft:      {eyes:[.86,.89], brows:[.013,.010], gaze:-.003, width:.047, smile:.012, curl:.002},
};
const tilt = {grumpy:[-.21,.20], skeptical:[.16,.055], smirk:[-.09,-.15], soft:[-.06,.05]};
const mix = T.MathUtils.lerp;

function pivot(parent, meshes) {
  const group = new T.Group();
  parent.add(group);
  if (meshes.length) {
    const bounds = new T.Box3();
    for (const mesh of meshes) bounds.expandByObject(mesh, true);
    group.position.copy(parent.worldToLocal(bounds.getCenter(new T.Vector3())));
    group.updateWorldMatrix(true, false);
    for (const mesh of meshes) group.attach(mesh);
  }
  return group;
}

// The GLB has a sculpted closed smile, but no jaw or phoneme morphs. Fit a small
// curved opening over that lip, keeping the corners expressive while audio opens it.
function mouthRibbon(head, smile) {
  const slices = 20, rows = 3;
  const coords = new T.BufferAttribute(new Float32Array((slices + 1) * rows * 3), 3);
  coords.setUsage(T.DynamicDrawUsage);
  const geometry = new T.BufferGeometry();
  geometry.setAttribute('position', coords);
  const indices = [];
  for (let row = 0; row < rows - 1; row++) {
    for (let col = 0; col < slices; col++) {
      const a = row * (slices + 1) + col, b = a + slices + 1;
      indices.push(a,b,a+1, a+1,b,b+1);
    }
    geometry.addGroup(row * slices * 6, slices * 6, row);
  }
  geometry.setIndex(indices);
  const material = colour => new T.MeshBasicMaterial({color:colour, side:T.DoubleSide});
  const mesh = new T.Mesh(geometry, [material(0x541e2c), material(0xb85b63)]);
  mesh.frustumCulled = false;
  head.add(mesh);
  mesh.position.copy(smile.position);
  mesh.position.z += .013;
  let width = faces.neutral.width, bend = 0, curl = 0;
  return (face, aperture, speechLine, f) => {
    width = mix(width, face.width, f);
    bend = mix(bend, face.smile, f);
    curl = mix(curl, face.curl, f);
    mesh.visible = speechLine || aperture > .035 || face !== faces.neutral;
    smile.visible = !mesh.visible;
    if (!mesh.visible) return;
    for (let col = 0; col <= slices; col++) {
      const t = col / slices * 2 - 1;
      const inner = Math.sqrt(Math.max(0, 1 - t * t));
      const x = t * width * (1 - .14 * aperture);
      const baseline = bend * t*t + curl*t - .002;
      const height = (.0034 + .042 * aperture) * inner;
      const z = -.009 * t*t;
      coords.setXYZ(col, x, baseline + height * .37, z);
      coords.setXYZ(col + slices + 1, x, baseline - height * .39, z);
      coords.setXYZ(col + 2 * (slices + 1), x, baseline - height * .63, z);
    }
    coords.needsUpdate = true;
  };
}

export function rigFace(head) {
  const eyes = [[],[]], brows = [[],[]], lips = [];
  head.traverse(mesh => {
    if (!mesh.isMesh) return;
    if (EYES.test(mesh.name) || /^Sculpted_eyebrow/i.test(mesh.name)) {
      const side = new T.Box3().setFromObject(mesh, true).getCenter(new T.Vector3()).x > 0 ? 1 : 0;
      (EYES.test(mesh.name) ? eyes : brows)[side].push(mesh);
    } else if (/^(Quiet_smile|Subtle_lip)/i.test(mesh.name)) lips.push(mesh);
  });
  const lids = [], pupils = [], eyebrows = [];
  for (let i=0; i<2; i++) {
    const lid = pivot(head, eyes[i]);
    lids.push(lid);
    const pupil = pivot(lid, eyes[i].filter(mesh => IRIS.test(mesh.name)));
    pupils.push({mesh:pupil, x:pupil.position.x, y:pupil.position.y});
    const brow = pivot(head, brows[i]);
    eyebrows.push({mesh:brow, y:brow.position.y});
  }
  const drawMouth = mouthRibbon(head, pivot(head, lips));
  let blinkStart = -10, nextBlink = 0;
  return (now, dt, mood, aperture, gaze, pitch, accent, speechLine, motion) => {
    const face = faces[mood] || faces.neutral, f = 1 - Math.exp(-dt * 13);
    if (nextBlink === 0) nextBlink = now + 2.1;
    if (now >= nextBlink) {
      blinkStart = now;
      nextBlink = now + 2.6 + Math.random() * 2.8;
    }
    const age = now - blinkStart;
    const blink = age >= 0 && age < .16 ? .09 + .91 * Math.abs(age - .08) / .08 : 1;
    for (let i=0; i<2; i++) {
      lids[i].scale.y = mix(lids[i].scale.y, blink * (face.eyes[i] + accent*.06), Math.min(1,dt*40));
      const brow = eyebrows[i];
      brow.mesh.position.y = mix(brow.mesh.position.y, brow.y + face.brows[i] + accent*.014*motion, f);
      brow.mesh.rotation.z = mix(brow.mesh.rotation.z, tilt[mood]?.[i] || 0, f);
      const pupil = pupils[i];
      pupil.mesh.position.x = mix(pupil.mesh.position.x, pupil.x + face.gaze + gaze*motion, f);
      pupil.mesh.position.y = mix(pupil.mesh.position.y, pupil.y + pitch*.017*motion, f);
    }
    drawMouth(face, aperture, speechLine, f);
  };
}
