// The live stage streams mono PCM from the local GPT-SoVITS worker.
const PCM_TYPE = 'application/x-doujie-pcm';
const SAMPLE_RATE = 24000;
const MAX_PCM_BYTES = 12 * 1024 * 1024;
let context;
let active;
let upcoming;
let playbackState = 'idle';
let easedLevel = 0;

function report(state) {
  playbackState = state;
  document.dispatchEvent(new CustomEvent('doujie:audio-status', {detail: state}));
}

async function unlock() {
  try {
    context ??= new AudioContext({latencyHint:'interactive'});
    if (context.state !== 'running') {
      let timer;
      try {
        await Promise.race([context.resume(), new Promise(resolve => {timer = setTimeout(resolve, 650);})]);
      } finally {
        clearTimeout(timer);
      }
    }
    if (context.state !== 'running') {
      report('locked');
      return false;
    }
    if (!active) report('ready');
    return true;
  } catch {
    report('unavailable');
    return false;
  }
}

function cancelRequest(request) {
  request.controller.abort();
  if (!request.pending) return;
  request.pending = false;
  void fetch('/api/tts/cancel', {
    method:'POST', headers:{'Content-Type':'application/json'}, keepalive:true,
    body:JSON.stringify({requestId:request.id}),
  }).catch(() => {});
}

function finish(job, status) {
  if (job.finished) return;
  job.finished = true;
  clearTimeout(job.timer);
  clearTimeout(job.startTimer);
  job.signal?.removeEventListener('abort', job.abort);
  job.request.consumer = null;
  for (const source of job.sources) {
    source.onended = null;
    try {source.stop();} catch {}
    source.disconnect();
  }
  job.sources.clear();
  job.analyser?.disconnect();
  if (active === job) {
    active = null;
    easedLevel = 0;
    report(status === 'unavailable' && playbackState === 'locked' ? 'locked'
      : ['unavailable','interrupted'].includes(status) ? 'unavailable' : 'ready');
  }
  const result = {status, duration:job.request.duration};
  job.resolve(result);
  job.onEnd?.(result);
}

function discardNext() {
  if (!upcoming) return;
  upcoming.signal?.removeEventListener('abort', upcoming.abort);
  cancelRequest(upcoming.request);
  upcoming = null;
}

function stop() {
  discardNext();
  if (active) {
    cancelRequest(active.request);
    finish(active, 'cancelled');
  }
}

function level() {
  if (!active?.started) return 0;
  active.analyser.getFloatTimeDomainData(active.samples);
  let sum = 0;
  for (const sample of active.samples) sum += sample * sample;
  const target = Math.min(1, 7 * Math.max(0, Math.sqrt(sum / active.samples.length) - .008));
  easedLevel += (target - easedLevel) * (target > easedLevel ? .5 : .3);
  return easedLevel;
}

function newRequest() {
  return {id:crypto.randomUUID(), controller:new AbortController(), pending:false, chunks:[],
    consumer:null, duration:0, complete:false, failed:false};
}

function publish(request, buffer) {
  if (request.controller.signal.aborted) return;
  request.duration += buffer.duration;
  request.chunks.push(buffer);
  request.consumer?.();
}

