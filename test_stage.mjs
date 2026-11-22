import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {runInNewContext} from 'node:vm';

const html = readFileSync(new URL('./web/stage.html', import.meta.url), 'utf8');
// Substitute the browser asset imports. All cue and speech routing is the live stage module.
const source = readFileSync(new URL('./web/stage.js', import.meta.url), 'utf8')
  .replace(/\bimport\(/g, 'loadAsset(');
const flush = () => new Promise(resolve => setImmediate(resolve));

async function openStage({deferAvatar = false, playback = () => ({accepted:true})} = {}) {
  const nodes = new Map();
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
    nodes.set('#' + id, Object.assign(new EventTarget(), {dataset:{}, textContent:'', hidden:false}));
  }
  const node = selector => nodes.get(selector);
  const poses = [], durations = [], utterances = [], acknowledgments = [], prefetched = [];
  const wallFrames = [], effects = [];
  const clock = {now:10000};
  let stream, loadModel, revision = 0, ended = 0;
  const rig = {
    refreshGiftWall() {},
    setPose(pose) { poses.push({...pose}); },
    setDuration(seconds) { durations.push(seconds); },
    endSegment() { ended++; },
  };
  const speech = {
    unlock:async () => true, level:() => 0, stop() {},
    prepareNext(text) { prefetched.push(text); },
    say(text, options) {
      return new Promise(resolve => {
        utterances.push({text, ...options, finish:() => resolve({status:'ended'})});
        options.signal.addEventListener('abort', () => resolve({status:'cancelled'}), {once:true});
      });
    },
  };
  class StageStream extends EventTarget {
    constructor(url) { super(); assert.equal(url, '/api/stream?view=stage'); stream = this; }
    close() {}
  }
  async function loadAsset(path) {
    if (path === './stage-avatar.js') {
      return {startAvatar:() => deferAvatar ? new Promise(resolve => { loadModel = () => resolve(rig); }) : rig};
    }
    if (path === './stage-wall.js') return {makeGiftWall:() => rows => {wallFrames.push(rows); return true;}};
    assert.equal(path, './stage-gifts.js');
    return {makeGiftEffects:() => ({show(effect) {effects.push(effect);}, clear() {}})};
  }
  runInNewContext(source, {
    window:Object.assign(new EventTarget(), {EventSource:StageStream, doujieSpeech:speech}),
    document:Object.assign(new EventTarget(), {querySelector:node, readyState:'complete'}),
    EventSource:StageStream, CustomEvent, AbortController, AbortSignal, console, loadAsset,
    Date:class extends Date { static now() { return clock.now; } }, performance:{now:() => clock.now},
    setTimeout:(fn, ms) => setTimeout(fn, ms).unref(), clearTimeout,
    async fetch(url, options) {
      assert.equal(url, '/api/playback');
      const message = JSON.parse(options.body);
      acknowledgments.push(message);
      return {ok:true, json:async () => playback(message)};
    },
  });
  await flush();
  function snapshot(fields) {
    stream.dispatchEvent(new MessageEvent('state', {data:JSON.stringify({revision:++revision, stopped:false, ...fields})}));
  }
  return {node, snapshot, clock, poses, durations, utterances, acknowledgments, prefetched, wallFrames, effects,
    get ended() { return ended; }, loadModel:() => loadModel()};
}

test('the gift wall restores recent senders independently of live effects and clears between rooms', async () => {
  const h = await openStage();
  const entries = [{nickname:'花花', giftName:'玫瑰', count:3}];
  const restored = {id:30, nickname:'花花', giftName:'玫瑰', count:3, effect:'rose', at:h.clock.now};
  h.snapshot({giftWall:entries, giftEffects:[restored]});
  assert.equal(h.wallFrames.at(-1)[0].nickname, '花花');
  assert.deepEqual(h.effects, []);
  const delivered = {id:31, nickname:'花花', giftName:'玫瑰', count:4, effect:'rose', at:h.clock.now};
  for (let i = 0; i < 2; i++) h.snapshot({giftWall:[{...entries[0], count:4}], giftEffects:[restored, delivered]});
  assert.equal(h.wallFrames.at(-1)[0].count, 4);
  assert.deepEqual(h.effects, ['rose']);
  h.snapshot({giftWall:[], giftEffects:[]});
  assert.equal(h.wallFrames.at(-1).length, 0);
  assert.equal(h.utterances.length, 0);
});

function comment() {
  return {id:'comment-1', source:'comment', status:'ready',
    replyTarget:{name:'小鱼', text:'老板说公司就是我的第二个家。'},
    segments:[{text:'先把房本拿来。', gesture:'look', expression:'deadpan'},
      {text:'分房给你写了几平？', gesture:'point', expression:'smirk'}]};
}

