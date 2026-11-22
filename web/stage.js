const stage = document.querySelector('#stage');
const utterance = document.querySelector('#utterance');
const eventLine = document.querySelector('#event-line');
const replyName = document.querySelector('#reply-name');
const replyText = document.querySelector('#reply-text');
const audioButton = document.querySelector('#enable-sound');
const giftNotice = document.querySelector('#gift-notice');
let wallRows = [], paintWall = null;
const player = globalThis.crypto?.randomUUID?.() || 'stage-' + Date.now() + '-' + Math.random().toString(36).slice(2);
const giftNames = {小心心:'heart',玫瑰:'rose',大啤酒:'beer',棒棒糖:'lollipop',加油鸭:'duck',荧光棒:'glowstick',礼花筒:'cannon',浪漫花火:'fireworks',跑车:'car'};

let active = null, current = null, avatar = null, fx = null, pose = {}, mouth = 0, revision = -1;
let poseStarted = 0, poseEnded = false, mirrorTimer = 0;
let mirrorCaption = null;
let giftTimer = 0, mirrorIndex = -1, stopped = false, lastGift = null;
let preparingId = null, receivedId = null, receiptTimer = 0;
const receiptLabels = {comment:'收到弹幕', topic:'收到投稿', like:'收到点赞', room_join:'听众入场', follow:'收到关注', fans_club_join:'新团员入场'};
const seenGifts = new Set();
const speech = () => window.doujieSpeech;
const sendUI = (name, detail) => window.dispatchEvent(new CustomEvent('scarf:' + name, {detail}));

function poseAs(part = {}) {
  pose = part;
  poseStarted = performance.now();
  poseEnded = false;
  avatar?.setPose(part);
  stage.dataset.cue = part.gesture || part.cue || 'idle';
  stage.dataset.expression = part.expression || 'neutral';
}

function segmentPose(cue, part, segmentIndex, duration, voiced, elapsed = 0) {
  poseAs({...cue, ...part, gesture:part.gesture || part.cue || cue.cue, segmentIndex, duration, voiced, elapsed});
}

function endPose() {
  poseEnded = true;
  avatar?.endSegment?.();
}

function setLine(text, speaking = false) {
  utterance.textContent = text;
  stage.dataset.dialogue = String(Boolean(text.trim()) || !eventLine.hidden);
  stage.dataset.speaking = String(speaking);
}

function sourceLabel(cue) {
  const nickname = cue.replyTarget?.name || cue.nickname || cue.name;
  const isReply = cue.source === 'comment' || cue.source === 'topic';
  const target = nickname ? (nickname.startsWith('@') ? nickname : '@' + nickname) : '这位听众';
  replyName.textContent = isReply ? '回复 ' + target : '';
  replyText.textContent = isReply ? cue.replyTarget?.text || cue.prompt || '' : '';
  eventLine.hidden = !isReply;
}

function cancel() {
  const old = current;
  current = null;
  old?.aborter.abort();
  speech()?.stop();
  clearTimeout(mirrorTimer);
  clearTimeout(mirrorCaption?.pageTimer);
  mirrorCaption = null;
  endPose();
  mouth = 0;
}

function reset({isStopped = false} = {}) {
  cancel(); active = null; mirrorIndex = -1; preparingId = null; stopped = isStopped;
  stage.dataset.stopped = String(isStopped); stage.dataset.source = '';
  if (isStopped || stage.dataset.received !== 'true') {
    document.querySelector('#air-label').textContent = isStopped ? '已暂停' : '直播中';
  }
  eventLine.hidden = true;replyName.textContent = '';replyText.textContent = '';
  poseAs({gesture:isStopped ? 'idle' : 'fold', expression:'deadpan', camera:'medium'});
  setLine('');
  if (isStopped) {
    clearTimeout(receiptTimer); stage.dataset.received = 'false';
    clearTimeout(giftTimer);giftNotice.hidden = true;lastGift = null;fx?.clear();
  }
  sendUI('reset', {stopped:isStopped});
}

