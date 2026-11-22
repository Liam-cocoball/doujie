import * as T from 'three';

function roundedRectangle(width, height, radius) {
  const x = width / 2, y = height / 2;
  const shape = new T.Shape();
  shape.moveTo(radius - x, -y);
  shape.lineTo(x - radius, -y);
  shape.quadraticCurveTo(x, -y, x, radius - y);
  shape.lineTo(x, y - radius);
  shape.quadraticCurveTo(x, y, x - radius, y);
  shape.lineTo(radius - x, y);
  shape.quadraticCurveTo(-x, y, -x, y - radius);
  shape.lineTo(-x, radius - y);
  shape.quadraticCurveTo(-x, -y, radius - x, -y);
  return shape;
}

function shell(width, height, thickness, radius, bevel = .0018) {
  const geometry = new T.ExtrudeGeometry(roundedRectangle(width, height, radius), {
    depth: thickness - 2 * bevel, bevelSize: bevel, bevelThickness: bevel,
    bevelEnabled: true, bevelSegments: 3, curveSegments: 8,
  });
  geometry.translate(0, 0, -thickness / 2 + bevel);
  return geometry;
}

// The bite, two lower lobes and detached pointed leaf stay readable at stream size.
function appleMark() {
  const fruit = new T.Shape();
  fruit.moveTo(-.04, .26);
  fruit.bezierCurveTo(-.14, .27, -.23, .37, -.38, .28);
  fruit.bezierCurveTo(-.55, .18, -.56, -.07, -.45, -.27);
  fruit.bezierCurveTo(-.39, -.39, -.30, -.51, -.21, -.51);
  fruit.bezierCurveTo(-.14, -.52, -.08, -.46, .00, -.46);
  fruit.bezierCurveTo(.10, -.45, .14, -.53, .23, -.50);
  fruit.bezierCurveTo(.33, -.46, .42, -.31, .47, -.19);
  fruit.bezierCurveTo(.26, -.10, .24, .08, .43, .19);
  fruit.bezierCurveTo(.35, .32, .23, .36, .12, .32);
  fruit.bezierCurveTo(.06, .30, .02, .27, -.04, .26);
  const leaf = new T.Shape();
  leaf.moveTo(-.03, .34);
  leaf.bezierCurveTo(-.04, .48, .07, .60, .21, .62);
  leaf.bezierCurveTo(.22, .48, .12, .34, -.03, .34);
  return new T.ShapeGeometry([fruit, leaf], 16);
}

function faceGeometry(width, height, radius) {
  const geometry = new T.ShapeGeometry(roundedRectangle(width, height, radius));
  const points = geometry.attributes.position, uv = geometry.attributes.uv;
  for (let i = 0; i < points.count; i++)
    uv.setXY(i, points.getX(i) / width + .5, points.getY(i) / height + .5);
  return geometry;
}

// Under studio lights a broad satin reflection distinguishes the back glass from the rim.
function rearFinish() {
  const canvas = document.createElement('canvas');
  canvas.width = 128; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const satin = ctx.createLinearGradient(0, 42, 128, 6);
  for (const [position, color] of [[0, '#c5cbd2'], [.28, '#e4e6e8'], [.46, '#fafafb'],
    [.59, '#e6e7e9'], [.84, '#d2d5d9'], [1, '#e3e4e6']]) satin.addColorStop(position, color);
  ctx.fillStyle = satin; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const texture = new T.CanvasTexture(canvas);
  texture.colorSpace = T.SRGBColorSpace;
  return new T.MeshStandardMaterial({map: texture, metalness: .19, roughness: .34});
}

function innerScreen(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = 256; canvas.height = 160;
  const ctx = canvas.getContext('2d');
  const fill = ctx.createLinearGradient(0, 0, 256, 160);
  fill.addColorStop(0, '#11193a'); fill.addColorStop(.55, '#38559c'); fill.addColorStop(1, '#153b5e');
  ctx.fillStyle = fill; ctx.fillRect(0, 0, 256, 160);
  const wave = ctx.createLinearGradient(0, 120, 240, 20);
  wave.addColorStop(0, '#4978cb'); wave.addColorStop(.45, '#43c6df');
  wave.addColorStop(.76, '#a1e4db'); wave.addColorStop(1, '#d2a0d1');
  ctx.fillStyle = wave; ctx.beginPath(); ctx.moveTo(-8, 113);
  ctx.bezierCurveTo(97, -24, 138, 181, 269, 29); ctx.lineTo(269, 53);
  ctx.bezierCurveTo(143, 212, 96, 23, -8, 157); ctx.closePath(); ctx.fill();
  const texture = new T.CanvasTexture(canvas);
  texture.colorSpace = T.SRGBColorSpace;
  return new T.Mesh(faceGeometry(width, height, .012), new T.MeshBasicMaterial({map: texture, toneMapped: false}));
}

