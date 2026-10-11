'use strict';
// Team Room: live product preview, what everyone's doing, opt-in camera and push-to-talk.
// Video/voice is a WebRTC mesh between teammates' browsers (teams are small). The server only relays
// offers/answers through /room/heartbeat + /room/signal; ICE candidates ride inside the SDP (no trickle).
// Transcripts: while you hold to talk, *your own* browser's speech recognition turns your words into text.
// Interim words ride the heartbeat as a live caption; finished phrases are saved to the team transcript.
// Loaded before app.js, so it may only touch app.js globals (api, esc, me, …) at call time.

const RTC_CONFIG = { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] };
const HEARTBEAT_MS = 1500;
const TALK_LEVEL = 0.04;
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const TRANSCRIBE_KEY = 'aoh.transcribe';

function transcribePref() {
  try { return localStorage.getItem(TRANSCRIBE_KEY) !== 'off'; } catch (e) { return true; }
}

let room = null;

const newSession = () => 's' + Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, '0')).join('');

function leaveRoom() {
  if (!room) return;
  const r = room;
  room = null;
  clearInterval(r.refreshTimer);
  clearInterval(r.beatTimer);
  clearInterval(r.meterTimer);
  window.removeEventListener('keydown', r.onKey);
  window.removeEventListener('keyup', r.onKey);
  window.removeEventListener('pagehide', r.onHide);
  document.removeEventListener('visibilitychange', r.onVisible);
  window.removeEventListener('pointerup', r.onUp);
  window.removeEventListener('pointercancel', r.onUp);
  window.removeEventListener('blur', r.onUp);
  if (r.joined) {
    for (const sess of r.peers.keys()) signalPeer(r, sess, 'bye', {}).catch(() => {});
    fetch(`/api/teams/${r.teamId}/room/leave`, {
      method: 'POST', keepalive: true, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: r.session }),
    }).catch(() => {});
  }
  for (const sess of [...r.peers.keys()]) closePeer(r, sess);
  r.pressed = false;
  stopCaptions(r);
  r.local.cam?.stop();
  r.local.mic?.stop();
  r.audioCtx?.close();
}

// ---------- WebRTC plumbing ----------

function signalPeer(r, to, kind, payload) {
  return api(`/teams/${r.teamId}/room/signal`, { session: r.session, to, kind, payload });
}

function waitForIce(pc) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') return resolve();
    const done = () => { if (pc.iceGatheringState === 'complete') resolve(); };
    pc.addEventListener('icegatheringstatechange', done);
    setTimeout(resolve, 2500); // good enough: host + srflx candidates arrive fast
  });
}

function makePeer(r, sess) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  const peer = { pc, stream: new MediaStream(), created: Date.now(), audioTx: null, videoTx: null, level: 0 };
  pc.ontrack = (e) => {
    peer.stream.addTrack(e.track);
    if (e.track.kind === 'audio') watchLevel(r, peer, e.track);
    const v = tileFor(r, sess)?.querySelector('video');
    if (v && v.srcObject !== peer.stream) { v.srcObject = peer.stream; v.play().catch(() => {}); }
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed') closePeer(r, sess); // the offerer side reconnects on the next heartbeat
    paintTiles(r);
  };
  r.peers.set(sess, peer);
  return peer;
}

function attachLocal(r, peer) {
  peer.audioTx?.sender.replaceTrack(r.local.mic || null);
  peer.videoTx?.sender.replaceTrack(r.local.cam || null);
}

function closePeer(r, sess) {
  const peer = r.peers.get(sess);
  if (!peer) return;
  peer.pc.close();
  r.peers.delete(sess);
}

async function callPeer(r, sess) {
  const peer = makePeer(r, sess);
  // Both transceivers exist from the start, so turning the camera/mic on later is a replaceTrack, not a renegotiation.
  peer.audioTx = peer.pc.addTransceiver('audio', { direction: 'sendrecv' });
  peer.videoTx = peer.pc.addTransceiver('video', { direction: 'sendrecv' });
  attachLocal(r, peer);
  await peer.pc.setLocalDescription(await peer.pc.createOffer());
  await waitForIce(peer.pc);
  if (room !== r) return;
  await signalPeer(r, sess, 'offer', { sdp: peer.pc.localDescription.sdp });
}