function showReceipt(item) {
  if (!item || item.id === receivedId || !receiptLabels[item.source]) return;
  receivedId = item.id;
  if (Date.now() - item.at > 1800) return;
  clearTimeout(receiptTimer);
  stage.dataset.received = 'true';
  document.querySelector('#air-label').textContent = receiptLabels[item.source];
  receiptTimer = setTimeout(() => {
    stage.dataset.received = 'false';
    document.querySelector('#air-label').textContent = stopped ? '已暂停' : '直播中';
  }, 1150);
}

function showPreparing(cue) {
  if (preparingId === cue.id) return;
  preparingId = cue.id;
  sourceLabel(cue);
  poseAs({gesture:'look', expression:'skeptical', camera:'medium'});
  setLine('');
}

function giftEffect(item) {
  return item.effect || item.giftFx || item.giftId || giftNames[item.giftName] || 'generic';
}

function showGift(item, restoring = false) {
  if (!item || typeof item !== 'object') return;
  const id = item.id ?? item.eventId;
  const at = Number(item.timestamp ?? item.at);
  if (id == null || seenGifts.has(id) || (at && Date.now() - at > 6500)) return;
  seenGifts.add(id);
  if (seenGifts.size > 128) seenGifts.delete(seenGifts.values().next().value);
  if (restoring) return;
  const nickname = item.nickname || item.name || '观众';
  const gift = item.giftName || '礼物';
  const count = Math.max(1,Number(item.count || item.giftCount || 1));
  document.querySelector('#gift-sender').textContent = String(nickname).slice(0,22) + ' 送来';
  document.querySelector('#gift-name').textContent = gift + (count > 1 ? ' ×' + count : '');
  giftNotice.hidden = false;
  lastGift = {effect:giftEffect(item),at:Date.now()};
  fx?.show(lastGift.effect);
  clearTimeout(giftTimer); giftTimer = setTimeout(()=>{giftNotice.hidden = true;}, 2700);
}

function segments(cue) {
  return Array.isArray(cue.segments) && cue.segments.length ? cue.segments : [{text:cue.text||'',gesture:cue.cue,expression:cue.expression}];
}

const pageLimit = 36;

// Keep long operator-written lines legible. Page changes follow the duration of the actual audio.
function pages(text) {
  const chars = Array.from(String(text));
  const parts = [];
  let start = 0;
  while (chars.length - start > pageLimit) {
    const limitAt = start + pageLimit;
    let end = limitAt;
    for (let i = limitAt; i >= start + 20; i--) {
      if (/[。！？；，、,.!?\s]/u.test(chars[i-1])) {end = i;break;}
    }
    if (end === limitAt && /[a-z\d]/i.test(chars[end])) {
      let word = end;
      while (word > start && /[a-z\d]/i.test(chars[word-1])) word--;
      if (word > start) end = word;
    }
    // Keep a closing quote or punctuation mark attached to the line it belongs to.
    while (end < chars.length && end < limitAt + 2 && /[。！？；，、,.!?）”’」]/u.test(chars[end])) end++;
    parts.push(chars.slice(start,end).join(''));
    start = end;
  }
  if (start < chars.length || !parts.length) parts.push(chars.slice(start).join(''));
  return parts;
}

