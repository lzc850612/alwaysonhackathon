'use strict';
// Demo Stage: a shipped team presents live inside the app — screen share, camera, mic — to an audience
// that reacts and asks questions. Media is WebRTC: every presenter sends directly to every viewer
// (sendonly) and presenters see/hear each other (sendrecv). The server only relays offers/answers.
// Each connection carries three transceivers in a fixed order — audio, screen, camera — so turning
// any of them on later is a replaceTrack, never a renegotiation. Reuses waitForIce/mediaError from room.js.

const STAGE_BEAT_MS = 1500;
const TX = { audio: 0, screen: 1, cam: 2 };
let stage = null;

function leaveStage() {
  if (!stage) return;
  const s = stage;
  stage = null;
  clearTimeout(s.stateTimer);
  clearInterval(s.beatTimer);
  window.removeEventListener('pagehide', s.onHide);
  if (s.joined) {
    for (const sess of s.peers.keys()) stageSignal(s, sess, 'bye', {}).catch(() => {});
    fetch(`/api/teams/${s.teamId}/stage/leave`, {
      method: 'POST', keepalive: true, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session: s.session }),
    }).catch(() => {});
  }
  for (const sess of [...s.peers.keys()]) closeStagePeer(s, sess);
  for (const t of Object.values(s.local)) if (t && t.stop) t.stop();
}

// ---------- connections ----------

function stageSignal(s, to, kind, payload) {
  return api(`/teams/${s.teamId}/stage/signal`, { session: s.session, to, kind, payload });
}

function newStagePeer(s, sess) {
  const pc = new RTCPeerConnection(RTC_CONFIG);
  const peer = { pc, created: Date.now(), tx: [], screen: new MediaStream(), cam: new MediaStream(), audio: null };
  pc.ontrack = (e) => {
    const idx = pc.getTransceivers().indexOf(e.transceiver);
    if (idx === TX.audio) {
      peer.audio = document.createElement('audio');
      peer.audio.autoplay = true;
      peer.audio.srcObject = new MediaStream([e.track]);
      document.getElementById('stage-audio')?.append(peer.audio);
      peer.audio.play().catch(() => {});
    } else {
      (idx === TX.screen ? peer.screen : peer.cam).addTrack(e.track);
    }
    paintStageMedia(s);
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed') closeStagePeer(s, sess);
    paintStageMedia(s);
  };
  s.peers.set(sess, peer);
  return peer;
}

function attachStageLocal(s, peer) {
  if (!s.presenter) return;
  peer.tx[TX.audio]?.sender.replaceTrack(s.local.mic || null);
  peer.tx[TX.screen]?.sender.replaceTrack(s.local.screen || null);
  peer.tx[TX.cam]?.sender.replaceTrack(s.local.cam || null);
}

function closeStagePeer(s, sess) {
  const peer = s.peers.get(sess);
  if (!peer) return;
  peer.pc.close();
  peer.audio?.remove();
  s.peers.delete(sess);
}

async function callStagePeer(s, sess, role) {
  const peer = newStagePeer(s, sess);
  // To a viewer we only send; with a co-presenter we send and receive.
  const direction = role === 'viewer' ? 'sendonly' : 'sendrecv';
  peer.tx = ['audio', 'video', 'video'].map((kind) => peer.pc.addTransceiver(kind, { direction }));
  attachStageLocal(s, peer);
  await peer.pc.setLocalDescription(await peer.pc.createOffer());
  await waitForIce(peer.pc);
  if (stage !== s) return;
  await stageSignal(s, sess, 'offer', { sdp: peer.pc.localDescription.sdp });
}

async function onStageSignal(s, sig) {
  if (sig.kind === 'bye') { closeStagePeer(s, sig.from); return; }
  if (sig.kind === 'offer') {
    closeStagePeer(s, sig.from);
    const peer = newStagePeer(s, sig.from);
    await peer.pc.setRemoteDescription({ type: 'offer', sdp: sig.payload.sdp });
    peer.tx = peer.pc.getTransceivers();
    for (const t of peer.tx) t.direction = s.presenter ? 'sendrecv' : 'recvonly';
    attachStageLocal(s, peer);
    await peer.pc.setLocalDescription(await peer.pc.createAnswer());
    await waitForIce(peer.pc);
    if (stage !== s) return;
    await stageSignal(s, sig.from, 'answer', { sdp: peer.pc.localDescription.sdp });
  } else if (sig.kind === 'answer') {
    const peer = s.peers.get(sig.from);
    if (peer && peer.pc.signalingState === 'have-local-offer') await peer.pc.setRemoteDescription({ type: 'answer', sdp: sig.payload.sdp });
  }
}

