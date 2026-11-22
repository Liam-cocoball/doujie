// Cut a line into playable beats. Punctuation provides most cuts in natural Chinese;
// a long unpunctuated line still gets a change in emphasis while it is on air.
const colours = {
  neutral: ['talk', 'present', 'nod', 'sweep'], happy: ['wave', 'present', 'nod'],
  surprised: ['recoil', 'point', 'shrug'], grumpy: ['point', 'cut', 'fold'],
  skeptical: ['chin', 'present', 'lean'], smirk: ['sweep', 'cut', 'chin'],
  deadpan: ['fold', 'look', 'present'], soft: ['hold', 'nod', 'present'],
};
const inflections = {
  neutral:['neutral','smirk'], happy:['happy','smirk'], surprised:['skeptical','deadpan'],
  grumpy:['deadpan','skeptical'], skeptical:['deadpan','smirk'], smirk:['skeptical','deadpan'],
  deadpan:['skeptical','smirk'], soft:['neutral','soft'],
};
const sharpMoods = new Set(['grumpy', 'skeptical', 'smirk', 'deadpan']);

function clauses(text) {
  const result = [];
  let chunk = '';
  for (const ch of Array.from(text)) {
    chunk += ch;
    const size = chunk.length;
    if (/[。！？!?；;]/u.test(ch) || (size >= 4 && /[，、：,:]/u.test(ch)) || size >= 12) {
      result.push(chunk);
      chunk = '';
    }
  }
  if (chunk) result.push(chunk);
  // Give a tiny trailing fragment enough screen time to share the preceding gesture.
  if (result.length > 1 && result.at(-1).length < 4) {
    const tail = result.pop();
    result[result.length - 1] += tail;
  }
  return result;
}

export function planPerformance(part) {
  const text = String(part.text || '');
  const expression = Object.hasOwn(colours, part.expression) ? part.expression : 'neutral';
  const first = part.gesture || part.cue || (text ? 'talk' : 'idle');
  const key = String(part.id ?? '') + ':' + (part.segmentIndex ?? '') + ':' + text;
  let seed = 5381;
  for (const ch of key) seed = (Math.imul(seed, 33) ^ ch.codePointAt(0)) >>> 0;
  const random = () => {
    seed = (Math.imul(1664525, seed) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const chunks = clauses(text);
  if (!chunks.length) chunks.push('');
  let last = '', previous = '', lastMood = '', end = 0;
  return chunks.map((chunk, index) => {
    let mood = expression;
    if (index === 0) mood = expression;
    else if (/[？?]/u.test(chunk)) mood = 'skeptical';
    else if (/[！!]/u.test(chunk)) {
      // A raised voice lands a barb with a glare; the host was not startled by her own line.
      mood = sharpMoods.has(expression) ? 'grumpy' : expression === 'happy' ? 'happy' : 'surprised';
    }
    else if (index === chunks.length - 1 && ['deadpan', 'skeptical', 'smirk'].includes(expression)) {
      mood = expression === 'smirk' ? 'deadpan' : 'smirk';
    } else {
      const moods = inflections[expression].filter(value => value !== lastMood);
      mood = moods[Math.floor(random() * moods.length)];
    }
    const choices = colours[mood].filter(gesture => gesture !== last && gesture !== previous);
    const gesture = index === 0 && first !== 'talk' ? first : choices[Math.floor(random() * choices.length)];
    previous = last; last = gesture; lastMood = mood;
    const start = end;
    end += chunk.length / Math.max(1, text.length);
    return {start, end: index === chunks.length - 1 ? 1 : end, gesture,
      mood, side: random() < .5 ? 1 : -1,
      strength: .88 + .23 * random(), phase: random() * Math.PI * 2};
  });
}