async function onSignal(r, s) {
  if (s.kind === 'bye') { closePeer(r, s.from); return; }
  if (s.kind === 'offer') {
    closePeer(r, s.from);
    const peer = makePeer(r, s.from);
    await peer.pc.setRemoteDescription({ type: 'offer', sdp: s.payload.sdp });
    for (const t of peer.pc.getTransceivers()) {
      t.direction = 'sendrecv';
      if (t.receiver.track.kind === 'audio') peer.audioTx = t; else peer.videoTx = t;
    }
    attachLocal(r, peer);
    await peer.pc.setLocalDescription(await peer.pc.createAnswer());
    await waitForIce(peer.pc);
    if (room !== r) return;
    await signalPeer(r, s.from, 'answer', { sdp: peer.pc.localDescription.sdp });
  } else if (s.kind === 'answer') {
    const peer = r.peers.get(s.from);
    if (peer && peer.pc.signalingState === 'have-local-offer') await peer.pc.setRemoteDescription({ type: 'answer', sdp: s.payload.sdp });
  }
}

async function heartbeat(r) {
  if (r.beating || room !== r) return;
  r.beating = true;
  try {
    const res = await api(`/teams/${r.teamId}/room/heartbeat`,
      { session: r.session, cam: !!r.local.cam, talking: r.local.talking, since: r.since,
        caption: r.caption.slice(-200), transcript_since: r.lines.at(-1)?.id || 0 });
    if (room !== r) return;
    addLines(r, res.transcript);
    for (const s of res.signals) {
      r.since = Math.max(r.since, s.id);
      await onSignal(r, s).catch((e) => console.warn('signal failed', e));
    }
    r.participants = res.participants;
    const present = new Set(res.participants.map((p) => p.session));
    for (const sess of [...r.peers.keys()]) if (!present.has(sess)) closePeer(r, sess);
    for (const p of res.participants) {
      if (p.session === r.session) continue;
      const peer = r.peers.get(p.session);
      // Lower session id offers; retry if a connection never came up.
      const stuck = peer && peer.pc.connectionState !== 'connected' && Date.now() - peer.created > 15000;
      if (stuck) closePeer(r, p.session);
      if ((!peer || stuck) && r.session < p.session) callPeer(r, p.session).catch((e) => console.warn('call failed', e));
    }
    paintTiles(r);
  } catch (e) {
    if (e.status === 403) { toast(e.message, true); leaveRoom(); }
  } finally {
    r.beating = false;
  }
}

// ---------- local media ----------

function mediaError(e) {
  if (!navigator.mediaDevices) return 'Camera and mic need HTTPS (or localhost) — open the site over https.';
  if (e && e.name === 'NotAllowedError') return 'Permission denied — allow camera/mic in your browser’s site settings.';
  if (e && e.name === 'NotFoundError') return 'No camera or microphone found.';
  return 'Couldn’t start camera/mic: ' + (e?.message || e);
}

async function toggleCamera(r) {
  if (r.local.cam) {
    r.local.cam.stop();
    r.local.cam = null;
  } else {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 360 } });
      r.local.cam = s.getVideoTracks()[0];
    } catch (e) { toast(mediaError(e), true); return; }
  }
  for (const peer of r.peers.values()) attachLocal(r, peer);
  const v = tileFor(r, r.session)?.querySelector('video');
  if (v) v.srcObject = r.local.cam ? new MediaStream([r.local.cam]) : null;
  paintControls(r);
  heartbeat(r);
}

async function setTalking(r, on) {
  r.pressed = on;
  if (on && !r.local.mic) {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (room !== r) { s.getTracks().forEach((t) => t.stop()); return; }
      r.local.mic = s.getAudioTracks()[0];
      for (const peer of r.peers.values()) attachLocal(r, peer);
    } catch (e) { r.pressed = false; toast(mediaError(e), true); return; }
  }
  // The mic track stays attached to every connection; holding the button just un-mutes it.
  if (r.local.mic) r.local.mic.enabled = r.pressed;
  if (r.local.talking !== r.pressed) {
    r.local.talking = r.pressed;
    if (r.pressed) startCaptions(r); else stopCaptions(r);
    paintControls(r);
    paintTiles(r);
    heartbeat(r);
  }
}

