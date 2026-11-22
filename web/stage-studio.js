import * as T from 'three';
import {makePhone} from './stage-phone.js';

function paint(width, height, draw) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext('2d'), width, height);
  const texture = new T.CanvasTexture(canvas);
  texture.colorSpace = T.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function skyline(ctx, w, h) {
  let seed = 1298;
  const rand = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const sky = ctx.createLinearGradient(0, 0, 0, h);
  sky.addColorStop(0, '#142f40'); sky.addColorStop(.55, '#48787d');
  sky.addColorStop(.78, '#d09784'); sky.addColorStop(1, '#2f4e53');
  ctx.fillStyle = sky; ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 80; i++) {
    ctx.fillStyle = 'rgba(237,247,229,' + (.13 + rand() * .50) + ')';
    ctx.fillRect(rand() * w, rand() * h * .43, 1.4, 1.4);
  }
  const moonX = w * .70, moonY = h * .23;
  const halo = ctx.createRadialGradient(moonX, moonY, 3, moonX, moonY, 81);
  halo.addColorStop(0, '#ead6a484'); halo.addColorStop(1, '#ecdcc000');
  ctx.fillStyle = halo; ctx.fillRect(moonX - 82, moonY - 82, 164, 164);
  ctx.fillStyle = '#ffead0'; ctx.beginPath(); ctx.arc(moonX, moonY, 15, 0, Math.PI * 2); ctx.fill();
  for (let depth = 0; depth < 3; depth++) {
    let x = -20;
    while (x < w) {
      const width = 13 + rand() * (27 + depth * 12);
      const top = h * (.58 + depth * .064) - rand() * (h * .19 + depth * 12);
      ctx.fillStyle = ['#557174', '#375a60', '#21454d'][depth];
      ctx.fillRect(x, top, width, h - top);
      if (rand() > .52) ctx.fillRect(x + width * .34, top - 3 - rand() * 10, width * .3, 15);
      if (rand() > .80) {ctx.fillRect(x + width * .66, top - 22, 1.5, 23);ctx.fillStyle = '#eeac80';ctx.fillRect(x + width * .66, top - 24, 2, 2);}
      for (let y = top + 9; y < h * .89; y += 6 + depth * 1.5) {
        for (let xx = x + 3; xx < x + width - 2; xx += 5 + depth) {
          if (rand() > .65) {ctx.fillStyle = rand() > .30 ? ['#a9a68c', '#c6b59c', '#e2b38e'][depth] : '#83acaa';ctx.fillRect(xx, y, 1.5 + depth * .35, 1.8);}
        }
      }
      x += width + rand() * 5;
    }
  }
}

