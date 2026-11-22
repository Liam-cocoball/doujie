import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {makeStudio} from './stage-studio.js';
import {makeGiftProps} from './stage-props.js';
import {rigFace} from './stage-face.js';
import {planPerformance} from './stage-performance.js';

const SHOTS = {
  medium: [.045,1.55,5.16, .005,1.40,0,36], close: [-.01,1.59,4.89, 0,1.44,0,36],
  wide: [.105,1.49,5.43, .01,1.35,0,36],
};
const {clamp, lerp} = T.MathUtils;
const handGifts = new Set(['rose', 'beer', 'glowstick', 'lollipop']);
const wideGifts = new Set(['duck', 'car', 'fireworks', 'cannon']);

// These values are in the original model's shoulder and neck coordinate systems.
// Arm entries are pitch, outward rotation and wrist roll for the lead and support hands.
const stances = {
  idle:    {lead:[-.04,.02,0],     off:[-.04,.02,0],   neck:[0,0,0],       turn:0,    lean:0},
  talk:    {lead:[-1.07,.17,.18],  off:[-.47,.15,-.1], neck:[.04,.06,.04], turn:.08,  lean:.02},
  present: {lead:[-1.45,.41,.49],  off:[-.35,.10,-.1], neck:[.02,-.1,.1],  turn:-.13, lean:.03},
  point:   {lead:[-1.68,-.39,-.20],off:[-.61,.25,.19], neck:[.09,-.09,.06],turn:-.15, lean:.068},
  shrug:   {lead:[-.84,1.21,.47],  off:[-.93,1.06,.4], neck:[-.06,.06,.12],turn:.04,  lean:-.01},
  lean:    {lead:[-1.13,-.12,.25], off:[-.67,.17,-.1], neck:[.13,.16,.075],turn:.13,  lean:.095},
  look:    {lead:[-.60,.19,.12],   off:[-.28,.06,0],   neck:[.045,.23,.06],turn:.11,  lean:.015},
  nod:     {lead:[-.89,.24,.15],   off:[-.48,.09,0],   neck:[.08,.06,.02], turn:.055, lean:.035},
  wave:    {lead:[-.52,1.86,.15],  off:[-.38,.13,.1],  neck:[-.04,.03,-.1],turn:-.07, lean:.005},
  heart:   {lead:[-1.28,-.95,.20], off:[-1.28,-.95,.2],neck:[.045,0,.09],  turn:0,    lean:.035},
  hold:    {lead:[-.94,-.66,.11],  off:[-1.05,-.64,.1],neck:[.07,.03,.04], turn:.035, lean:.02},
  hop:     {lead:[-.59,.81,.19],   off:[-.74,.75,.17], neck:[-.045,0,.04], turn:.06,  lean:.005},
  chin:    {lead:[-2.31,-.65,-.32],off:[-.74,-.52,.21],neck:[.10,-.15,.10],turn:-.10, lean:.055},
  cut:     {lead:[-1.45,-.58,-.35],off:[-.38,.19,.08],neck:[.09,-.1,-.035],turn:-.13,lean:.045},
  fold:    {lead:[-1.36,-1.18,.34],off:[-1.05,-1.08,.24],neck:[-.07,.05,.065],turn:.11,lean:-.025},
  sweep:   {lead:[-1.27,.48,.32],  off:[-.47,-.19,.1], neck:[-.04,.13,.11],turn:.16,  lean:.02},
  recoil:  {lead:[-1.51,.53,-.18], off:[-1.37,.41,.08],neck:[-.14,-.08,.06],turn:-.07,lean:-.064},
};

function joint(parent, name, position, nodes) {
  const group = new T.Group();
  group.name = name;
  group.position.set(...position);
  parent.add(group);
  group.updateWorldMatrix(true, false);
  for (const node of nodes) group.attach(node);
  return group;
}

function rotate(node, x, y, z, f) {
  const r = node.rotation;
  r.set(lerp(r.x,x,f),lerp(r.y,y,f),lerp(r.z,z,f));
}