// ---------- transcription ----------

function startCaptions(r) {
  if (!SpeechRec || !r.transcribe || r.rec) return;
  const rec = new SpeechRec();
  rec.lang = navigator.language || 'en-US';
  rec.continuous = true;
  rec.interimResults = true;
  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) postLine(r, res[0].transcript);
      else interim += res[0].transcript;
    }
    r.caption = interim.trim();
    paintCaptions(r);
  };
  rec.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      r.transcribe = false;
      paintControls(r);
      toast('Speech-to-text was blocked — transcript is off for you', true);
    } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
      console.warn('speech recognition', e.error);
    }
  };
  rec.onend = () => {
    // Words still in flight when you let go are kept rather than dropped.
    if (r.caption) postLine(r, r.caption);
    r.caption = '';
    r.rec = null;
    paintCaptions(r);
    // Recognition stops itself after a pause; keep going while the button is still held.
    if (room === r && r.pressed && r.transcribe) startCaptions(r);
  };
  try { rec.start(); r.rec = rec; } catch (e) { console.warn('speech recognition', e); }
}

function stopCaptions(r) {
  r.rec?.stop(); // onend flushes the last words
}

function postLine(r, words) {
  const textLine = words.trim();
  if (!textLine || room !== r) return;
  api(`/teams/${r.teamId}/transcript`, { text: textLine })
    .then((res) => addLines(r, [res.line]))
    .catch((e) => toast(e.message, true));
}

function addLines(r, lines) {
  const fresh = (lines || []).filter((l) => !r.lines.some((x) => x.id === l.id));
  if (!fresh.length) return;
  r.lines = [...r.lines, ...fresh].sort((a, b) => a.id - b.id).slice(-300);
  paintTranscript(r);
}

function watchLevel(r, peer, track) {
  try {
    r.audioCtx = r.audioCtx || new AudioContext();
    const src = r.audioCtx.createMediaStreamSource(new MediaStream([track]));
    const an = r.audioCtx.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    peer.analyser = an;
  } catch (e) { /* level meter is a nicety */ }
}

function meterLoop(r) {
  const buf = new Float32Array(512);
  // A timer, not requestAnimationFrame: rAF stops in background tabs, and people code with the room tab hidden.
  const tick = () => {
    if (room !== r) return;
    let changed = false;
    for (const [sess, peer] of r.peers) {
      if (peer.analyser) {
        peer.analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (const x of buf) sum += x * x;
        const loud = Math.sqrt(sum / buf.length) > TALK_LEVEL;
        if (loud !== peer.loud) { peer.loud = loud; changed = true; }
      }
      const tile = tileFor(r, sess);
      if (tile) tile.classList.toggle('talking', !!peer.loud || !!r.participants.find((p) => p.session === sess)?.talking);
    }
    if (changed) paintTalkers(r);
  };
  r.meterTimer = setInterval(tick, 100);
}

// ---------- rendering ----------

function tileFor(r, sess) {
  return document.querySelector(`#tiles [data-session="${CSS.escape(sess)}"]`);
}