function monitorFace(ctx, w, h) {
  ctx.fillStyle = '#102c2e'; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = '#335657'; ctx.lineWidth = 1;
  for (let y = 14; y < h; y += 12) { ctx.beginPath();ctx.moveTo(0, y);ctx.lineTo(w, y);ctx.stroke(); }
  for (let x = 0; x < w; x += 15) {ctx.beginPath();ctx.moveTo(x, 0);ctx.lineTo(x, h);ctx.stroke();}
  ctx.strokeStyle = '#8ce0c8'; ctx.lineWidth = 2.8; ctx.beginPath();
  for (let x = 0; x < w; x++) {
    const y = h * .5 + Math.sin(x * .29) * Math.sin(x * .08) ** 2 * h * .32;
    if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

export function makeStudio(scene, inventory) {
  scene.background = new T.Color(0x1c3439);
  const matte = (color, metalness = 0, roughness = .72) => new T.MeshStandardMaterial({color, metalness, roughness});
  const ink = matte(0x203333), frame = matte(0x304449, .3), wood = matte(0xad6c4b);
  const brass = matte(0xd2a06a, .64, .38), copper = matte(0xbd735b, .44);
  const unit = new T.BoxGeometry(1, 1, 1);
  const circle = new T.CylinderGeometry(1, 1, 1, 24);
  function mesh(parent, geometry, material, x, y, z) {
    const obj = new T.Mesh(geometry, material);
    obj.position.set(x, y, z); parent.add(obj); return obj;
  }
  function box(parent, x, y, z, sx, sy, sz, material) {
    const obj = mesh(parent, unit, material, x, y, z); obj.scale.set(sx, sy, sz); return obj;
  }
  function tube(parent, from, to, radius, material) {
    const start = new T.Vector3(...from), end = new T.Vector3(...to);
    const obj = mesh(parent, circle, material, 0, 0, 0);
    obj.position.addVectors(start, end).multiplyScalar(.5);
    obj.scale.set(radius, start.distanceTo(end), radius);
    obj.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), end.sub(start).normalize());
    return obj;
  }
  function panelTexture(texture) {return new T.MeshBasicMaterial({map:texture,toneMapped:false});}

  // A backlit panorama sits behind the window, with joinery and furniture at different depths.
  const view = mesh(scene, new T.PlaneGeometry(6.3, 3.1), panelTexture(paint(1280, 690, skyline)), .06, 1.73, -1.84);
  view.renderOrder = -1;
  for (const x of [-2.48, -.83, .98, 2.56]) box(scene, x, 1.6, -1.71, .038, 3.2, .09, frame);
  for (const y of [.66, 2.66]) box(scene, 0, y, -1.69, 6, .045, .10, frame);
  box(scene, 0, .57, -1.64, 6, .095, .27, wood);
  box(scene, 0, .1, -1.76, 6.2, .85, .13, matte(0x304d51));
  const slats = matte(0x875742), slatBack = matte(0x342e2a);
  for (const sign of [-1, 1]) {
    box(scene, sign * 1.63, 1.5, -1.54, .9, 3.3, .12, slatBack);
    for (let i = 0; i < 12; i++) box(scene, sign * (1.23 + i * .072), 1.52, -1.42, .045, 3.15, .12, slats);
  }

  // A horizontal enamel lightbox hangs from the mullions behind the host.
  const wallY = 2.966;
  for (const x of [-.87, .87]) box(scene, x, wallY + .24, -1.48, .024, .23, .045, brass);
  box(scene, 0, wallY, -1.47, 2.11, .335, .095, frame);
  box(scene, 0, wallY, -1.415, 2.09, .320, .022, brass);
  const giftWallTexture = new T.CanvasTexture(document.querySelector('#gift-wall'));
  giftWallTexture.colorSpace = T.SRGBColorSpace;
  giftWallTexture.anisotropy = 4;
  mesh(scene, new T.PlaneGeometry(2.06, .306), panelTexture(giftWallTexture), 0, wallY, -1.398);

  const hemi = new T.HemisphereLight(0xffecd7, 0x5f6466, 1.75);
  scene.add(hemi);
  function light(color, power, x, y, z) {const l = new T.DirectionalLight(color, power);l.position.set(x,y,z);scene.add(l);}
  light(0xffe5cb, 2.25, -2, 4, 4); light(0xb4e4eb, 1.0, 3, 2, 2); light(0xffc7a6, 2.6, 0, 3, -3);

  // Brass reading lamp, with a warm dome and visible diffuser.
  const lamp = new T.Group(); scene.add(lamp);lamp.position.set(-.89, .43, -.86);
  tube(lamp, [0,0,0], [0,1.24,0], .015, brass);
  tube(lamp, [0,1.24,0], [.20,1.34,0], .014, brass);
  mesh(lamp,new T.ConeGeometry(.20,.15,40),copper,.20,1.28,0);
  mesh(lamp,new T.CylinderGeometry(.185,.185,.012,32),new T.MeshBasicMaterial({color:0xffddb4}),.20,1.205,0);
  const lampLight = new T.PointLight(0xffad78, .50, 2.2); lampLight.position.set(-.69,1.61,-.8);scene.add(lampLight);

  // A broadcast desk in the foreground, with a cantilevered microphone and analogue controls.
  const tabletop = paint(512,128,(ctx,w,h)=>{
    ctx.fillStyle='#96684e';ctx.fillRect(0,0,w,h);
    for(let i=0;i<75;i++){ctx.beginPath();ctx.strokeStyle=i%4?'#623d2c30':'#e2ac7940';ctx.lineWidth=i%5?.8:1.6;
      for(let x=0;x<=w;x+=8){const y=(i*17%h)+Math.sin(x*.014+i)*1.6;if(!x)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();}
  });
  const desk = box(scene,0,.413,.57,3.2,.085,.49,new T.MeshStandardMaterial({map:tabletop,roughness:.76}));
  const deskTop = desk.position.y + desk.scale.y/2;
  box(scene,0,.351,.804,3.15,.045,.038,brass);
  box(scene,0,.245,.77,3.15,.18,.07,matte(0x294240));
  const boom = new T.Group();scene.add(boom);
  tube(boom,[-.88,.44,.48],[-.75,.68,.46],.026,ink);
  tube(boom,[-.75,.68,.46],[-.42,.97,.34],.021,ink);
  tube(boom,[-.762,.72,.46],[-.43,1.008,.34],.009,brass);
  tube(boom,[-.43,.98,.34],[-.375,.98,.36],.023,brass);
  const mic = new T.Group();scene.add(mic);mic.position.set(-.37,.99,.38);mic.rotation.z=-.26;
  mesh(mic,new T.CapsuleGeometry(.061,.135,5,22),ink,0,.012,0);
  for (let j=0;j<7;j++) {
    const ring=mesh(mic,new T.TorusGeometry(.058-(Math.max(0,j-4)*.003),.0027,5,24),brass,0,.023+j*.014,0);
    ring.rotation.x=Math.PI/2;
  }
  box(mic,0,-.071,.052,.050,.018,.012,new T.MeshBasicMaterial({color:0xff865e}));

  // The waveform screen stands on the rear of the desk.
  const screen = new T.Group();screen.name = 'Waveform monitor';
  screen.position.set(.29,.85,.38);screen.rotation.set(-.12,-.21,0);
  screen.scale.setScalar(.74);scene.add(screen);
  box(screen,0,0,0,.30,.215,.033,ink);
  mesh(screen,new T.PlaneGeometry(.263,.173),panelTexture(paint(270,156,monitorFace)),0,.006,.018);
  tube(scene,[.29,deskTop,.356],[.29,.82,.355],.012,frame);
  box(scene,.29,deskTop+.007,.363,.092,.014,.065,ink);

  const mixer = new T.Group();mixer.name = 'Desk mixer';scene.add(mixer);
  mixer.rotation.x = .09;
  const baseHeight = .030, baseDepth = .132;
  mixer.position.set(0,deskTop + (baseHeight*Math.cos(.09)+baseDepth*Math.sin(.09))/2,.70);
  box(mixer,0,0,0,.337,baseHeight,baseDepth,ink);
  for (let k=0;k<7;k++) {
    const x=-.136+.037*k;
    box(mixer,x,.016,0,.006,.003,.079,frame);
    box(mixer,x,.021,-.004+.022*Math.sin(k*4),.019,.009,.020,k%3?brass:copper);
  }
  const lit = new T.MeshBasicMaterial({color:0xe88d65});
  for(let i=0;i<4;i++) box(mixer,.115+(i%2)*.023,.018,-.014+Math.floor(i/2)*.027,.012,.006,.012,lit);

  // The host's facts and the physical layout both use the audience's left and right.
  const phoneItem = inventory.items.find(item => item.id === 'phone');
  const side = phoneItem.viewerSide === 'left' ? -1 : 1;
  const displaySides = new Map([['phone', side], ['monitor', 1]]);
  const shadowTexture = paint(64,64,(ctx,w,h) => {
    const fade = ctx.createRadialGradient(w/2,h/2,0,w/2,h/2,w/2);
    fade.addColorStop(0,'rgba(36,20,14,.48)');
    fade.addColorStop(.65,'rgba(36,20,14,.24)');
    fade.addColorStop(1,'rgba(36,20,14,0)');
    ctx.fillStyle = fade; ctx.fillRect(0,0,w,h);
  });
  const shadow = new T.MeshBasicMaterial({map:shadowTexture,transparent:true,depthWrite:false,toneMapped:false});
  const phone = makePhone();
  phone.name = phoneItem.name;
  phone.position.set(side * .408, deskTop, .65);
  scene.add(phone);
  const contact = mesh(scene,new T.PlaneGeometry(.38,.22),shadow,phone.position.x,deskTop+.0004,.57);
  contact.rotation.x = -Math.PI / 2;
  return {displaySides, deskTop, giftWallTexture};
}
