// One face for the studio lightbox and the static stage used when WebGL is unavailable.
export function makeGiftWall(canvas) {
  const ctx = canvas.getContext('2d');
  const font = '"Microsoft YaHei", "PingFang SC", system-ui, sans-serif';
  const boundary = 280;
  let previous;

  function lettering(text, x, y, width, size, weight, color) {
    ctx.font = weight + ' ' + size + 'px ' + font;
    ctx.fillStyle = color;
    const chars = Array.from(text);
    if (ctx.measureText(text).width > width) {
      while (chars.length && ctx.measureText(chars.join('') + '…').width > width) chars.pop();
      text = chars.join('') + '…';
    }
    ctx.fillText(text, x, y);
  }

  function draw(entries) {
    const {width, height} = canvas;
    const face = ctx.createLinearGradient(0, 0, width, height);
    face.addColorStop(0, '#3c5350');
    face.addColorStop(.24, '#25433f');
    face.addColorStop(1, '#152e30');
    ctx.fillStyle = face;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = '#b49568';
    ctx.lineWidth = 3;
    ctx.strokeRect(4, 4, width - 8, height - 8);
    ctx.fillStyle = '#a7946a';
    ctx.fillRect(boundary, 34, 2, height - 68);

    // A folded brass ribbon picks up the frame and the microphone hardware.
    ctx.strokeStyle = '#ffd491';
    ctx.lineWidth = 6;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(105, 59); ctx.lineTo(171, 59); ctx.lineTo(171, 72); ctx.lineTo(105, 72); ctx.closePath();
    ctx.moveTo(111, 74); ctx.lineTo(111, 99); ctx.lineTo(165, 99); ctx.lineTo(165, 74);
    ctx.moveTo(138, 99); ctx.lineTo(138, 58);
    ctx.bezierCurveTo(111, 58, 109, 28, 124, 35);
    ctx.bezierCurveTo(133, 39, 137, 51, 138, 58);
    ctx.bezierCurveTo(150, 23, 172, 33, 158, 49); ctx.lineTo(138, 58);
    ctx.stroke();
    lettering('礼物墙', 47, 166, 200, 60, 750, '#ffe1a9');

    if (!entries.length) {
      lettering('等待本场第一份礼物', boundary + 44, 128, width - boundary - 80, 53, 550, '#deccad');
      return;
    }
    const slotWidth = (width - boundary - 20) / entries.length;
    entries.forEach(({nickname, giftName, count}, i) => {
      const slot = boundary + 12 + i * slotWidth;
      if (i) {
        ctx.fillStyle = '#547068';
        ctx.fillRect(slot, 40, 2, height - 80);
      }
      const x = slot + 30, available = slotWidth - 52;
      lettering(nickname, x, 95, available, 60, 700, '#fff3d9');
      const quantity = '×' + count;
      ctx.font = '650 48px ' + font;
      const qtyWidth = ctx.measureText(quantity).width;
      const nameWidth = Math.max(0, available - qtyWidth - 12);
      lettering(giftName, x, 165, nameWidth, 48, 650, '#ffc586');
      lettering(quantity, x + Math.min(nameWidth, ctx.measureText(giftName).width) + 12,
        165, available, 48, 650, '#ffc586');
    });
  }

  return function update(rows) {
    const entries = rows.slice(0, 3).map(row => ({
      nickname: String(row.nickname || '观众'),
      giftName: String(row.giftName || '礼物'),
      count: Math.max(1, Number(row.count) || 1),
    }));
    const signature = JSON.stringify(entries);
    if (signature === previous) return false;
    previous = signature;
    draw(entries);
    canvas.setAttribute('aria-label', entries.length
      ? '礼物墙。' + entries.map(e => e.nickname + '送出' + e.giftName + ' ×' + e.count).join('。')
      : '礼物墙，等待本场第一份礼物');
    return true;
  };
}