export async function startAvatar(canvas, level, onReady, onLost) {
  const renderer = new T.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.65));
  renderer.toneMapping = T.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.03;
  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(36,9/16,.05,25);
  const [asset, inventory] = await Promise.all([
    new GLTFLoader().loadAsync(new URL('./assets/girl.glb',import.meta.url).href),
    new T.FileLoader().setResponseType('json').loadAsync(new URL('./assets/studio-inventory.json',import.meta.url).href),
  ]);
  const {displaySides, deskTop, giftWallTexture} = makeStudio(scene, inventory);
  const root = asset.scene;
  scene.add(root);
  root.updateWorldMatrix(true, true);
  const girl = root.getObjectByName('Girl');
  const head = girl.getObjectByName('HeadRig');
  const torso = joint(girl, 'Waist pivot', [0,.43,0], girl.children.filter(node => !node.name.startsWith('Leg_')));
  const arms = [girl.getObjectByName('Arm_L'), girl.getObjectByName('Arm_R')];
  const legs = [girl.getObjectByName('Leg_L'), girl.getObjectByName('Leg_R')];
  const giftProps = makeGiftProps(scene, arms[0], deskTop);
  const wrists = arms.map((arm, index) => joint(arm, 'Wrist pivot', [index ? -.163 : .163,-.273,.020],
    arm.children.filter(node => /^(Peach_hand|Rounded_thumb|Finger_tip|Gift grip)/.test(node.name))));
  const drawFace = rigFace(head);
  const [cx,cy,cz,tx,ty,tz] = SHOTS.medium;
  const target = new T.Vector3(tx,ty,tz), destination = new T.Vector3(), faceCentre = new T.Vector3();
  camera.position.set(cx,cy,cz);

  let beats = planPerformance({}), beatIndex = 0, shot = 'medium', giftId = null, focusSide = 0;
  let hasLine = false, voiced = false, duration = 1, progress = 0, since = performance.now();
  let endTime = null, previous = since, mouth = 0, slowLevel = 0, accent = 0, nextAccent = 0;
  let frame = 0, width = 0, height = 0, ready = false, visible = true;
  const motion = matchMedia('(prefers-reduced-motion: reduce)').matches ? .55 : 1;

  function setDuration(seconds) {
    if (Number.isFinite(seconds) && seconds > 0) duration = seconds;
  }
  function setPose(part = {}) {
    beats = planPerformance(part);
    beatIndex = 0;
    hasLine = Boolean(part.text);
    voiced = hasLine && part.voiced !== false;
    duration = Math.max(1.2, Array.from(part.text || '').length * .165 + .45);
    setDuration(part.duration);
    const elapsed = hasLine && Number.isFinite(part.elapsed) ? Math.max(0, part.elapsed) : 0;
    since = performance.now() - elapsed * 1000;
    progress = 0;
    endTime = null;
    giftId = part.source === 'gift' ? part.giftId : null;
    focusSide = displaySides.get(part.focusItem) || 0;
    if (giftId) giftProps.show(giftId);
    else giftProps.clear();
    const gesture = beats[0].gesture;
    shot = part.camera in SHOTS ? part.camera : giftId ? (wideGifts.has(giftId) ? 'wide' : 'medium')
      : ['lean','look','chin'].includes(gesture) ? 'close' : ['heart','wave','hop','shrug'].includes(gesture) ? 'wide' : 'medium';
  }
  function endSegment() {
    if (endTime === null) endTime = performance.now();
  }

  function animate(now) {
    if (!visible) return;
    const dt = clamp((now-previous)/1000,0,.09);
    previous = now;
    const s = now*.001, elapsed = Math.max(0,(now-since)*.001);
    const f = 1-Math.exp(-dt*10);
    progress = Math.max(progress, clamp(elapsed/duration,0,1));
    while (beatIndex + 1 < beats.length && progress >= beats[beatIndex].end) beatIndex++;
    const beat = beats[beatIndex], gesture = beat.gesture, mood = beat.mood;
    const showingItem = focusSide !== 0 && beatIndex === 0 && hasLine && progress < .55 && endTime === null;
    const stance = showingItem ? stances.present : stances[gesture] || stances.talk;
    const phase = clamp((progress-beat.start) / Math.max(.01,beat.end-beat.start),0,1);
    const stroke = Math.sin(Math.PI * Math.min(1,phase/.78));
    const speaking = hasLine && endTime === null;
    const input = voiced && speaking ? clamp(level() || 0,0,1) : 0;
    mouth = lerp(mouth,input,1-Math.exp(-dt * (input > mouth ? 32 : 22)));
    slowLevel = lerp(slowLevel,input,1-Math.exp(-dt*3.8));
    accent *= Math.exp(-dt * 8);
    if (mouth - slowLevel > .07 && s >= nextAccent) {
      accent = Math.min(1,(mouth-slowLevel)*3 + .25);
      nextAccent = s + .24;
    }
    const emphasis = speaking ? (.64 * stroke + .38 * accent) * beat.strength : 0;
    const settle = endTime === null ? 1 : Math.max(.34, Math.exp(-(now-endTime)*.0028));
    const reach = (hasLine ? .78 + .22*stroke : 1) * settle;
    const side = showingItem ? focusSide : handGifts.has(giftId) ? -1 : beat.side;
    const breath = Math.sin(s*1.7), sway = Math.sin(s*.81 + beat.phase);
    const nod = gesture === 'nod' ? .17 * Math.sin(phase * Math.PI*2.3) : 0;
    const inspectingDuck = giftId === 'duck' && gesture === 'look';
    const squint = mood === 'skeptical' ? -.095 : mood === 'smirk' ? .072 : 0;
    const headYaw = showingItem ? side*.30 : inspectingDuck ? -.25 : stance.neck[1]*side;
    rotate(head, (stance.neck[0] + (showingItem ? .14 : 0) + nod + .083*emphasis + (mood === 'surprised' ? -.09 : 0) + breath*.016)*motion,
      (headYaw * (.65 + reach*.35) + sway*.035)*motion,
      (stance.neck[2]*side + squint + emphasis*.048*side)*motion, f);
    const turn = stance.turn * side;
    rotate(torso, (.048*emphasis + stance.lean*.84 + breath*.009)*motion,
      (turn + .050*side*emphasis + sway*.022)*motion, (.038*side*reach + .026*side*emphasis)*motion, f);

    for (let i=0; i<2; i++) {
      const sign = i === 0 ? 1 : -1, lead = sign === side;
      const angles = lead ? stance.lead : stance.off;
      let pitch = angles[0] * reach - (lead ? .28 : .1)*emphasis;
      let spread = angles[1] * reach, wrist = angles[2] * reach, yaw = 0;
      if (lead) {
        if (gesture === 'wave') { spread += .18*Math.sin(elapsed*8); wrist += .29*Math.sin(elapsed*9+.4); }
        if (gesture === 'sweep' || gesture === 'cut') { spread += (gesture === 'cut' ? -.55 : .72)*stroke; yaw = .23*stroke; }
        if (gesture === 'talk' || gesture === 'present') { spread += .24*emphasis; wrist += .32*emphasis; }
      }
      // Rest a lowered hand near the waist.
      if (speaking) {
        const lowered = clamp((pitch + .98)/.70, 0, 1);
        const tuck = lowered * (1 - clamp(Math.abs(spread)/.85, 0, 1));
        spread -= 1.08*tuck;
        pitch -= .30*tuck;
      }
      if (i === 0 && handGifts.has(giftId)) {
        pitch = -1.13 - .15*emphasis;
        spread = (giftId === 'glowstick' ? .16 + .18*Math.sin(elapsed*6) : -.03);
        wrist = .08;
      }
      rotate(arms[i], (pitch + breath*.025)*motion, yaw*sign*motion, spread*sign*motion, f);
      rotate(wrists[i], (.14*emphasis + .05*breath)*motion, wrist * sign * .7 * motion, wrist*sign*motion, f);
      rotate(legs[i], -.016*breath*motion, .018*sway*motion, sign*(.014 + .018*emphasis)*motion, f);
    }
    const hop = gesture === 'hop' ? .10*Math.sin(Math.PI*phase)**2 : 0;
    root.position.y = lerp(root.position.y, (hop + .008*breath)*motion, f);
    root.position.z = lerp(root.position.z, stance.lean*reach*motion, f);
    const gaze = showingItem ? .032*side : inspectingDuck ? -.028 : .015*Math.sin(beat.phase + .57*s) + .008*side*emphasis;
    drawFace(s,dt,mood,mouth,gaze,showingItem ? -.9 : gesture === 'chin' ? .8 : .35*sway,emphasis,speaking,motion);
    giftProps.update(dt);

    const [cx,cy,cz,tx,ty,tz,fov] = SHOTS[shot];
    const pan = 1-Math.exp(-dt*2.9);
    // Let the shot breathe with the host while keeping both ends of the desk in frame.
    head.localToWorld(faceCentre.set(0,.41,.11));
    const tracking = clamp(faceCentre.x, -.035, .035);
    camera.position.lerp(destination.set(cx + tracking*.28,cy,cz),pan);
    target.lerp(destination.set(tx + tracking*.40,ty,tz),pan);
    camera.lookAt(target);
    const w = Math.max(1,canvas.clientWidth), h = Math.max(1,canvas.clientHeight);
    if (w !== width || h !== height) {
      width=w; height=h; camera.aspect=w/h; renderer.setSize(w,h,false); camera.updateProjectionMatrix();
    }
    if (Math.abs(camera.fov-fov)>.002) { camera.fov = lerp(camera.fov,fov,pan); camera.updateProjectionMatrix(); }
    try { renderer.render(scene,camera); } catch { visible=false; onLost(); return; }
    if (!ready) { ready=true; onReady(); }
    frame = requestAnimationFrame(animate);
  }
  canvas.addEventListener('webglcontextlost',e => { e.preventDefault(); visible=false; cancelAnimationFrame(frame); onLost(); });
  frame = requestAnimationFrame(animate);
  window.addEventListener('pagehide',()=>{ visible=false; cancelAnimationFrame(frame); renderer.dispose(); },{once:true});
  return {setPose, setDuration, endSegment, refreshGiftWall() { giftWallTexture.needsUpdate = true; }};
}