function paintTiles(r) {
  const box = document.getElementById('tiles');
  if (!box || room !== r) return;
  const people = r.members;
  const list = r.joined ? r.participants : [];
  if (!r.joined) {
    box.innerHTML = `<div class="tiles-empty">${r.members.filter((m) => m.where === 'room').map((m) => avatar(m, 'lg')).join('') || ''}
      <p class="small muted">${r.members.filter((m) => m.where === 'room').length ? 'Teammates are in the call.' : 'Nobody is in the call yet.'}</p></div>`;
    return;
  }
  box.querySelector('.tiles-empty')?.remove();
  const wanted = new Set(list.map((p) => p.session));
  box.querySelectorAll('[data-session]').forEach((el) => { if (!wanted.has(el.dataset.session)) el.remove(); });
  for (const p of list) {
    const u = people.find((m) => m.id === p.user_id) || { name: '?', handle: '?' };
    const mine = p.session === r.session;
    let tile = tileFor(r, p.session);
    if (!tile) {
      tile = document.createElement('div');
      tile.className = 'tile';
      tile.dataset.session = p.session;
      tile.innerHTML = `<video autoplay playsinline ${mine ? 'muted' : ''}></video><div class="tile-face">${avatar(u, 'lg')}</div>
        <div class="tile-caption" hidden></div>
        <div class="tile-label"><span class="tile-name">${esc(u.name)}${mine ? ' (you)' : ''}</span><span class="tile-state"></span></div>`;
      box.append(tile);
      const v = tile.querySelector('video');
      if (mine && r.local.cam) v.srcObject = new MediaStream([r.local.cam]);
      const peer = r.peers.get(p.session);
      if (!mine && peer) { v.srcObject = peer.stream; v.play().catch(() => {}); }
    }
    const cam = mine ? !!r.local.cam : p.cam;
    const peer = r.peers.get(p.session);
    tile.classList.toggle('cam-on', cam);
    if (mine) tile.classList.toggle('talking', r.local.talking);
    const state = mine ? '' : !peer ? 'connecting…' : peer.pc.connectionState === 'connected' ? '' : peer.pc.connectionState + '…';
    tile.querySelector('.tile-state').textContent = state;
  }
  paintTalkers(r);
  paintCaptions(r);
}

function paintCaptions(r) {
  if (room !== r) return;
  const live = [];
  for (const p of r.participants) {
    const mine = p.session === r.session;
    const words = mine ? r.caption : p.caption;
    const cap = tileFor(r, p.session)?.querySelector('.tile-caption');
    if (cap) { cap.textContent = words; cap.hidden = !words; }
    if (words) live.push({ name: mine ? 'You' : r.members.find((m) => m.id === p.user_id)?.name || 'Someone', words });
  }
  if (!r.participants.length && r.caption) live.push({ name: 'You', words: r.caption });
  const el = document.getElementById('live-caption');
  if (el) el.innerHTML = live.map((l) => `<div><b>${esc(l.name)}</b> <span class="muted">${esc(l.words)}…</span></div>`).join('');
}

function paintTranscript(r) {
  const box = document.getElementById('transcript-lines');
  if (!box || room !== r) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  box.innerHTML = r.lines.length ? r.lines.map((l) => `<div class="tline${l.user_id === me.id ? ' mine' : ''}">
      <span class="muted mono">${time(l.created_at)}</span> <b>${esc(l.name)}</b> ${esc(l.text)}</div>`).join('')
    : `<p class="small muted" style="margin:0">${SpeechRec ? 'Hold to talk and your words show up here for the whole team.'
      : 'This browser can’t do speech-to-text (try Chrome, Edge or Safari) — teammates’ lines still show up here.'}</p>`;
  if (nearBottom) box.scrollTop = box.scrollHeight;
}