export function makePhone() {
  const phone = new T.Group(), chassis = new T.Group();
  phone.name = 'iPhone Duo';
  chassis.rotation.y = -.32;
  phone.add(chassis);
  const width = .333, height = .202, thickness = .012;
  const hingeZ = .047, hingeY = .011;
  const metal = new T.MeshStandardMaterial({color: 0xbfc3c8, metalness: .48, roughness: .27});
  const dark = new T.MeshStandardMaterial({color: 0x1f2532, metalness: .24, roughness: .30});
  const lens = new T.MeshStandardMaterial({color: 0x182b47, metalness: .22, roughness: .18});
  const mark = new T.MeshBasicMaterial({color: 0x31373f, toneMapped: false});
  const glint = new T.MeshBasicMaterial({color: 0x91c9eb});
  function add(parent, geometry, material, x, y, z) {
    const mesh = new T.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    parent.add(mesh);
    return mesh;
  }

  // The host looks at the inside of the fold, the audience at its silver back.
  const base = new T.Group();
  base.name = 'Flat lower half';
  base.position.set(0, thickness / 2, hingeZ - height / 2);
  base.rotation.x = -Math.PI / 2;
  chassis.add(base);
  add(base, shell(width, height, thickness, .018), metal, 0, 0, 0);
  add(base, new T.ShapeGeometry(roundedRectangle(width - .004, height - .004, .015)),
    dark, 0, 0, thickness / 2 + .0001);
  const display = innerScreen(width - .014, height - .014);
  display.position.z = thickness / 2 + .0003;
  base.add(display);

  const lid = new T.Group();
  lid.name = 'Open upper half';
  lid.position.set(0, hingeY, hingeZ);
  lid.rotation.x = .24;
  chassis.add(lid);
  const centerY = height / 2 + .003;
  add(lid, shell(width, height, thickness, .018), metal, 0, centerY, 0);
  const rearZ = thickness / 2 + .0003;
  add(lid, faceGeometry(width - .004, height - .004, .015), rearFinish(), 0, centerY, rearZ);
  const upperScreen = display.clone();
  upperScreen.position.set(0, centerY, -rearZ);
  upperScreen.rotation.y = Math.PI;
  lid.add(upperScreen);

  const logo = add(lid, appleMark(), mark, .009, centerY - .002, rearZ + .0004);
  logo.name = 'Apple rear emblem';
  logo.scale.setScalar(.078);

  const cameraX = -.101, cameraY = height - .034;
  const island = add(lid, shell(.101, .049, .007, .022, .0011), metal,
    cameraX, cameraY, rearZ + .0035);
  island.name = 'Dual rear cameras';
  for (const offset of [-.022, .022]) {
    const x = cameraX + offset;
    const rim = add(lid, new T.CylinderGeometry(.020, .020, .006, 28), dark, x, cameraY, rearZ + .010);
    rim.rotation.x = Math.PI / 2;
    add(lid, new T.CircleGeometry(.0153, 28), lens, x, cameraY, rearZ + .0132);
    add(lid, new T.CircleGeometry(.0074, 20), dark, x, cameraY, rearZ + .0133);
    add(lid, new T.CircleGeometry(.0035, 16), glint, x - .0047, cameraY + .004, rearZ + .0135);
  }

  // The transverse hinge runs along the desk, with visible dark joins between knuckles.
  const axle = add(chassis, new T.CylinderGeometry(.0075, .0075, width - .025, 20),
    dark, 0, hingeY, hingeZ);
  axle.rotation.z = Math.PI / 2;
  for (const [x, length] of [[-.099, .099], [0, .091], [.099, .099]]) {
    const knuckle = add(chassis, new T.CylinderGeometry(.0086, .0086, length, 20),
      metal, x, hingeY, hingeZ + .0005);
    knuckle.rotation.z = Math.PI / 2;
  }
  return phone;
}