async function stageBeat(s) {
  if (s.beating || stage !== s) return;
  s.beating = true;
  try {
    const hb = await api(`/teams/${s.teamId}/stage/heartbeat`, {
      session: s.session, since: s.since, screen: !!s.local.screen, cam: !!s.local.cam, mic: !!(s.local.mic && s.local.mic.enabled),
    });
    if (stage !== s) return;
    s.full = !!hb.full;
    for (const sig of hb.signals) {
      s.since = Math.max(s.since, sig.id);
      await onStageSignal(s, sig).catch((e) => console.warn('stage signal', e));
    }
    s.participants = hb.participants;
    const present = new Set(hb.participants.map((p) => p.session));
    for (const sess of [...s.peers.keys()]) if (!present.has(sess) || (!hb.live && !s.presenter)) closeStagePeer(s, sess);
    if (s.presenter) {
      for (const p of hb.participants) {
        if (p.session === s.session) continue;
        if (p.role === 'viewer' && !hb.live) continue;
        const peer = s.peers.get(p.session);
        const stuck = peer && peer.pc.connectionState !== 'connected' && Date.now() - peer.created > 15000;
        if (stuck) closeStagePeer(s, p.session);
        // Presenters always call viewers; between presenters the lower session id calls.
        const mine = p.role === 'viewer' || s.session < p.session;
        if ((!peer || stuck) && mine) callStagePeer(s, p.session, p.role).catch((e) => console.warn('stage call', e));
      }
    }
    paintStageMedia(s);
  } catch (e) {
    if (e.status === 403 || e.status === 401) { toast(e.message, true); leaveStage(); }
  } finally {
    s.beating = false;
  }
}

function joinStage(s) {
  if (s.joined) return;
  s.joined = true; // joining happens inside a click, so remote audio is allowed to autoplay
  stageBeat(s);
  s.beatTimer = setInterval(() => stageBeat(s), STAGE_BEAT_MS);
  paintStageControls(s);
}

// ---------- presenter media ----------

async function toggleScreen(s) {
  if (s.local.screen) {
    s.local.screen.stop();
    s.local.screen = null;
  } else {
    if (!navigator.mediaDevices?.getDisplayMedia) { toast('Screen sharing needs a desktop browser over HTTPS (or localhost)', true); return; }
    try {
      const st = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 15 }, audio: false });
      s.local.screen = st.getVideoTracks()[0];
      s.local.screen.contentHint = 'detail'; // keep text sharp rather than smooth
      // The browser's own "Stop sharing" bar ends the track; follow it.
      s.local.screen.onended = () => { if (stage === s && s.local.screen) { s.local.screen = null; refreshStageMedia(s); } };
    } catch (e) {
      if (e.name !== 'NotAllowedError') toast(mediaError(e), true);
      return;
    }
  }
  refreshStageMedia(s);
}

async function toggleStageCam(s) {
  if (s.local.cam) {
    s.local.cam.stop();
    s.local.cam = null;
  } else {
    try {
      s.local.cam = (await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } })).getVideoTracks()[0];
    } catch (e) { toast(mediaError(e), true); return; }
  }
  refreshStageMedia(s);
}

async function toggleStageMic(s) {
  if (!s.local.mic) {
    try {
      s.local.mic = (await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })).getAudioTracks()[0];
    } catch (e) { toast(mediaError(e), true); return; }
  } else {
    s.local.mic.enabled = !s.local.mic.enabled;
  }
  refreshStageMedia(s);
}

function refreshStageMedia(s) {
  for (const peer of s.peers.values()) attachStageLocal(s, peer);
  paintStageControls(s);
  paintStageMedia(s);
  stageBeat(s);
}

// ---------- rendering ----------

function presenterName(s, p) {
  return s.state.presenters.find((x) => x.user.id === p.user_id)?.user.name
    || s.state.team.members.find((m) => m.id === p.user_id)?.name || 'Presenter';
}

// Point a <video> at one track, touching it only when the track actually changes (so playback never restarts).
function showTrack(el, track) {
  if (!el) return;
  const current = el.srcObject?.getVideoTracks()[0] || null;
  if (current === (track || null)) return;
  el.srcObject = track ? new MediaStream([track]) : null;
  if (track) el.play().catch(() => {});
}

