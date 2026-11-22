import * as T from 'three';

const TAU = Math.PI * 2;

// One curved petal, tapered at the stem and folded slightly back at its lip.
function rosePetal() {
  const vertices = [], faces = [];
  const columns = 8, rows = 5;
  for (let j = 0; j <= rows; j++) {
    const v = j / rows;
    for (let i = 0; i <= columns; i++) {
      const u = i * 2 / columns - 1;
      const width = .005 + .040 * Math.sin(v * 2.30);
      vertices.push(u * width, .064 * v - .013 * u * u * v, .034 * v * v + .012 * u * u * v);
      if (i < columns && j < rows) {
        const a = j * (columns + 1) + i, b = a + columns + 1;
        faces.push(a, a + 1, b, a + 1, b + 1, b);
      }
    }
  }
  const geometry = new T.BufferGeometry();
  geometry.setAttribute('position', new T.Float32BufferAttribute(vertices, 3));
  geometry.setIndex(faces);
  geometry.computeVertexNormals();
  return geometry;
}

function lathe(outline) {
  return new T.LatheGeometry(outline.map(([radius, height]) => new T.Vector2(radius, height)), 32);
}

export function makeGiftProps(scene, arm, deskTop) {
  const enamel = (color, roughness = .36, metalness = .12) =>
    new T.MeshStandardMaterial({color, roughness, metalness});
  const coral = enamel(0xe76b68), cream = enamel(0xffeac7), teal = enamel(0x2d746f);
  const brass = enamel(0xce9d63, .34, .6), silver = enamel(0xbac5bf, .28, .72);
  const ink = enamel(0x233c40), leafGreen = enamel(0x548263, .67);
  const egg = new T.SphereGeometry(1, 20, 14);
  const cylinder = new T.CylinderGeometry(1, 1, 1, 28);

  function mesh(parent, geo, material, x = 0, y = 0, z = 0) {
    const obj = new T.Mesh(geo, material);
    obj.position.set(x, y, z);
    parent.add(obj);
    return obj;
  }
  function oval(parent, mat, x, y, z, rx, ry, rz) {
    const obj = mesh(parent, egg, mat, x, y, z);
    obj.scale.set(rx, ry, rz);
    return obj;
  }
  function barrel(parent, mat, x, y, z, r, height) {
    const obj = mesh(parent, cylinder, mat, x, y, z);
    obj.scale.set(r, height, r);
    return obj;
  }

  const grip = new T.Group();
  grip.name = 'Gift grip';
  grip.position.set(.19, -.336, .049);
  arm?.add(grip);
  const objects = {};
  function create(id, parent = grip) {
    const group = new T.Group();
    group.name = 'Gift: ' + id;
    group.visible = false;
    parent.add(group);
    objects[id] = group;
    return group;
  }

  const rose = create('rose');
  barrel(rose, leafGreen, 0, .070, .004, .0055, .255);
  const leafShape = new T.Shape();
  leafShape.moveTo(0, 0);
  leafShape.quadraticCurveTo(-.029, .032, 0, .077);
  leafShape.quadraticCurveTo(.030, .039, 0, 0);
  const leafGeo = new T.ShapeGeometry(leafShape);
  leafGreen.side = T.DoubleSide;
  for (const [y, angle] of [[.047, -.92], [.088, .94]]) {
    const leaf = mesh(rose, leafGeo, leafGreen, 0, y, .007);
    leaf.rotation.set(.13, .18, angle);
  }
  const petal = rosePetal();
  const petals = [0xd65360, 0xbc344b, 0x962c4c].map(color =>
    new T.MeshStandardMaterial({color, roughness: .57, side: T.DoubleSide}));
  const bloom = new T.Group();
  bloom.position.set(0, .177, .004);
  bloom.rotation.x = .46; // Face the audience enough to reveal the spiral inside the flower.
  rose.add(bloom);
  for (const [layer, count] of [7, 5, 3].entries()) {
    for (let i = 0; i < count; i++) {
      const a = TAU * i / count + layer * .85;
      const radius = .014 - .0045 * layer;
      const p = mesh(bloom, petal, petals[layer], Math.sin(a)*radius, .012*layer, Math.cos(a)*radius);
      p.rotation.set(0, a, 0);
      p.rotateZ(.07 * layer);
      p.scale.setScalar(1 - layer * .19);
    }
  }
  oval(bloom, petals[2], 0, .049, .001, .013, .026, .013);

  const beer = create('beer');
  const can = lathe([[0,-.071],[.033,-.071],[.041,-.06],[.045,-.05],[.045,.049],[.037,.062],[.037,.068],[0,.068]]);
  mesh(beer, can, teal, 0, .009, .031);
  for (const y of [-.061,.078]) barrel(beer, silver, 0, y, .031, .038, .0045);
  for (const y of [-.029,.045]) barrel(beer, brass, 0, y, .031, .0455, .004);
  const badge = oval(beer, cream, 0, .008, .074, .025, .030, .003);
  badge.rotation.z = -.22;
  for (let i = 0; i < 3; i++) {
    const grain = oval(beer, brass, -.010+i*.009, .002+i*.005, .0775, .004, .010, .001);
    grain.rotation.z = -.5;
  }
  const tab = mesh(beer, new T.TorusGeometry(.0095, .0025, 6, 18), ink, 0, .084, .027);
  tab.scale.x = .65; tab.rotation.x = -Math.PI/2;

  const sweet = create('lollipop');
  barrel(sweet, cream, 0, .043, .009, .006, .174);
  const sweetR = .069, sweetZ = .023, sweetY = .162;
  oval(sweet, coral, 0, sweetY, .009, sweetR, sweetR, sweetZ);
  const swirl = [];
  for (let i = 0; i <= 72; i++) {
    const t = i / 72, angle = t*TAU*2.3, r = sweetR*(.04+.87*t);
    const z = .009 + sweetZ * Math.sqrt(1 - (r/sweetR)**2);
    swirl.push(new T.Vector3(Math.cos(angle)*r, sweetY+Math.sin(angle)*r, z));
  }
  mesh(sweet, new T.TubeGeometry(new T.CatmullRomCurve3(swirl), 80, .005, 7, false), cream);

  const stick = create('glowstick');
  barrel(stick, teal, 0, -.012, .007, .018, .101);
  for (const y of [-.047,.027]) barrel(stick, brass, 0, y, .007, .020, .009);
  const luminous = new T.MeshStandardMaterial({color:0xabf6dd, emissive:0x50dcb8, emissiveIntensity:.95, roughness:.31});
  mesh(stick, new T.CapsuleGeometry(.014, .169, 4, 18), luminous, 0, .127, .007);
  oval(stick, cream, 0, -.003, .024, .006, .007, .002);

  // Land behind the mixer; the horizontal half of the phone needs the space on its left.
  const duckRig = create('duck', scene);
  duckRig.position.set(-.065, deskTop, .510);
  const shadow = mesh(duckRig, new T.CircleGeometry(1, 24),
    new T.MeshBasicMaterial({color:0x473728, transparent:true, opacity:.20, depthWrite:false}), 0, .001, 0);
  shadow.rotation.x = -Math.PI/2;
  const duck = new T.Group();
  duckRig.add(duck);
  const honey = enamel(0xedb84f, .28), wing = enamel(0xf5cb70, .30), bill = enamel(0xcf6b42, .35);
  oval(duck, honey, 0, .063, -.008, .071, .054, .092);
  oval(duck, honey, 0, .128, .030, .055, .055, .055);
  const tail = oval(duck, wing, 0, .076, -.092, .029, .027, .048);
  tail.rotation.x = .37;
  for (const side of [-1, 1]) {
    const fin = oval(duck, wing, side*.061, .068, -.022, .017, .032, .056);
    fin.rotation.x = -.25;
    oval(duck, ink, side*.036, .139, .067, .008, .009, .006);
    oval(duck, cream, side*.034, .142, .071, .0024, .0028, .002);
    oval(duck, bill, side*.031, .012, .018, .025, .009, .034);
  }
  oval(duck, bill, 0, .117, .082, .032, .010, .028);
  oval(duck, bill, 0, .124, .083, .032, .009, .031);

  let active = null, elapsed = 0;
  const inverseGrip = new T.Quaternion(), worldTilt = new T.Quaternion(), rotation = new T.Euler();
  function clear() {
    if (active) objects[active].visible = false;
    active = null;
    elapsed = 0;
  }
  function update(seconds) {
    if (!active) return;
    elapsed += Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
    if (active === 'duck') {
      const progress = Math.min(elapsed / .72, 1);
      const hop = .135*Math.sin(Math.PI*progress);
      const approach = (1-progress)**2;
      duck.position.set(-.026*approach, hop, -.032*approach);
      duck.rotation.set(.09*Math.sin(progress*TAU), -.79+.045*Math.sin(elapsed*2.1), .065*Math.sin(elapsed*2.6));
      shadow.position.x = duck.position.x;
      shadow.position.z = duck.position.z;
      shadow.scale.set(.074-hop*.18, .052-hop*.14, 1);
      shadow.material.opacity = .20-hop*.78;
      return;
    }
    // Keep objects in the palm and readable as the arm rotates to point or wave.
    grip.getWorldQuaternion(inverseGrip).invert();
    const sway = active === 'glowstick' ? .14*Math.sin(elapsed*6) : .028*Math.sin(elapsed*2.3);
    rotation.set(.09, -.16, -.15+sway+.24*arm.rotation.z);
    worldTilt.setFromEuler(rotation);
    objects[active].quaternion.copy(inverseGrip).multiply(worldTilt);
  }
  function show(id) {
    if (id === active) return;
    clear();
    if (!Object.hasOwn(objects, id) || (id !== 'duck' && !arm)) return;
    active = id;
    objects[id].visible = true;
    update(0);
  }
  return {show, update, clear};
}