test('a gift notice and a delayed thank-you both use the visual effect chosen for the gift', async () => {
  const h = await openStage();
  const gift = {id:41, giftName:'嘉年华', giftId:'generic_high', effect:'generic', nickname:'阿梨', count:2};
  h.snapshot({giftEffects:[]});
  h.snapshot({giftEffects:[gift]});
  assert.deepEqual(h.effects, ['generic']);
  assert.equal(h.node('#gift-name').textContent, '嘉年华 ×2');
  h.clock.now += 4000;
  h.snapshot({active:{...gift, id:42, source:'gift', status:'ready', text:'谢谢阿梨，两份嘉年华。'}});
  await flush();
  h.utterances[0].onStart(1);
  assert.deepEqual(h.effects, ['generic', 'generic']);
  h.snapshot({active:null});
});

test('the reply card shows the viewer while TTS and each voiced pose follow only the answer', async () => {
  const h = await openStage();
  const cue = comment();
  const target = () => [h.node('#reply-name').textContent, h.node('#reply-text').textContent];
  const label = ['回复 @小鱼', cue.replyTarget.text];
  h.snapshot({active:null, preparing:cue});
  assert.deepEqual(target(), label);
  assert.equal(h.node('#event-line').hidden, false);
  assert.equal(h.node('#stage').dataset.dialogue, 'true');
  assert.equal(h.node('#utterance').textContent, '');
  assert.equal(h.utterances.length, 0);

  h.snapshot({active:cue});
  await flush();
  h.utterances[0].onStart(1.8);
  assert.equal(h.poses.at(-1).segmentIndex, 0);
  assert.equal(h.poses.at(-1).duration, 1.8);
  assert.equal(h.poses.at(-1).elapsed, 0);
  assert.equal(h.poses.at(-1).voiced, true);
  assert.equal(h.poses.at(-1).gesture, 'look');
  assert.equal(h.poses.at(-1).expression, 'deadpan');
  h.utterances[0].onDuration(1.42);
  assert.deepEqual(h.durations, [1.42]);
  const other = {id:'next', source:'comment', replyTarget:{name:'老李', text:'轮到我了吗？'}};
  h.snapshot({active:{...cue, status:'playing'}, preparing:other, received:{...other, at:h.clock.now}});
  assert.equal(h.node('#air-label').textContent, '收到弹幕');
  assert.deepEqual(target(), label);
  assert.equal(h.node('#utterance').textContent, cue.segments[0].text);

  const beforeEnd = h.ended;
  h.utterances[0].finish();
  await flush();
  assert.equal(h.ended, beforeEnd + 1);
  h.utterances[1].onStart(.95);
  assert.equal(h.node('#utterance').textContent, cue.segments.map(part => part.text).join(''));
  assert.equal(h.poses.at(-1).segmentIndex, 1);
  assert.equal(h.poses.at(-1).gesture, 'point');
  assert.equal(h.poses.at(-1).expression, 'smirk');
  assert.deepEqual(h.utterances.map(s => s.text), cue.segments.map(s => s.text));
  assert.equal(h.utterances[0].nextText, cue.segments[1].text);
  h.utterances[1].finish();
  await flush();
  assert.deepEqual(h.acknowledgments.map(a => a.phase), ['start','segment','segment_end','segment','segment_end','complete']);
  h.snapshot({active:null});
  assert.equal(h.node('#event-line').hidden, true);
  assert.equal(h.node('#stage').dataset.dialogue, 'false');
  assert.deepEqual(target(), ['', '']);
});

test('each brief comment speaks once even when its live state is delivered again', async () => {
  const h = await openStage();
  for (const id of [31, 32]) {
    const cue = {
      id, source:'comment', status:'ready', replyTarget:{name:'小鱼', text:'哈哈'},
      segments:[{text:'笑够没？', expression:'smirk', gesture:'look'}],
    };
    const previous = h.utterances.length;
    h.snapshot({active:cue});
    h.snapshot({active:cue});
    await flush();
    assert.equal(h.utterances.length, previous + 1);
    const voice = h.utterances[previous];
    assert.equal(voice.text, cue.segments[0].text);
    assert.equal(voice.nextText, undefined);
    voice.onStart(0.8);
    h.snapshot({active:{...cue, status:'playing', currentSegment:0}});
    assert.equal(h.node('#utterance').textContent, voice.text);
    voice.finish();
    await flush();
    assert.deepEqual(h.acknowledgments.filter(ack => ack.id === id).map(ack => ack.phase),
      ['start', 'segment', 'segment_end', 'complete']);
    assert.equal(h.utterances.length, previous + 1);
    h.snapshot({active:null});
  }
  assert.deepEqual(h.prefetched, []);
});