function paintStageMedia(s) {
  if (stage !== s) return;
  const main = document.getElementById('stage-main');
  const cams = document.getElementById('stage-cams');
  if (!main || !cams) return;
  const presenters = (s.participants || []).filter((p) => p.role === 'presenter');
  // Main screen: my own share (presenters see their preview), else the presenter who's sharing.
  let screen = null;
  let who = '';
  if (s.local.screen) { screen = s.local.screen; who = 'You'; }
  else {
    const sharer = presenters.find((p) => p.screen && p.session !== s.session && s.peers.get(p.session)?.screen.getVideoTracks().length);
    if (sharer) { screen = s.peers.get(sharer.session).screen.getVideoTracks()[0]; who = presenterName(s, sharer); }
  }
  showTrack(main.querySelector('video'), screen);
  main.classList.toggle('has-screen', !!screen);
  main.querySelector('.stage-who').textContent = screen ? `🖥 ${who === 'You' ? 'You are' : `${who} is`} sharing` : '';

  // Camera strip: one tile per presenter (only once you've joined; before that, avatars of the team).
  const list = s.joined ? presenters : [];
  const wanted = new Set(list.map((p) => p.session));
  cams.querySelectorAll('[data-session]').forEach((el) => { if (!wanted.has(el.dataset.session)) el.remove(); });
  for (const p of list) {
    const mine = p.session === s.session;
    let tile = cams.querySelector(`[data-session="${CSS.escape(p.session)}"]`);
    const user = s.state.team.members.find((m) => m.id === p.user_id) || { name: '?', handle: '?' };
    if (!tile) {
      tile = document.createElement('div');
      tile.className = 'tile cam-tile';
      tile.dataset.session = p.session;
      tile.innerHTML = `<video autoplay playsinline muted></video><div class="tile-face">${avatar(user, 'lg')}</div>
        <div class="tile-label"><span class="tile-name">${esc(user.name)}${mine ? ' (you)' : ''}</span><span class="tile-state"></span></div>`;
      cams.append(tile);
    }
    const peer = s.peers.get(p.session);
    const camOn = mine ? !!s.local.cam : p.cam && !!peer?.cam.getVideoTracks().length;
    showTrack(tile.querySelector('video'), !camOn ? null : mine ? s.local.cam : peer.cam.getVideoTracks()[0]);
    tile.classList.toggle('cam-on', camOn);
    const micOn = mine ? !!(s.local.mic && s.local.mic.enabled) : p.mic;
    const conn = mine || !peer ? '' : peer.pc.connectionState === 'connected' ? '' : `${peer.pc.connectionState}…`;
    tile.querySelector('.tile-state').textContent = conn || (micOn ? '🎙' : '🔇');
  }
  const waiting = document.getElementById('stage-waiting');
  if (waiting) waiting.hidden = !!screen || list.some((p) => p.cam);
}

function paintStageControls(s) {
  const el = document.getElementById('stage-controls');
  if (!el) return;
  const st = s.state;
  if (s.presenter) {
    if (st.team.status !== 'shipped') {
      el.innerHTML = `<p class="small muted" style="margin:0">Finish the project in your <a href="#/t/${st.team.id}/room">Team Room</a> to open the stage.</p>`;
      return;
    }
    if (!s.joined) {
      el.innerHTML = `<button class="btn" data-stage="join">🎬 Set up the stage</button>
        <span class="small muted">Share your screen and test your mic before you go live — no one sees anything until you do.</span>`;
      return;
    }
    const micOn = !!(s.local.mic && s.local.mic.enabled);
    el.innerHTML = `<div class="row">
        <button class="btn ${s.local.screen ? 'on-air' : ''}" data-stage="screen">🖥 ${s.local.screen ? 'Stop sharing' : 'Share screen'}</button>
        <button class="btn ghost ${s.local.cam ? 'on' : ''}" data-stage="cam">📷 Camera ${s.local.cam ? 'on' : 'off'}</button>
        <button class="btn ghost ${micOn ? 'on' : ''}" data-stage="mic">${micOn ? '🎙 Mic on' : '🔇 Mic off'}</button>
        <span style="flex:1"></span>
        ${st.live ? '<button class="btn danger" data-stage="end">■ End demo</button>'
          : '<button class="btn live-btn" data-stage="live">🔴 Go live</button>'}</div>
      <p class="small muted" style="margin:6px 0 0">${st.live ? `You're live — ${st.viewers} watching. Your mic stays on while you present; mute it any time.`
        : 'Set things up, then Go live — everyone gets a notification and can watch here.'}</p>`;
  } else if (s.full) {
    el.innerHTML = '<p class="small" style="margin:0">The stage is full right now (30 viewers). Try again in a bit.</p>';
  } else if (st.live && !s.joined) {
    el.innerHTML = '<button class="btn live-btn" data-stage="join">▶ Watch live</button><span class="small muted">You’ll hear the presenters.</span>';
  } else if (st.live) {
    el.innerHTML = `<p class="small muted" style="margin:0">You're watching live with ${st.viewers - 1 > 0 ? `${st.viewers - 1} others` : 'the team'}.</p>`;
  } else {
    el.innerHTML = '';
  }
}