function caption(run, cue, indexInCue, part, duration, speaking, elapsedSeconds = 0) {
  clearTimeout(run.pageTimer);
  const text = part.text || '';
  const lines = pages(text);
  // A short opener can stay beside its punchline once the second segment is on air.
  if (indexInCue === 1 && text && (cue.source === 'comment' || cue.source === 'topic')) {
    const opener = String(segments(cue)[0].text || '').trim();
    const separator = /\p{P}$/u.test(opener) ? '' : ' ';
    const together = opener + separator + text;
    if (opener && Array.from(opener).length <= 12 && Array.from(together).length <= pageLimit) {
      lines[0] = together;
    }
  }
  const startedAt = performance.now() - elapsedSeconds * 1000;
  let index = 0, boundary = lines[0].length;
  const display = seconds => {
    if (current !== run && mirrorCaption !== run) return;
    clearTimeout(run.pageTimer);
    const elapsed = performance.now() - startedAt;
    const msPerChar = seconds * 1000 / Math.max(1, text.length);
    while (index < lines.length - 1 && elapsed >= boundary * msPerChar) {
      boundary += lines[++index].length;
    }
    setLine(lines[index], speaking);
    if (index < lines.length - 1) {
      run.pageTimer = setTimeout(() => display(seconds), Math.max(1, Math.ceil(boundary * msPerChar - elapsed)));
    }
  };
  display(duration);
  return display;
}

async function ack(id, phase, extra = {}) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch('/api/playback', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id,player,phase,...extra}), cache:'no-store', signal:AbortSignal.timeout(3000),
      });
      if (!res.ok) throw new Error('playback ' + res.status);
      return await res.json();
    } catch (error) {
      if (attempt === 1) throw error;
    }
  }
}

function delay(ms, signal) {
  if (signal.aborted || !ms) return Promise.resolve();
  return new Promise(resolve=>{
    function finish(){clearTimeout(timer);signal.removeEventListener('abort',finish);resolve();}
    const timer = setTimeout(finish, ms);signal.addEventListener('abort',finish,{once:true});
  });
}