function downloadTranscript(r, teamName) {
  const stamp = (ts) => new Date(ts * 1000).toLocaleString();
  const body = r.lines.map((l) => `[${stamp(l.created_at)}] ${l.name} (@${l.handle}): ${l.text}`).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([`${teamName} — call transcript\n\n${body}\n`], { type: 'text/plain' }));
  a.download = `${teamName.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-transcript.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function paintTalkers(r) {
  const el = document.getElementById('talkers');
  if (!el) return;
  const names = [];
  if (r.local.talking) names.push('You');
  for (const p of r.participants) {
    if (p.session === r.session) continue;
    const peer = r.peers.get(p.session);
    if (p.talking || peer?.loud) names.push(r.members.find((m) => m.id === p.user_id)?.name.split(' ')[0] || 'Someone');
  }
  el.textContent = names.length ? `🔊 ${names.join(', ')} ${names.length > 1 || names[0] === 'You' ? 'are' : 'is'} talking` : '';
}

function paintControls(r) {
  const el = document.getElementById('call-controls');
  if (!el) return;
  if (!r.joined) {
    el.innerHTML = `<button class="btn" data-room="join">🎧 Join the call</button>
      <p class="small muted" style="margin:6px 0 0">Camera stays off until you turn it on. Video and voice go straight to your teammates’ browsers and are never recorded.
      If transcription is on, what you say is saved as text for your team.</p>`;
    return;
  }
  el.innerHTML = `<div class="row">
    <button class="btn ptt ${r.local.talking ? 'on' : ''}" data-room="talk" aria-pressed="${r.local.talking}">🎙 ${r.local.talking ? 'Talking…' : 'Hold to talk'}</button>
    <button class="btn ghost ${r.local.cam ? 'on' : ''}" data-room="cam">📷 Camera ${r.local.cam ? 'on' : 'off'}</button>
    <button class="btn ghost ${r.transcribe ? 'on' : ''}" data-room="transcribe" ${SpeechRec ? '' : 'disabled title="Speech-to-text needs Chrome, Edge or Safari"'}>📝 Transcribe me: ${SpeechRec ? (r.transcribe ? 'on' : 'off') : 'n/a'}</button>
    <button class="btn danger" data-room="leave">Leave call</button></div>
    <p class="small muted" style="margin:6px 0 0">Hold the button or the <kbd>Space</kbd> bar — everyone in the call hears you while it’s held${r.transcribe && SpeechRec ? ', and your words are transcribed' : ''}.</p>`;
}

function previewFrame(url) {
  if (!url) {
    return `<div class="frame-empty"><b>No preview yet</b><span class="small muted">Paste your deploy URL (Vercel, Netlify, Replit, a tunnel…) above — teammates see every update.</span></div>`;
  }
  let sameOrigin = false;
  try { sameOrigin = new URL(url).origin === location.origin; } catch (e) { /* invalid URLs are rejected server-side */ }
  const sandbox = 'allow-scripts allow-forms allow-popups allow-modals' + (sameOrigin ? '' : ' allow-same-origin');
  return `<iframe src="${esc(url)}" sandbox="${sandbox}" referrerpolicy="no-referrer" title="Product preview"></iframe>`;
}

function doingPanel(d) {
  const label = { room: 'in the room', floor: 'on the Floor', away: 'away' };
  const mine = d.members.find((m) => m.id === me.id);
  return `<form class="row" id="doing-form" style="margin-bottom:14px;flex-wrap:nowrap">
      <input name="doing" maxlength="140" value="${esc(mine?.doing)}" placeholder="What are you on right now?" style="margin:0">
      <button class="btn" type="submit">Set</button></form>
    <div class="stack">${d.members.map((m) => `<div class="person"><span class="presence ${m.where}" title="${label[m.where]}"></span>${avatar(m)}
      <div class="who"><div><b>${esc(m.name)}</b> <span class="small muted">· ${label[m.where]}</span></div>
      <div class="small">${m.doing ? esc(m.doing) : '<span class="muted">No status yet</span>'}${m.doing_at ? ` <span class="muted">· ${ago(m.doing_at)}</span>` : ''}</div></div></div>`).join('')}</div>`;
}

function timelinePanel(d) {
  return d.log.length ? `<div class="timeline">${d.log.map((x) => `<div class="small"><b>@${esc(x.user.handle)}</b> ${esc(x.text)} <span class="muted">· ${ago(x.created_at)}</span></div>`).join('')}</div>`
    : '<p class="small muted" style="margin:0">Status changes and new builds show up here.</p>';
}

function previewMeta(p) {
  return p.url ? `Pushed by @${esc(p.by)} ${ago(p.at)} · blank? Some sites refuse to be embedded — use ↗` : '';
}

async function viewRoom(id) {
  if (!me) { location.hash = '#/join'; return ''; }
  const d = await api(`/teams/${id}/room`);
  const t = d.team;
  const html = `<div class="row spread"><div><div class="row small muted"><a href="#/t/${t.id}">← ${esc(t.name)}</a>${pill(t.challenge_status)}
      <span>${esc(t.challenge_title)}</span></div><h1 style="margin:6px 0 0">${esc(t.name)} · Team Room</h1></div>
      <span class="small muted">Private to the ${d.members.length} of you</span></div>
    <div class="room-grid section" style="margin-top:18px">
      <section class="card browser">
        <form class="urlbar" id="preview-form"><span class="lights"><i></i><i></i><i></i></span>
          <input name="url" type="url" value="${esc(d.preview.url)}" placeholder="https://your-app.vercel.app">
          <button class="btn sm" type="submit">Load for team</button>
          <button class="btn sm ghost" type="button" data-room="reload" title="Reload">↻</button>
          <a class="btn sm ghost" id="preview-open" href="${esc(d.preview.url || '#')}" target="_blank" rel="noopener" title="Open in new tab">↗</a></form>
        <div class="frame" id="frame">${previewFrame(d.preview.url)}</div>
        <div class="small muted" id="preview-meta" style="padding:8px 12px">${previewMeta(d.preview)}</div>
      </section>
      <section class="card call"><div class="row spread"><h3 style="margin:0">Call</h3><span class="small" id="talkers"></span></div>
        <div class="tiles" id="tiles"></div><div id="call-controls"></div></section>
    </div>
    <section class="card section transcript">
      <div class="row spread"><h3 style="margin:0">Transcript</h3><div class="row">
        <button class="btn sm ghost" type="button" data-tx="download">Download .txt</button>
        <button class="btn sm danger" type="button" data-tx="clear">Clear</button></div></div>
      <div id="transcript-lines" class="tlines"></div>
      <div id="live-caption" class="live-caption small"></div>
    </section>
    <div class="grid two section">
      <div class="card"><h3>What everyone's doing</h3><div id="doing">${doingPanel(d)}</div></div>
      <div class="card"><h3>Team timeline</h3><div id="timeline">${timelinePanel(d)}</div></div>
    </div>`;

  return [html, () => {
    const r = room = {
      teamId: t.id, session: newSession(), joined: false, members: d.members, participants: [],
      peers: new Map(), local: { cam: null, mic: null, talking: false }, since: 0, pressed: false,
      previewUrl: d.preview.url, caption: '', lines: [], rec: null, transcribe: !!SpeechRec && transcribePref(),
    };
    paintTiles(r);
    paintControls(r);
    addLines(r, d.transcript);
    paintTranscript(r);
    document.querySelector('.transcript').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-tx]');
      if (!b) return;
      if (b.dataset.tx === 'download') {
        if (!r.lines.length) { toast('Nothing to download yet'); return; }
        downloadTranscript(r, t.name);
      } else if (confirm('Clear the call transcript for the whole team? This can’t be undone.')) {
        try { await api(`/teams/${t.id}/transcript/clear`, {}); r.lines = []; paintTranscript(r); toast('Transcript cleared'); refresh(); }
        catch (err) { toast(err.message, true); }
      }
    });

    const setPanel = (elId, html) => {
      const el = document.getElementById(elId);
      if (el && el.dataset.html !== html && !el.contains(document.activeElement)) { el.innerHTML = html; el.dataset.html = html; bindDoing(); }
    };
    const loadPreview = (url) => {
      r.previewUrl = url;
      document.getElementById('frame').innerHTML = previewFrame(url);
      document.getElementById('preview-open').href = url || '#';
    };
    const bindDoing = () => {
      const f = document.getElementById('doing-form');
      if (!f || f.dataset.bound) return;
      f.dataset.bound = '1';
      f.onsubmit = async (e) => {
        e.preventDefault();
        try { await api(`/teams/${t.id}/doing`, { doing: f.doing.value }); f.doing.blur(); toast('Status set'); refresh(); } catch (err) { toast(err.message, true); }
      };
    };
    const refresh = async () => {
      r.lastRefresh = Date.now();
      const next = await api(`/teams/${t.id}/room`);
      if (room !== r) return;
      r.members = next.members;
      setPanel('doing', doingPanel(next));
      setPanel('timeline', timelinePanel(next));
      // The full list is authoritative (it reflects a teammate clearing the transcript).
      const ids = (xs) => xs.map((x) => x.id).join(',');
      if (ids(next.transcript) !== ids(r.lines.slice(-next.transcript.length))) { r.lines = []; addLines(r, next.transcript); paintTranscript(r); }
      document.getElementById('preview-meta').innerHTML = previewMeta(next.preview);
      if (next.preview.url !== r.previewUrl) {
        loadPreview(next.preview.url);
        const input = document.querySelector('#preview-form [name=url]');
        if (input !== document.activeElement) input.value = next.preview.url;
        if (next.preview.by !== me.handle) toast(`@${next.preview.by} pushed a new build — reloaded`);
      }
      if (!r.joined) paintTiles(r);
    };
    document.getElementById('doing').dataset.html = doingPanel(d);
    document.getElementById('timeline').dataset.html = timelinePanel(d);
    bindDoing();
    // Every 5s while visible, every 30s in a background tab, and immediately when you switch back.
    r.lastRefresh = Date.now();
    r.refreshTimer = setInterval(() => {
      if (!document.hidden || Date.now() - r.lastRefresh > 30000) refresh().catch(() => {});
    }, 5000);
    r.onVisible = () => { if (!document.hidden) refresh().catch(() => {}); };
    document.addEventListener('visibilitychange', r.onVisible);

    document.getElementById('preview-form').onsubmit = async (e) => {
      e.preventDefault();
      const url = e.target.url.value.trim();
      try {
        await api(`/teams/${t.id}/preview`, { url });
        loadPreview(url);
        toast(url ? 'Loaded for the whole team 🚀' : 'Preview cleared');
        refresh();
      } catch (err) { toast(err.message, true); }
    };

    // Call controls: delegated, with press-and-hold for push-to-talk.
    const controls = document.getElementById('call-controls');
    const browser = document.querySelector('.browser');
    browser.addEventListener('click', (e) => {
      if (e.target.closest('[data-room=reload]')) loadPreview(r.previewUrl);
    });
    controls.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-room]');
      if (!b) return;
      if (b.dataset.room === 'join') {
        r.joined = true;
        r.audioCtx = new AudioContext(); // created inside the click so remote audio may autoplay
        meterLoop(r);
        paintControls(r);
        await heartbeat(r);
        r.beatTimer = setInterval(() => heartbeat(r), HEARTBEAT_MS);
      } else if (b.dataset.room === 'cam') {
        toggleCamera(r);
      } else if (b.dataset.room === 'transcribe') {
        r.transcribe = !r.transcribe;
        try { localStorage.setItem(TRANSCRIBE_KEY, r.transcribe ? 'on' : 'off'); } catch (err) { /* preference just won't stick */ }
        if (!r.transcribe) stopCaptions(r); else if (r.pressed) startCaptions(r);
        paintControls(r);
        toast(r.transcribe ? 'Your words will be transcribed for the team' : 'Transcription off — your voice still reaches the call');
      } else if (b.dataset.room === 'leave') {
        const tid = r.teamId;
        leaveRoom();
        toast('Left the call');
        location.hash = `#/t/${tid}/room`;
        render();
      }
    });
    controls.addEventListener('pointerdown', (e) => {
      if (!e.target.closest('[data-room=talk]')) return;
      e.preventDefault();
      setTalking(r, true);
    });
    // Any way the hold can end must cut the mic: release anywhere, a cancelled touch, or switching windows.
    r.onUp = () => { if (r.pressed) setTalking(r, false); };
    window.addEventListener('pointerup', r.onUp);
    window.addEventListener('pointercancel', r.onUp);
    window.addEventListener('blur', r.onUp);
    r.onKey = (e) => {
      if (!r.joined || e.code !== 'Space' || e.repeat) return;
      if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(document.activeElement?.tagName)) return;
      e.preventDefault();
      setTalking(r, e.type === 'keydown');
    };
    window.addEventListener('keydown', r.onKey);
    window.addEventListener('keyup', r.onKey);
    r.onHide = () => leaveRoom();
    window.addEventListener('pagehide', r.onHide);
  }];
}