function stageHeader(st) {
  const t = st.team;
  const d = st.demo;
  const status = st.live ? `<span class="pill live">Live</span> <b>${st.viewers}</b> watching`
    : d ? `<span class="pill past">Ended</span> <span class="muted">${ago(d.ended_at || d.starts_at)}</span>`
      : t.status === 'shipped' ? '<span class="pill upcoming">Shipped · not live yet</span>' : '<span class="pill past">Still building</span>';
  return `<div class="row spread"><div><div class="row small muted"><a href="#/t/${t.id}">← ${esc(t.name)}</a><span>${esc(t.challenge_title)}</span></div>
      <h1 style="margin:6px 0 4px">🎬 ${esc(st.submission?.title || t.name)}</h1><div class="row small">${status}</div></div>
    <div class="avatars">${t.members.map((m) => avatar(m)).join('')}</div></div>`;
}

function stageSide(st, s) {
  const sub = st.submission;
  const canAsk = me && !st.presenter && st.live;
  const qs = st.questions;
  const summary = !st.live && st.demo ? `<div class="card"><h3 style="margin:0 0 8px">Demo recap</h3>
      <div class="stats" style="margin:0;grid-template-columns:repeat(3,1fr)"><div class="stat"><b>${st.demo.peak}</b><span>peak viewers</span></div>
      <div class="stat"><b>${Object.values(st.reactions).reduce((a, b) => a + b, 0)}</b><span>reactions</span></div>
      <div class="stat"><b>${qs.length}</b><span>questions</span></div></div>
      ${st.presenter ? '<p class="small" style="margin:10px 0 0">Next: <a href="#/live">take the stage at the Sunday Closing Ceremony →</a></p>' : ''}</div>` : '';
  return `${summary}
    ${sub ? `<div class="card"><h3 style="margin:0">${esc(sub.title)}</h3><p class="small" style="margin:6px 0">${esc(sub.description)}</p>
      <div class="row small">${sub.repo_url ? `<a href="${esc(sub.repo_url)}" target="_blank" rel="noopener">Repo ↗</a>` : ''}
      ${sub.demo_url ? `<a href="${esc(sub.demo_url)}" target="_blank" rel="noopener">Try it ↗</a>` : ''}</div></div>` : ''}
    <div class="card"><div class="row spread"><h3 style="margin:0">Questions</h3><span class="small muted">${qs.filter((q) => !q.answered).length} open</span></div>
      ${canAsk ? `<form id="ask" class="row" style="margin-top:10px;flex-wrap:nowrap"><input name="text" required maxlength="280" placeholder="Ask the team…" style="margin:0"><button class="btn" type="submit">Ask</button></form>` : ''}
      <div class="stack" style="margin-top:10px">${qs.map((q) => `<div class="question ${q.answered ? 'answered' : ''}">${avatar(q.user)}<div class="who">
        <div class="small"><b>${esc(q.user.name)}</b> <span class="muted">${ago(q.created_at)}</span></div><div>${esc(q.text)}</div>
        ${st.presenter ? `<button class="btn sm ghost" data-stage="answered" data-id="${q.id}">${q.answered ? '↺ Reopen' : '✓ Answered'}</button>` : q.answered ? '<span class="small muted">✓ answered</span>' : ''}
      </div></div>`).join('') || `<p class="small muted" style="margin:0">${st.live ? 'No questions yet.' : 'Questions open while the team is live.'}</p>`}</div></div>`;
}