async function perform(cue, claim) {
  const run = {aborter:new AbortController(),pageTimer:0,tailTimer:0,owned:false,settled:false};
  current = run;
  const signal = run.aborter.signal;
  signal.addEventListener('abort',()=>{
    clearTimeout(run.pageTimer);
    clearTimeout(run.tailTimer);
  },{once:true});
  try {
    if (claim) {
      // A reopened window or another browser profile must not speak a claimed line a second time.
      const acquired = await ack(cue.id,'start');
      if (signal.aborted) return;
      if (!acquired.accepted) {if(current === run) current = null;return;}
    }
    run.owned = claim;
    const parts = [...segments(cue)];
    for (const [index, part] of parts.entries()) {
      if (signal.aborted) return;
      const fallbackMs = part.text ? Math.min(14000,Math.max(1350,Array.from(part.text).length * 165 + 450)) : 1500;
      let started = false, segmentStarted, updateDuration;
      const dynamicTail = claim && index === 0 && cue.tailPending && parts.length > 1;
      let openerAt, seconds, voicedOpener, pendingTail = false, lineEnded = false;
      function useClosing(reply) {
        if (!reply?.accepted || signal.aborted) return;
        if (reply.nextSegment?.text) parts[1] = reply.nextSegment;
        if (voicedOpener && !lineEnded) speech()?.prepareNext?.(parts[1].text, signal);
      }
      function scheduleClosing() {
        if (!pendingTail || lineEnded || signal.aborted) return;
        clearTimeout(run.tailTimer);
        // Give the model part of the opener, reserving time to synthesize a changed closing line.
        const afterOnset = Math.min(1500, seconds * 1000 - 650);
        run.tailTimer = setTimeout(async () => {
          pendingTail = false;
          try {
            const reply = await ack(cue.id,'segment',{index,acceptNextSegment:true});
            if (!lineEnded) useClosing(reply);
          } catch { /* The end acknowledgement still returns the authoritative closing line. */ }
        }, Math.max(0, afterOnset - (performance.now() - openerAt)));
      }
      function begin(duration, voiced) {
        if (signal.aborted || started) return;
        started = true;
        openerAt = performance.now();seconds = duration;voicedOpener = voiced;
        segmentPose(cue,part,index,duration,voiced);
        updateDuration = caption(run,cue,index,part,duration,voiced);
        if (index === 0 && cue.source === 'gift' && (!lastGift || Date.now() - lastGift.at > 3200)) {
          fx?.show(giftEffect(cue));
        }
        if (claim) {
          segmentStarted = ack(cue.id,'segment',{index, durationMs:Math.round(duration*1000),
            ...(dynamicTail ? {acceptNextSegment:true,deferNextSegment:true} : {})})
            .then(response => {
              if (dynamicTail && response.accepted && !signal.aborted) {
                useClosing(response);
                pendingTail = response.tailPending === true;
                scheduleClosing();
              }
              return response.accepted;
            }).catch(()=>false);
        }
        sendUI('segment',{id:cue.id,index});
      }
      let result = {status:'unavailable'};
      if (part.text && speech()) {
        try {
          result = await speech().say(part.text,{
            signal, nextText:dynamicTail ? undefined : parts[index+1]?.text,
            onStart:duration=>begin(Number(duration)||fallbackMs/1000,true),
            onDuration:duration=>{
              if (!started || !Number.isFinite(duration) || duration <= 0 || signal.aborted) return;
              seconds = duration;
              scheduleClosing();
              pose.duration = duration;
              avatar?.setDuration?.(duration);
              updateDuration?.(duration);
            },
          });
        } catch { /* Subtitle timing keeps the show advancing when the local voice worker is unavailable. */ }
      }
      if (signal.aborted || result?.status === 'cancelled') return;
      if (result?.status === 'interrupted') throw new Error('语音传输中断');
      if (!started) begin(fallbackMs/1000,false);
      if (result?.status !== 'ended' || !part.text) await delay(fallbackMs,signal);
      clearTimeout(run.pageTimer);
      if (signal.aborted) return;
      lineEnded = true;
      clearTimeout(run.tailTimer);
      setLine('');mouth=0;endPose();
      if (claim) {
        const confirmed = await segmentStarted && await ack(cue.id,'segment_end',
          dynamicTail ? {index,acceptNextSegment:false} : {index});
        if (!confirmed?.accepted) throw new Error('舞台已失去当前发言的播出权');
        if (dynamicTail) useClosing(confirmed);
      }
      await delay(Math.min(1800,Math.max(0,Number(part.pauseMs)||0)),signal);
    }
    if (claim && !signal.aborted) {await ack(cue.id,'complete');run.settled=true;}
  } catch (error) {
    if (!signal.aborted) {
      endPose();
      setLine('');
      if (run.owned) void ack(cue.id,'error').catch(()=>{});
      console.warn('直播表演连接中断',error);
    }
  } finally {
    clearTimeout(run.pageTimer);
    clearTimeout(run.tailTimer);
    if (current === run && !run.owned) current = null;
  }
}

function adopt(cue, claim = true) {
  cancel();active = cue;mirrorIndex = -1;preparingId = null;stopped = false;
  stage.dataset.stopped = 'false';stage.dataset.source = cue.source || '';
  if (stage.dataset.received !== 'true') document.querySelector('#air-label').textContent = '直播中';
  sourceLabel(cue);
  poseAs({gesture:'look',expression:'skeptical',camera:'medium'});
  setLine('');
  sendUI('show',cue);
  if (!claim || !cue.status || cue.status === 'ready') void perform(cue,claim);
}