test('a gift opens immediately and can take a rewritten closing while the opener is on air', async () => {
  const base = {text:'跑车靠边停。'}, rewrite = {text:'副驾驶坐的是我的坏脾气。'};
  let committed = false;
  const h = await openStage({playback(message) {
    if (message.index !== 0) return {accepted:true};
    if (message.phase === 'segment' && !message.deferNextSegment) committed = true;
    return {accepted:true, tailPending:!committed, nextSegment:committed ? rewrite : base};
  }});
  h.snapshot({active:{id:91, source:'gift', status:'ready', tailPending:true,
    segments:[{text:'远光给我关上。'},base]}});
  await flush();
  const first = h.utterances[0];
  first.onStart(3);
  await flush();
  assert.deepEqual(h.prefetched, [base.text]);
  // A streaming length update moves the decision earlier, while the opener still owns the mic.
  first.onDuration(.66);
  await new Promise(resolve => setTimeout(resolve, 35));
  assert.deepEqual(h.prefetched, [base.text, rewrite.text]);
  assert.equal(h.utterances.length, 1);
  first.finish();
  await flush();
  assert.equal(h.utterances[1].text, rewrite.text);
  h.snapshot({active:null});
});

test('an early-ending opener uses the prepared gift line without waiting for a model rewrite', async () => {
  const base = {text:'红毯卷起来。'};
  const h = await openStage({playback:message => ({
    accepted:true, nextSegment:base, tailPending:message.deferNextSegment === true,
  })});
  h.snapshot({active:{id:92,source:'gift',status:'ready',tailPending:true,
    segments:[{text:'这排场挺大。'},base]}});
  await flush();
  h.utterances[0].onStart(4);
  await flush();
  h.utterances[0].finish();
  await flush();
  assert.equal(h.utterances[1].text, base.text);
  assert.deepEqual(h.acknowledgments.map(a => a.phase), ['start','segment','segment_end']);
  assert.equal(h.acknowledgments.at(-1).acceptNextSegment, false);
  h.snapshot({active:null});
});

test('a stopped cue releases its pose and ignores late audio callbacks', async () => {
  const h = await openStage();
  h.snapshot({active:comment()});
  await flush();
  const speaking = h.utterances[0];
  speaking.onStart(2);
  const ended = h.ended;
  h.snapshot({active:null, stopped:true});
  speaking.onDuration(4);
  await flush();
  assert.ok(speaking.signal.aborted);
  assert.ok(h.ended > ended);
  assert.equal(h.node('#stage').dataset.speaking, 'false');
  assert.equal(h.node('#event-line').hidden, true);
  assert.deepEqual(h.durations, []);
  assert.equal(h.utterances.length, 1);
  assert.deepEqual(h.acknowledgments.map(a => a.phase), ['start','segment']);
});

test('a late-loaded avatar joins the current gesture on time without claiming or repeating audio', async () => {
  const h = await openStage({deferAvatar:true});
  const cue = comment();
  h.snapshot({active:{...cue, status:'playing', currentSegment:1,
    segmentDurationMs:2000, segmentStartedAt:h.clock.now - 500}});
  h.clock.now += 250;
  h.loadModel();
  await flush();
  const pose = h.poses.at(-1);
  assert.equal(pose.segmentIndex, 1);
  assert.equal(pose.gesture, cue.segments[1].gesture);
  assert.equal(pose.voiced, false);
  assert.equal(pose.duration, 2);
  assert.equal(pose.elapsed, .75);
  assert.equal(h.utterances.length, 0);
  assert.equal(h.acknowledgments.length, 0);
  h.snapshot({active:null});
});

test('a stage joining mid-speech opens the current caption page and clears it on reset', async () => {
  const h = await openStage();
  assert.equal(h.node('#stage').dataset.dialogue, 'false');
  const intro = '先把你刚才猜的那个答案连同理由好好写在这张桌子上，';
  const closing = '再看看今天到底是谁先猜中了。';
  const cue = {id:'mirror-2',source:'manual',status:'playing',currentSegment:0,
    segmentDurationMs:6000,segmentStartedAt:h.clock.now-4900,segments:[{text:intro+closing}]};
  h.snapshot({active:cue});
  assert.equal(h.node('#utterance').textContent, closing);
  assert.equal(h.node('#stage').dataset.dialogue, 'true');
  assert.equal(h.utterances.length, 0);
  h.snapshot({active:null});
  assert.equal(h.node('#stage').dataset.dialogue, 'false');
  assert.equal(h.node('#utterance').textContent, '');
});

test('a mirror keeps only the current reply’s short opener and never adds it to gifts or long pages', async () => {
  const h = await openStage(), opening = {text:'真敢开口。'};
  const mirror = (id, source, text) => h.snapshot({active:{id,source,status:'playing',currentSegment:1,
    segmentDurationMs:6000,segmentStartedAt:h.clock.now,replyTarget:{name:'阿海',text:'想听你怎么说'},
    segments:[opening,{text}]}});
  mirror('short','topic','加班费先结清。');
  assert.equal(h.node('#utterance').textContent,'真敢开口。加班费先结清。');
  assert.equal(h.node('#event-line').hidden,false);
  const fullPage = '来'.repeat(35);
  mirror('long','comment',fullPage);
  assert.equal(h.node('#utterance').textContent,fullPage);
  mirror('present','gift','这份礼物我收了。');
  assert.equal(h.node('#event-line').hidden,true);
  assert.equal(h.node('#utterance').textContent,'这份礼物我收了。');
  h.snapshot({active:null});
});