async function readPCM(request, response) {
  const reader = response.body.getReader();
  let carry = new Uint8Array();
  let received = 0;
  try {
    while (true) {
      const {value, done} = await reader.read();
      if (done && !carry.byteLength) break;
      received += value?.byteLength || 0;
      if (received > MAX_PCM_BYTES) throw new Error('超出语音长度');
      let bytes = value || new Uint8Array();
      if (carry.byteLength) {
        const joined = new Uint8Array(carry.byteLength + bytes.byteLength);
        joined.set(carry);
        joined.set(bytes, carry.byteLength);
        bytes = joined;
      }
      // HTTP framing is unrelated to sample boundaries. Batch tiny reads into
      // at least 10 ms to avoid scheduling thousands of sub-millisecond nodes.
      if (!done && bytes.byteLength < 480) {carry = bytes; continue;}
      const size = bytes.byteLength - bytes.byteLength % 2;
      if (done && size !== bytes.byteLength) throw new Error('音频截断');
      carry = bytes.slice(size);
      if (size) {
        const view = new DataView(bytes.buffer, bytes.byteOffset, size);
        const buffer = context.createBuffer(1, size / 2, SAMPLE_RATE);
        const floats = buffer.getChannelData(0);
        for (let i = 0; i < floats.length; i++) floats[i] = view.getInt16(2*i,true) / 32768;
        publish(request, buffer);
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}

async function fetchAudio(request, text) {
  request.pending = true;
  try {
    const response = await fetch('/api/tts', {
      method:'POST', headers:{'Content-Type':'application/json',Accept:PCM_TYPE},
      body:JSON.stringify({text,requestId:request.id}), signal:request.controller.signal, cache:'no-store',
    });
    if (!response.ok) throw new Error('合成失败');
    if (response.headers.get('Content-Type')?.split(';')[0].trim() === PCM_TYPE) {
      await readPCM(request, response);
    } else {
      // Compatibility with a stage that was upgraded before its local server.
      publish(request, await context.decodeAudioData(await response.arrayBuffer()));
    }
    if (!request.duration) throw new Error('语音为空');
  } catch {
    request.failed = true;
    if (!request.controller.signal.aborted) cancelRequest(request);
  } finally {
    request.pending = false;
    request.complete = true;
    request.consumer?.();
  }
}

function prepareNext(text, signal) {
  if (!active?.started || active.signal !== signal || signal?.aborted || typeof text !== 'string') return;
  const normalized = text.trim();
  if (!normalized || (upcoming?.text === normalized && upcoming.signal === signal)) return;
  discardNext();
  const request = newRequest();
  const abort = () => {if (upcoming?.request === request) discardNext();};
  upcoming = {text:normalized, request, signal, abort};
  signal?.addEventListener('abort', abort, {once:true});
  void fetchAudio(request, normalized);
}

function startSound(job) {
  if (job.finished || job.started) return;
  job.started = true;
  report('speaking');
  job.onStart?.(job.request.complete ? job.request.duration : undefined);
  if (!job.finished) prepareNext(job.nextText, job.signal);
}

function consume(job) {
  if (job.finished) return;
  const request = job.request;
  if (request.failed) {
    discardNext();
    finish(job, job.started ? 'interrupted' : 'unavailable');
    return;
  }
  for (const buffer of request.chunks.splice(0)) {
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(job.analyser);
    job.sources.add(source);
    source.onended = () => {
      source.disconnect();
      job.sources.delete(source);
      if (request.complete && !job.sources.size && !job.finished) {
        startSound(job);
        finish(job,'ended');
      }
    };
    const now = context.currentTime;
    const when = Math.max(job.nextTime, now + (job.nextTime > now ? 0 : .022));
    source.start(when);
    job.nextTime = when + buffer.duration;
    if (!job.started && !job.startTimer) {
      job.startTimer = setTimeout(() => startSound(job), Math.max(0,(when-now)*1000));
    }
  }
  if (request.complete) {
    job.onDuration?.(request.duration);
    if (!job.sources.size) {
      startSound(job);
      finish(job, 'ended');
      return;
    }
    // A device switch can suspend the audio context and suppress onended.
    clearTimeout(job.timer);
    job.timer = setTimeout(() => finish(job, job.started ? 'interrupted' : 'unavailable'),
      Math.max(0, job.nextTime-context.currentTime)*1000 + 10000);
  }
}

async function play(job, text, prefetched) {
  try {
    if (!await unlock()) {
      cancelRequest(job.request);
      finish(job,'unavailable');
      return;
    }
    if (job.finished) return;
    report('preparing');
    job.analyser = context.createAnalyser();
    job.analyser.fftSize = 512;
    job.samples = new Float32Array(job.analyser.fftSize);
    job.analyser.connect(context.destination);
    job.request.consumer = () => consume(job);
    if (prefetched) consume(job);
    else await fetchAudio(job.request, text);
  } catch {
    if (!job.finished) {
      cancelRequest(job.request);
      finish(job, job.started ? 'interrupted' : 'unavailable');
    }
  }
}

function say(text, {onStart, onDuration, onEnd, signal, nextText} = {}) {
  const normalized = typeof text === 'string' ? text.trim() : '';
  let prepared;
  if (!signal?.aborted && upcoming?.text === normalized && upcoming.signal === signal) {
    prepared = upcoming.request;
    upcoming.signal?.removeEventListener('abort', upcoming.abort);
    upcoming = null;
  }
  stop();
  if (signal?.aborted || !normalized) {
    const result = {status:signal?.aborted ? 'cancelled' : 'unavailable', duration:0};
    onEnd?.(result);
    return Promise.resolve(result);
  }
  return new Promise(resolve => {
    const job = {request:prepared || newRequest(), sources:new Set(), nextTime:0, resolve,
      onStart, onDuration, onEnd, nextText, signal, finished:false, started:false,
      abort:() => {if (active === job) stop();}};
    active = job;
    signal?.addEventListener('abort', job.abort, {once:true});
    job.timer = setTimeout(() => {
      cancelRequest(job.request);
      finish(job, job.started ? 'interrupted' : 'unavailable');
    }, 275000);
    void play(job, normalized, Boolean(prepared));
  });
}

window.addEventListener('pagehide', stop);
window.doujieSpeech = {say, stop, unlock, level, prepareNext, get state() {return playbackState;}};
