// Short portrait-stage overlays. Geometry uses a 360 × 640 design space.
const TAU = 2 * Math.PI;
const cream = '#ffedc4', amber = '#ffc379', peach = '#fa9289', mint = '#88ddce';
const palette = [cream, amber, peach, mint, '#e9a4c5'];
const durations = {
  heart: 1900, rose: 2500, beer: 2100, lollipop: 2100, duck: 2400,
  glowstick: 2400, cannon: 2200, fireworks: 3100, car: 2600,
  generic: 2100,
};
const clamp = value => Math.min(1, Math.max(0, value));
const ease = value => 1 - Math.pow(1 - clamp(value), 3);

function oval(ctx, x, y, rx, ry, color, angle = 0) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, angle, 0, TAU);
  ctx.fill();
}

function line(ctx, points, color, width) {
  ctx.beginPath();
  ctx.moveTo(...points[0]);
  for (let n = 1; n < points.length; n++) ctx.lineTo(...points[n]);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
}

function star(ctx, x, y, r, color) {
  ctx.beginPath();
  for (let i = 0; i < 8; i++) {
    const angle = i * Math.PI / 4;
    const size = i % 2 ? r * .24 : r;
    const px = x + Math.cos(angle) * size, py = y + Math.sin(angle) * size;
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

function heart(ctx, x, y, size, color) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(size, size);
  ctx.beginPath();
  ctx.moveTo(0, 1);
  ctx.bezierCurveTo(-1.9, -.1, -.94, -1.55, 0, -.65);
  ctx.bezierCurveTo(.94, -1.55, 1.9, -.1, 0, 1);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.restore();
}

// Particles live in the side lanes to leave the host's eyes and subtitles clear.
function sideParticles(ctx, t, seeds, kind) {
  seeds.slice(0, kind === 'rose' ? 22 : 15).forEach(({a, b, c, d}, i) => {
    const u = (t - a * .38) / .64;
    if (u < 0 || u >= 1) return;
    const left = i % 2 === 0;
    const x = (left ? 20 + b * 83 : 340 - b * 83) + Math.sin(u * 4 + c * 5) * 13;
    const y = kind === 'rose' ? 178 + c * 80 + u * 190 : 458 - u * (72 + c * 140);
    ctx.save();
    ctx.globalAlpha *= Math.min(1, u * 10 + .1, (1 - u) * 5);
    if (kind === 'rose') {
      ctx.translate(x, y);
      ctx.rotate(d * TAU + u * 4.5);
      ctx.scale((5 + c * 5) * (.5 + .5 * Math.abs(Math.cos(u * 4 + b))), 6 + b * 6);
      ctx.beginPath();
      ctx.moveTo(0, 1);
      ctx.bezierCurveTo(-1.2, .55, -1.3, -.72, -.5, -.83);
      ctx.bezierCurveTo(.65, -1.4, 1.25, -.25, 0, 1);
      ctx.fillStyle = ['#e77386', '#ffacb1', '#bd516d'][i % 3];
      ctx.fill();
    } else if (kind === 'heart') {
      heart(ctx, x, y, 4 + d * 8, i % 3 === 0 ? cream : peach);
    } else if (kind === 'beer') {
      const radius = 2 + d * 4;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, TAU);
      ctx.strokeStyle = amber;
      ctx.lineWidth = 1.15;
      ctx.stroke();
      oval(ctx, x - radius * .3, y - radius * .4, 1, 1, cream);
    } else {
      star(ctx, x, y, 2 + d * 5, palette[i % palette.length]);
    }
    ctx.restore();
  });
}

function beer(ctx, t) {
  ctx.save();
  ctx.translate(58, 431 - 13 * Math.sin(t * Math.PI));
  ctx.rotate(-.19 + .13 * Math.sin(t * TAU));
  ctx.strokeStyle = cream;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.roundRect(7, -12, 15, 18, 6);
  ctx.stroke();
  ctx.fillStyle = '#d99142';
  ctx.beginPath();
  ctx.roundRect(-15, -18, 28, 38, [3, 3, 6, 6]);
  ctx.fill();
  for (const x of [-8, -1, 6]) line(ctx, [[x, -7], [x, 13]], '#ffe0a0', 2);
  for (let n = 0; n < 4; n++) oval(ctx, -12 + n * 7, -16 - n % 2 * 3, 6, 5, cream);
  ctx.restore();
}