function snapshot(state) {
  const restoring = revision < 0;
  if (Number.isFinite(state.revision)) {
    if (state.revision < revision) return;
    revision = state.revision;
  }
  if (Array.isArray(state.giftWall)) {
    wallRows = state.giftWall;
    if (paintWall?.(wallRows)) avatar?.refreshGiftWall();
  }
  if (!state.stopped) {
    showReceipt(state.received);
    const gifts = state.giftEffects?.length ? state.giftEffects : [state.giftFx || state.giftFlash];
    for (const item of gifts) showGift(item, restoring);
  }
  if (state.stopped || !state.active) {
    if (active || stopped !== Boolean(state.stopped) || (preparingId !== null && !state.preparing)) reset({isStopped:Boolean(state.stopped)});
    if (!state.stopped && state.preparing) showPreparing(state.preparing);
    return;
  }
  const cue = state.active;
  if (active?.id !== cue.id) adopt(cue);
  else active = cue;
  if (!current && cue.status === 'playing') {
    const index = cue.currentSegment;
    if (Number.isInteger(index) && index >= 0 && index !== mirrorIndex) {
      mirrorIndex = index;
      const part = segments(cue)[index] || cue;
      const duration = cue.segmentDurationMs / 1000 || Math.max(1.35, Array.from(part.text || '').length * .165);
      const elapsed = Math.max(0, (Date.now() - (cue.segmentStartedAt || Date.now())) / 1000);
      clearTimeout(mirrorTimer);
      segmentPose(cue,part,index,duration,false,elapsed);
      clearTimeout(mirrorCaption?.pageTimer);
      mirrorCaption = {pageTimer:0};
      if (elapsed < duration) caption(mirrorCaption,cue,index,part,duration,false,elapsed);
      mirrorTimer = setTimeout(() => {
        clearTimeout(mirrorCaption?.pageTimer);
        endPose();setLine('');
      }, Math.max(0, duration - elapsed) * 1000);
    }
  }
}

window.scarfStage = {
  show:cue=>adopt(cue,false), reset, setMouth:n=>{mouth=Number.isFinite(n)?Math.max(0,Math.min(1,n)):0;},
  getState:()=>({active,stopped,revision,view:stage.dataset.view})
};
reset();
audioButton.hidden = true;
document.addEventListener('doujie:audio-status', event => {
  audioButton.hidden = event.detail !== 'locked';
});
function checkAudio() { void speech()?.unlock(); }
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', checkAudio, {once:true});
else checkAudio();
audioButton.addEventListener('click',async()=>{
  try {if (await speech()?.unlock()) audioButton.hidden = true;} catch {}
});
import('./stage-avatar.js').then(({startAvatar})=>startAvatar(document.querySelector('#scarf-canvas'),
  ()=>Math.max(mouth,Number(speech()?.level())||0),
  ()=>{stage.dataset.view='model';},()=>{stage.dataset.view='fallback';}))
  .then(result=>{
    avatar=result;
    avatar.refreshGiftWall?.();
    const elapsed = (pose.elapsed || 0) + (performance.now() - poseStarted) / 1000;
    avatar.setPose({...pose, elapsed});
    if (poseEnded) avatar.endSegment?.();
  })
  .catch(error=>console.warn('3D 舞台切换到静态画面',error));
import('./stage-wall.js').then(({makeGiftWall})=>{
  paintWall = makeGiftWall(document.querySelector('#gift-wall'));
  if (paintWall(wallRows)) avatar?.refreshGiftWall();
}).catch(error=>console.warn('礼物墙暂未加载',error));
import('./stage-gifts.js').then(({makeGiftEffects})=>{
  fx=makeGiftEffects(document.querySelector('#gift-effects'));
  if(lastGift && Date.now()-lastGift.at<1300) fx.show(lastGift.effect);
}).catch(error=>console.warn('礼物动画暂未加载',error));

if ('EventSource' in window) {
  const stream = new EventSource('/api/stream?view=stage');
  stream.addEventListener('open',()=>{revision=-1;});
  stream.addEventListener('state',e=>{try{snapshot(JSON.parse(e.data));}catch(error){console.warn('舞台状态无效',error);}});
  window.addEventListener('pagehide',()=>{
    stream.close();
    if(current?.owned&&!current.settled&&active){
      const message = new Blob([JSON.stringify({id:active.id,player,phase:'error'})],{type:'application/json'});
      navigator.sendBeacon('/api/playback',message);
    }
    cancel();
  },{once:true});
}