async function viewStage(id) {
  const st0 = await api(`/teams/${id}/stage`);
  const html = `<div class="stage-page">
    <div id="stage-head">${stageHeader(st0)}</div>
    <div class="stage-grid section" style="margin-top:18px">
      <div class="stack">
        <div class="stage-main" id="stage-main"><video autoplay playsinline muted></video><span class="stage-who"></span>
          <div class="stage-waiting" id="stage-waiting"><b>${st0.live ? 'Waiting for the team to share their screen…' : st0.demo ? 'This demo has ended.' : 'Not live yet'}</b>
            <span class="small">${st0.live ? '' : st0.demo ? 'See the recap →' : 'You’ll get a notification when the team goes live.'}</span></div></div>
        <div class="stage-cams" id="stage-cams"></div>
        <div class="emoji-stage" id="emoji-stage"></div>
        <div id="stage-react">${stageReactBar(st0)}</div>
        <div id="stage-controls" class="card"></div>
        <div id="stage-audio" hidden></div>
      </div>
      <aside class="stack" id="stage-side">${stageSide(st0, null)}</aside>
    </div></div>`;
  return [html, () => {
    const s = stage = {
      teamId: st0.team.id, session: newSession(), presenter: st0.presenter, state: st0, joined: false,
      peers: new Map(), participants: [], since: 0, local: { screen: null, cam: null, mic: null },
      lastReactions: { ...st0.reactions },
    };
    paintStageControls(s);
    paintStageMedia(s);
    const panes = { 'stage-head': stageHeader, 'stage-side': (st) => stageSide(st, s), 'stage-react': stageReactBar };
    for (const [elId, fn] of Object.entries(panes)) document.getElementById(elId).dataset.html = fn(st0);
    const refreshState = async () => {
      clearTimeout(s.stateTimer);
      try {
        const st = await api(`/teams/${s.teamId}/stage`);
        if (stage !== s) return;
        for (const [e, n] of Object.entries(st.reactions)) {
          for (let i = 0; i < Math.min(6, n - (s.lastReactions[e] || 0)); i++) floatEmoji(e);
        }
        s.lastReactions = { ...st.reactions };
        const wasLive = s.state.live;
        s.state = st;
        for (const [elId, fn] of Object.entries(panes)) {
          const el = document.getElementById(elId);
          const h = fn(st);
          if (el && el.dataset.html !== h && !el.contains(document.activeElement)) { el.innerHTML = h; el.dataset.html = h; }
        }
        const wait = document.querySelector('#stage-waiting b');
        if (wait) wait.textContent = st.live ? 'Waiting for the team to share their screen…' : st.demo ? 'This demo has ended.' : 'Not live yet';
        if (wasLive && !st.live && !s.presenter) { toast('The demo has ended — thanks for watching!'); }
        if (!wasLive && st.live && !s.presenter && !s.joined) toast('They’re live — hit ▶ Watch live');
        paintStageControls(s);
      } catch (e) { /* transient */ }
      if (stage === s) s.stateTimer = setTimeout(refreshState, document.hidden ? 10000 : 3000);
    };
    s.stateTimer = setTimeout(refreshState, 3000);

    document.querySelector('.stage-page').addEventListener('click', async (e) => {
      const r = e.target.closest('.react');
      if (r && !r.disabled) {
        floatEmoji(r.dataset.emoji);
        s.lastReactions[r.dataset.emoji] = (s.lastReactions[r.dataset.emoji] || 0) + 1;
        api(`/teams/${s.teamId}/stage/react`, { emoji: r.dataset.emoji }).catch((err) => { if (err.status !== 429) toast(err.message, true); });
        return;
      }
      const b = e.target.closest('[data-stage]');
      if (!b) return;
      try {
        const act = b.dataset.stage;
        if (act === 'join') joinStage(s);
        else if (act === 'screen') await toggleScreen(s);
        else if (act === 'cam') await toggleStageCam(s);
        else if (act === 'mic') await toggleStageMic(s);
        else if (act === 'live') {
          if (!s.local.screen && !s.local.cam && !confirm('You aren’t sharing your screen or camera yet. Go live anyway?')) return;
          await api(`/teams/${s.teamId}/stage/start`, {});
          toast('You’re live 🎬 — everyone’s been notified');
          await refreshState();
          stageBeat(s);
        } else if (act === 'end') {
          if (!confirm('End the demo for everyone?')) return;
          const r2 = await api(`/teams/${s.teamId}/stage/end`, {});
          toast(`Demo ended — ${r2.minutes} min, ${r2.peak} watching at peak, ${r2.reactions} reactions`);
          await refreshState();
        } else if (act === 'answered') {
          await api(`/teams/${s.teamId}/stage/questions/${b.dataset.id}/answered`, {});
          await refreshState();
        }
      } catch (err) { toast(err.message, true); }
    });
    document.getElementById('stage-side').addEventListener('submit', async (e) => {
      if (e.target.id !== 'ask') return;
      e.preventDefault();
      try {
        await api(`/teams/${s.teamId}/stage/questions`, { text: e.target.text.value });
        e.target.reset();
        e.target.text.blur();
        toast('Question sent');
        refreshState();
      } catch (err) { toast(err.message, true); }
    });
    s.onHide = () => leaveStage();
    window.addEventListener('pagehide', s.onHide);
  }];
}

function stageReactBar(st) {
  return `<div class="react-bar">${st.emojis.map((e) => `<button class="react" data-emoji="${e}" ${st.live && me ? '' : 'disabled'}>${e}</button>`).join('')}</div>`;
}