function lollipop(ctx, t) {
  ctx.save();
  ctx.translate(297, 408 + 5 * Math.sin(t * TAU));
  ctx.rotate(.18 + .12 * Math.sin(t * TAU));
  line(ctx, [[0, 5], [0, 39]], cream, 4);
  oval(ctx, 0, 0, 18, 18, '#ffcab5');
  ctx.beginPath();
  for (let i = 0; i <= 70; i++) {
    const a = i * .16, r = 1 + i * .22;
    const x = Math.cos(a + t * 5) * r, y = Math.sin(a + t * 5) * r;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = '#d65c77';
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.restore();
}

function duck(ctx, t) {
  const slide = ease(t * 4) * (1 - ease((t - .74) * 4));
  ctx.save();
  ctx.translate(-24 + slide * 93, 443 - 7 * Math.abs(Math.sin(t * Math.PI * 3)));
  ctx.rotate(.07 * Math.sin(t * TAU * 2));
  oval(ctx, -1, 3, 25, 17, '#f7bd55', -.12);
  oval(ctx, 14, -14, 13, 14, '#ffda75');
  oval(ctx, 28, -12, 8, 4, '#e98349');
  oval(ctx, 19, -17, 2.4, 2.4, '#2b2624');
  oval(ctx, 19.6, -17.5, .75, .75, cream);
  oval(ctx, -5, 3, 15, 7, '#ffdc81', -.22 + .2 * Math.sin(t * TAU * 3));
  line(ctx, [[-14, 7], [-6, 9], [1, 7]], '#d29647', 1.1);
  for (let i = 0; i < 2; i++) {
    ctx.beginPath();
    ctx.ellipse(0, 19 + i * 3, 27 + i * 6, 3 + i * 1.5, 0, .1, 3);
    ctx.strokeStyle = i ? '#a4e5da85' : '#d1f5e9';
    ctx.lineWidth = 1.4;
    ctx.stroke();
  }
  ctx.restore();
}

function glowsticks(ctx, t) {
  for (const side of [-1, 1]) {
    ctx.save();
    ctx.translate(side === -1 ? 60 : 298, 440);
    ctx.rotate(side * (.48 + .25 * Math.sin(t * TAU * 2)));
    const color = side === -1 ? mint : peach;
    ctx.shadowBlur = 10;
    ctx.shadowColor = color;
    line(ctx, [[0, 0], [0, -38]], color, 8);
    ctx.shadowBlur = 0;
    line(ctx, [[-1, -4], [-1, -36]], cream, 2);
    line(ctx, [[0, 2], [0, 14]], '#c69a80', 6);
    ctx.restore();
  }
}

function confetti(ctx, t, seeds) {
  seeds.forEach(({a, b, c, d}, i) => {
    const u = (t - .12 * a) / .92;
    if (u < 0 || u > 1) return;
    const x = (i % 2 ? 331 : 29) + (i % 2 ? -1 : 1) * (24 + b * 86) * u;
    const y = 468 - (220 + 100 * a) * u + (212 + 100 * c) * u * u;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(d * TAU + u * (4 + a * 4));
    ctx.fillStyle = palette[i % palette.length];
    ctx.fillRect(-1.7, -3.3, 3.4 * (.4 + Math.abs(Math.sin(u * 8))), 6.6);
    ctx.restore();
  });
  for (const side of [-1, 1]) {
    ctx.save();
    ctx.translate(side === -1 ? 31 : 329, 466);
    ctx.rotate(side * -.55);
    ctx.fillStyle = peach;
    ctx.beginPath();
    ctx.moveTo(-6, -8); ctx.lineTo(6, -8); ctx.lineTo(2, 15); ctx.closePath(); ctx.fill();
    line(ctx, [[-5, -3], [4, 0]], cream, 2.4);
    ctx.restore();
  }
}

function fireworks(ctx, t, seeds) {
  const positions = [[48, 206, .03], [303, 266, .22], [67, 325, .44], [308, 183, .57]];
  for (const [x, y, delay] of positions) {
    const u = (t - delay) / .38;
    if (u <= 0 || u >= 1) continue;
    ctx.save();
    ctx.globalAlpha *= 1 - u;
    line(ctx, [[x, y + 65 * (1 - clamp(u * 6))], [x, y]], cream, (1 - u) * 1.1);
    seeds.slice(0, 18).forEach(({a, b}, i) => {
      const angle = TAU * (i + a * .38) / 18;
      const len = (27 + b * 24) * ease(u);
      const dx = Math.cos(angle), dy = Math.sin(angle);
      line(ctx, [[x + dx * len * .76, y + dy * len * .76 + 9 * u * u],
                 [x + dx * len, y + dy * len + 12 * u * u]],
           palette[i % 4], 1.4);
    });
    ctx.restore();
  }
}

function car(ctx, t) {
  const x = -57 + ease(t / .34) * 141 + 335 * Math.pow(clamp((t - .62) / .38), 2);
  ctx.save();
  ctx.translate(x, 466);
  for (const y of [-6, -2]) {
    const light = ctx.createLinearGradient(30, 0, 138, 0);
    light.addColorStop(0, '#ffe6a7ba');
    light.addColorStop(1, '#ffeac200');
    ctx.fillStyle = light;
    ctx.beginPath();
    ctx.moveTo(30, y); ctx.lineTo(139, y - 15); ctx.lineTo(139, y + 2); ctx.closePath(); ctx.fill();
  }
  ctx.beginPath();
  ctx.moveTo(-41, 2); ctx.quadraticCurveTo(-41, -6, -29, -8);
  ctx.lineTo(-17, -18); ctx.quadraticCurveTo(-3, -24, 12, -16);
  ctx.lineTo(21, -11); ctx.quadraticCurveTo(43, -10, 43, 0);
  ctx.lineTo(38, 6); ctx.lineTo(-35, 6); ctx.closePath();
  ctx.fillStyle = '#dc7d63'; ctx.fill();
  ctx.fillStyle = '#284247';
  ctx.beginPath();
  ctx.moveTo(-23, -9); ctx.lineTo(-14, -16); ctx.quadraticCurveTo(-3, -20, 9, -15);
  ctx.lineTo(17, -10); ctx.closePath(); ctx.fill();
  line(ctx, [[-32, -2], [32, -3]], '#ffd6ac', 1);
  for (const px of [-25, 25]) {
    oval(ctx, px, 5, 7, 7, '#272c32');
    oval(ctx, px, 5, 3.5, 3.5, '#f0cba7');
  }
  oval(ctx, 36, -6, 5, 2, cream);
  ctx.restore();
}

function present(ctx, t, seeds) {
  sideParticles(ctx, t, seeds, 'star');
  ctx.save();
  ctx.translate(297, 436 - Math.sin(t * Math.PI) * 9);
  ctx.fillStyle = '#bb6d62'; ctx.fillRect(-16, -10, 32, 24);
  ctx.fillStyle = amber; ctx.fillRect(-3, -10, 6, 24);
  ctx.translate(0, -11 * Math.sin(t * Math.PI));
  ctx.rotate(-.08 * Math.sin(t * TAU));
  ctx.fillStyle = peach; ctx.fillRect(-18, -15, 36, 7);
  ctx.fillStyle = cream; ctx.fillRect(-3, -15, 6, 7);
  for (const dir of [-1, 1]) {
    ctx.beginPath();
    ctx.moveTo(0, -15);
    ctx.bezierCurveTo(dir * 22, -20, dir * 11, -34, 0, -15);
    ctx.strokeStyle = amber; ctx.lineWidth = 2.6; ctx.stroke();
  }
  ctx.restore();
}

const drawings = {
  heart: (ctx, t, seeds) => sideParticles(ctx, t, seeds, 'heart'),
  rose: (ctx, t, seeds) => sideParticles(ctx, t, seeds, 'rose'),
  beer: (ctx, t, seeds) => { sideParticles(ctx, t, seeds, 'beer'); beer(ctx, t); },
  lollipop: (ctx, t, seeds) => { sideParticles(ctx, t, seeds, 'star'); lollipop(ctx, t); },
  duck, glowstick: glowsticks, cannon: confetti, fireworks, car,
  generic: present,
};

export function makeGiftEffects(canvas) {
  const ctx = canvas.getContext('2d');
  let frame = 0;

  function clear() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function show(effectId) {
    clear();
    if (!ctx) return;
    const id = Object.hasOwn(drawings, effectId) ? effectId : 'generic';
    const seeds = Array.from({length: 40}, () => ({
      a: Math.random(), b: Math.random(), c: Math.random(), d: Math.random(),
    }));
    const start = performance.now();
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.min(globalThis.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(bounds.width * ratio));
    canvas.height = Math.max(1, Math.round(bounds.height * ratio));
    function paint(now) {
      const t = clamp((now - start) / durations[id]);
      if (t >= 1) { clear(); return; }
      ctx.setTransform(canvas.width / 360, 0, 0, canvas.height / 640, 0, 0);
      ctx.clearRect(0, 0, 360, 640);
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.globalAlpha = Math.min(1, .2 + t * 9, (1 - t) * 7);
      drawings[id](ctx, t, seeds);
      ctx.restore();
      frame = requestAnimationFrame(paint);
    }
    paint(start);
  }

  return {show, clear};
}
