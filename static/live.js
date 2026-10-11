'use strict';
// The shared clock: a bar on every page (what's live / next, your team's deadline), the weekly schedule,
// and the live ritual screens. All countdowns run on server time (see clockSkew in app.js), so everyone
// sees the same seconds. Loaded before app.js; app.js globals (api, esc, me, …) are used at call time.

let clockState = null;
let clockTimer = null;
let clockBoundary = null;
let liveTimer = null;
const RITUAL_ICON = { kickoff: '🚀', checkin: '🔔', closing: '🏆' };
const RITUAL_PRIORITY = { closing: 0, kickoff: 1, checkin: 2 };
const DAY_SECONDS = 86400;
// Most important ritual first; among the same kind, the one that started most recently.
const byPriority = (a, b) => RITUAL_PRIORITY[a.key] - RITUAL_PRIORITY[b.key] || b.starts_at - a.starts_at;

function stopLive() {
  clearTimeout(liveTimer);
  liveTimer = null;
}

// ---------- clock bar ----------

async function refreshClock() {
  try {
    const before = Date.now() / 1000;
    const c = await api('/clock');
    const after = Date.now() / 1000;
    clockSkew = c.now - (before + after) / 2; // halfway through the round trip ≈ when the server read its clock
    clockState = c;
  } catch (e) { return; }
  paintClock();
  // Re-check right as something starts or ends, so the bar flips to LIVE on the second.
  clearTimeout(clockBoundary);
  const edges = [clockState.next?.starts_at, ...clockState.live.map((o) => o.ends_at)].filter(Boolean);
  if (edges.length) {
    const wait = Math.max(1, Math.min(...edges) - nowSec() + 0.5) * 1000;
    if (wait < 6 * 3600 * 1000) clockBoundary = setTimeout(refreshClock, wait);
  }
}

function startClock() {
  refreshClock();
  clearInterval(clockTimer);
  clockTimer = setInterval(() => { if (!document.hidden) refreshClock(); }, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshClock(); });
}

function paintClock() {
  const bar = document.getElementById('clockbar');
  if (!bar || !clockState) return;
  const c = clockState;
  const live = [...c.live].sort(byPriority)[0];
  let left;
  if (live) {
    left = `<a class="clock-live" href="#/live/${live.id}"><span class="pill live">Live</span>
      <b>${RITUAL_ICON[live.key]} ${esc(live.title)}</b><span class="muted">ends in <span data-until="${live.ends_at}">${until(live.ends_at)}</span></span>
      <span class="clock-cta">Join →</span></a>`;
  } else if (c.next) {
    left = `<a href="#/live"><span class="muted">Next</span> <b>${RITUAL_ICON[c.next.key]} ${esc(c.next.title)}</b>
      <span class="muted">in</span> <span class="countdown" data-until="${c.next.starts_at}">${until(c.next.starts_at)}</span></a>`;
  } else {
    left = '<a href="#/live">Schedule</a>';
  }
  let right = '';
  if (c.deadline) {
    const left_s = c.deadline.ends_at - nowSec();
    const urgency = left_s < 3 * 3600 ? 'urgent' : left_s < DAY_SECONDS ? 'soon' : '';
    right = `<a class="deadline ${urgency}" href="#/t/${c.deadline.team_id}/room" title="${esc(c.deadline.challenge_title)}">
      ⏱ <b>${esc(c.deadline.team_name)}</b> ships in <span class="countdown" data-until="${c.deadline.ends_at}">${until(c.deadline.ends_at)}</span></a>`;
  }
  bar.innerHTML = `<div class="clock-inner">${left}<span class="clock-right">${right}<a class="muted small" href="#/live">Schedule</a></span></div>`;
  bar.classList.toggle('is-live', !!live);
}


// ---------- schedule ----------

const localTime = (ts) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
const localDay = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });

async function viewLiveHub() {
  const c = await api('/clock');
  clockState = c;
  paintClock();
  const byDay = new Map();
  for (const o of c.week) {
    const key = localDay(o.starts_at);
    if (!byDay.has(key)) byDay.set(key, []);
    byDay.get(key).push(o);
  }
  const today = localDay(nowSec());
  const live = [...c.live].sort(byPriority);
  const hero = live.length
    ? live.map((o) => `<a class="card ritual-hero live" href="#/live/${o.id}"><span class="pill live">Live now</span>
        <h2>${RITUAL_ICON[o.key]} ${esc(o.title)}</h2><p class="muted" style="margin:0">${esc(o.blurb)}</p>
        <div class="row spread" style="margin-top:12px"><span>ends in <b data-until="${o.ends_at}">${until(o.ends_at)}</b></span><span class="btn">Join now →</span></div></a>`).join('')
    : c.next ? `<div class="card ritual-hero"><div class="muted small">Next up</div><h2>${RITUAL_ICON[c.next.key]} ${esc(c.next.title)}</h2>
        <div class="big-countdown" data-until="${c.next.starts_at}">${until(c.next.starts_at)}</div>
        <p class="muted" style="margin:0">${localDay(c.next.starts_at)} at ${localTime(c.next.starts_at)} · ${esc(c.next.blurb)}</p></div>` : '';
  return `<div class="row spread"><div class="page-intro"><span class="eyebrow">Always on, never empty</span><h1>The shared clock.</h1>
      <p>Three rituals a week bring everyone into the same moment — show up and the room is full.</p></div>
      <a class="btn ghost" href="/api/clock.ics" download>📅 Add to calendar</a></div>
    <div class="grid section" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">${hero}</div>
    <div class="grid section steps" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">
      <div class="card flat"><h3>🚀 Monday Kickoff</h3><p class="small muted" style="margin:0">Challenges go live. Pitch a one-line idea, tap “I'm in” on others, and turn the best ones into teams in one click.</p></div>
      <div class="card flat"><h3>🔔 Nightly check-in</h3><p class="small muted" style="margin:0">Same half hour every night in your region${c.region_label ? ` (${esc(c.region_label)})` : ''}: post what you shipped, keep your streak.</p></div>
      <div class="card flat"><h3>🏆 Sunday Closing Ceremony</h3><p class="small muted" style="margin:0">Demos on a 3-minute clock, the crowd reacts, awards at the end. Put your team in the lineup.</p></div>
    </div>
    <section class="section"><h2>This week</h2><div class="stack">${[...byDay].map(([day, items]) => `<div class="card schedule-day ${day === today ? 'today' : ''}">
      <div class="day-label">${day === today ? 'Today' : esc(day)}</div><div class="stack">${items.map((o) => `<a class="sched ${o.live ? 'live' : ''}" href="#/live/${o.id}">
        <span class="mono small">${localTime(o.starts_at)}–${localTime(o.ends_at)}</span><span>${RITUAL_ICON[o.key]} <b>${esc(o.title)}</b></span>
        <span class="small">${o.live ? '<span class="pill live">Live</span>' : `<span class="muted">in <span data-until="${o.starts_at}">${until(o.starts_at)}</span></span>`}</span></a>`).join('')}</div></div>`).join('')}</div>
      <p class="small muted">Times are in your timezone. ${c.region_label ? `You get the ${esc(c.region_label)} check-in — change your timezone on your profile.` : 'Sign in to see your region’s check-in.'}</p></section>`;
}

// ---------- live ritual screen ----------

function floatEmoji(emoji) {
  const stage = document.getElementById('emoji-stage');
  if (!stage) return;
  const el = document.createElement('span');
  el.className = 'float-emoji';
  el.textContent = emoji;
  el.style.left = `${10 + Math.random() * 80}%`;
  el.style.animationDuration = `${2 + Math.random() * 1.2}s`;
  stage.append(el);
  setTimeout(() => el.remove(), 3500);
}

function reactionBar(s) {
  return `<div class="react-bar">${s.emojis.map((e) => `<button class="react" data-emoji="${e}" ${s.ritual.live && me ? '' : 'disabled'}>${e}</button>`).join('')}</div>`;
}

function ritualHeader(s) {
  const o = s.ritual;
  const t = nowSec();
  const status = o.live ? `<span class="pill live">Live</span> ends in <b data-until="${o.ends_at}">${until(o.ends_at)}</b>`
    : t < o.starts_at ? `<span class="pill upcoming">Soon</span> starts in <b data-until="${o.starts_at}">${until(o.starts_at)}</b>`
      : '<span class="pill past">Ended</span>';
  return `<div class="ritual-head"><div><a class="small" href="#/live">← Schedule</a><h1>${RITUAL_ICON[o.key]} ${esc(o.title)}</h1>
      <div class="row small">${status}<span class="muted">· ${localTime(o.starts_at)}–${localTime(o.ends_at)}</span></div></div>
    <div class="here"><div class="avatars">${s.here_people.slice(0, 8).map((u) => avatar(u)).join('')}</div>
      <b id="here-count">${s.here}</b> <span class="muted">here</span></div></div>`;
}

function kickoffBody(s) {
  const idea = (i) => `<div class="card idea ${i.team_id ? 'formed' : ''}"><div class="row spread" style="align-items:flex-start;flex-wrap:nowrap">
      <div><p style="margin:0 0 6px;font-weight:600">${esc(i.text)}</p><div class="small muted">pitched by <a href="#/u/${esc(i.author.handle)}">@${esc(i.author.handle)}</a></div></div>
      <div class="fans"><b>${i.fans.length}</b><span class="small muted">in</span></div></div>
    <div class="row spread" style="margin-top:10px"><div class="avatars">${i.fans.map((f) => avatar(f)).join('')}</div>
      ${i.team_id ? `<a class="btn sm ghost" href="#/t/${i.team_id}">Became ${esc(i.team_name)} →</a>`
        : i.mine ? `<button class="btn sm" data-live="form-team" data-id="${i.id}" data-text="${esc(i.text)}" ${s.ritual.live ? '' : 'disabled'}>Form team${i.fans.length ? ` & invite ${i.fans.length}` : ''} →</button>`
        : me && me.role === 'hacker' && s.ritual.live ? `<button class="btn sm ${i.in ? 'ghost on' : ''}" data-live="fan" data-id="${i.id}">${i.in ? '✓ I\'m in' : 'I\'m in'}</button>` : ''}</div></div>`;
  return `<div class="split"><div class="stack">
      ${me && me.role === 'hacker' && s.ritual.live ? `<form class="card row" id="pitch" style="flex-wrap:nowrap">
        <input name="text" required maxlength="140" placeholder="Pitch an idea in one line…" style="margin:0">
        <button class="btn" type="submit">Pitch</button></form>` : ''}
      <h2 style="margin:8px 0 0">Ideas <span class="muted small">· ${s.ideas.length}</span></h2>
      <div class="stack" id="ideas">${s.ideas.map(idea).join('') || empty('No ideas yet — be the first to pitch.')}</div>
    </div><aside class="stack"><h3 style="margin:0">This week's challenges</h3>
      ${s.challenges.map((c) => `<a class="card flat mini-challenge" href="#/c/${c.id}" style="--c:${esc(c.sponsor.color)}">
        <span class="small muted">${esc(c.sponsor.name)}</span><b>${esc(c.title)}</b>${c.prize ? `<span class="small">🏆 ${esc(c.prize)}</span>` : ''}</a>`).join('')}
    </aside></div>`;
}

function checkinBody(s) {
  const mine = s.checked_in;
  return `<div class="split"><div class="stack">
      ${!me ? `<div class="card">Sign in to check in. <a href="#/join">Join →</a></div>`
        : mine ? `<div class="card checked"><b>✓ You're checked in.</b> ${s.streak ? `<span class="streak">🔥 ${s.streak}-night streak</span>` : ''}</div>`
          : s.ritual.live ? `<form class="card stack" id="checkin-form"><b>What did you ship today?</b>
            <textarea name="text" required maxlength="280" rows="2" placeholder="Small wins count. “Login works.” “Fixed the flaky test.”"></textarea>
            <div class="row spread"><span class="small muted">${s.streak ? `🔥 ${s.streak}-night streak — keep it going` : 'Start a streak tonight'}</span><button class="btn" type="submit">Check in</button></div></form>`
            : '<div class="card muted">Check-ins open when this starts.</div>'}
      <h2 style="margin:8px 0 0">${s.checkins.length} checked in</h2>
      <div class="stack" id="checkins">${s.checkins.map((p) => `<div class="card person">${avatar(p.author)}<div class="who">
        <div class="row spread"><span>${whoLine(p.author)} <span class="small muted">· ${ago(p.created_at)}</span></span>${p.streak > 1 ? `<span class="streak small">🔥 ${p.streak}</span>` : ''}</div>
        <p style="margin:4px 0 0">${esc(p.text)}</p></div></div>`).join('') || empty('Nobody yet — go first.')}</div>
    </div><aside class="card flat small"><b>Why a check-in?</b><p class="muted" style="margin:6px 0 0">Everyone in your region posts in the same half hour, so the room fills up at once. Check-ins also land on the Floor and your team timeline — teammates see you're still in it.</p></aside></div>`;
}

function closingBody(s) {
  const p = s.presenter;
  let stage;
  if (s.phase === 'upcoming') stage = `<div class="stage-card"><div class="muted">The ceremony starts in</div><div class="big-countdown" data-until="${s.ritual.starts_at}">${until(s.ritual.starts_at)}</div></div>`;
  else if (s.phase === 'intro') stage = `<div class="stage-card"><div class="muted">Welcome! First demo in</div><div class="big-countdown" data-until="${s.demos_at}">${until(s.demos_at)}</div>
    <p class="muted small" style="margin:0">${s.lineup.length} teams in the lineup · 3 minutes each · react to cheer them on</p></div>`;
  else if (s.phase === 'demos' && p) {
    const pct = Math.min(100, Math.max(0, ((nowSec() - p.slot_start) / (p.slot_end - p.slot_start)) * 100));
    stage = `<div class="stage-card on-stage"><div class="row spread"><span class="pill live">On stage · slot ${p.position + 1}</span>
        <span class="mono">⏱ <b data-until="${p.slot_end}">${until(p.slot_end)}</b> left</span></div>
      <h2 style="margin:10px 0 2px">${esc(p.team_name)}</h2><div class="muted">${esc(p.project || '')}</div>
      ${p.description ? `<p class="small" style="margin:8px 0 0">${esc(p.description)}</p>` : ''}
      <div class="slot-progress"><div style="width:${pct.toFixed(1)}%"></div></div>
      <div class="row"><a class="btn" href="${esc(p.zoom_url)}" target="_blank" rel="noopener">Watch on Zoom ↗</a>
        ${p.demo_url ? `<a class="btn ghost" href="${esc(p.demo_url)}" target="_blank" rel="noopener">Try it ↗</a>` : ''}
        <span class="applause">👏 <b>${p.applause}</b></span></div></div>`;
  } else if (s.phase === 'demos') {
    stage = `<div class="stage-card"><div class="muted">Intermission</div><p style="margin:6px 0 0">${s.lineup.some((r) => r.state === 'next')
      ? 'Next team takes the stage shortly.' : `That's the lineup! Awards at ${localTime(s.awards_at)} — <span data-until="${s.awards_at}">${until(s.awards_at)}</span>.`}</p></div>`;
  } else {
    stage = `<div class="stage-card awards"><h2 style="margin:0 0 12px">🏆 Awards</h2>${s.awards.length ? `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr))">${s.awards.map((a) =>
      `<a class="card award" href="#/t/${a.team_id}"><span class="small muted">${esc(a.title)}</span><b>${esc(a.team_name)}</b><span class="small">${esc(a.project || '')}</span><span class="small muted">${esc(a.detail)}</span></a>`).join('')}</div>`
      : '<p class="muted" style="margin:0">No awards this week — not enough demos. Next Sunday!</p>'}</div>`;
  }
  const lineup = s.lineup.map((r) => `<div class="lineup-row ${r.state}"><span class="mono small">${localTime(r.slot_start)}</span>
      <span><b>${esc(r.team_name)}</b> <span class="small muted">${esc(r.project || '')}</span></span>
      <span class="small">${r.state === 'now' ? '<span class="pill live">Now</span>' : r.state === 'done' ? `👏 ${r.applause}` : `<span class="muted">in <span data-until="${r.slot_start}">${until(r.slot_start)}</span></span>`}</span>
      ${s.my_team_ids.includes(r.team_id) && r.state === 'next' ? `<button class="btn sm danger" data-live="unstage" data-id="${r.team_id}">Withdraw</button>` : ''}</div>`).join('');
  const canSign = s.eligible_teams.length && ['upcoming', 'intro', 'demos'].includes(s.phase) && s.lineup.length < s.max_slots;
  return `<div class="split"><div class="stack">${stage}
      <div class="card"><div class="row spread"><h3 style="margin:0">Lineup</h3><span class="small muted">${s.lineup.length}/${s.max_slots} slots · 3 min each</span></div>
        <div class="lineup">${lineup || '<p class="small muted" style="margin:8px 0 0">No teams yet. Submitted a project? Take the stage →</p>'}</div></div>
    </div><aside class="stack">
      ${canSign ? `<form class="card stack" id="stage-form"><h3 style="margin:0">Take the stage</h3>
        <label>Team<select name="team_id">${s.eligible_teams.map((t) => `<option value="${t.id}" data-zoom="${esc(t.zoom_url || '')}">${esc(t.name)} — ${esc(t.project)}</option>`).join('')}</select></label>
        <label>Zoom link you'll present from<input name="zoom_url" type="url" placeholder="https://us02web.zoom.us/j/…" value="${esc(s.eligible_teams[0].zoom_url || '')}"></label>
        <button class="btn" type="submit">Put us in the lineup</button><span class="small muted">You get the next open 3-minute slot.</span></form>` : ''}
      <div class="card flat small"><b>How it works</b><p class="muted" style="margin:6px 0 0">The stage runs on the clock — no host. Each team gets 3 minutes on their own Zoom; reactions during your slot count toward Crowd favorite. Judges' scores and community votes decide the other awards.</p></div>
    </aside></div>`;
}

async function viewRitual(occId) {
  const s0 = await api(`/live/${occId}`);
  const bodyOf = (s) => (s.ritual.key === 'kickoff' ? kickoffBody(s) : s.ritual.key === 'checkin' ? checkinBody(s) : closingBody(s));
  const html = `<div class="ritual ${s0.ritual.key}">
      <div id="ritual-head">${ritualHeader(s0)}</div>
      <div class="emoji-stage" id="emoji-stage"></div>
      <div id="ritual-react">${reactionBar(s0)}</div>
      <div id="ritual-body" class="section">${bodyOf(s0)}</div></div>`;
  return [html, () => {
    let last = s0;
    let lastCounts = { ...(s0.presenter?.reactions || s0.reactions) };
    const seq = renderSeq;
    const paint = (id, h) => {
      const el = document.getElementById(id);
      // Never replace a region someone is typing in.
      if (el && el.dataset.html !== h && !el.contains(document.activeElement)) { el.innerHTML = h; el.dataset.html = h; bind(); }
    };
    const bind = () => {
      bindForm('#pitch', async (v, f) => { await api(`/live/${occId}/ideas`, v); f.reset(); toast('Pitched 🚀'); poll(); });
      bindForm('#checkin-form', async (v) => { const r = await api(`/live/${occId}/checkin`, v); toast(`Checked in${r.streak > 1 ? ` — 🔥 ${r.streak}-night streak` : ''}`); poll(); });
      bindForm('#stage-form', async (v) => {
        const r = await api(`/live/${occId}/lineup`, { team_id: +v.team_id, zoom_url: v.zoom_url || undefined });
        toast(`You're slot ${r.position + 1} — on stage at ${localTime(r.slot_start)}`); poll();
      });
      const sel = document.querySelector('#stage-form [name=team_id]');
      if (sel && !sel.dataset.bound) {
        sel.dataset.bound = '1';
        sel.onchange = () => { document.querySelector('#stage-form [name=zoom_url]').value = sel.selectedOptions[0].dataset.zoom || ''; };
      }
    };
    const bindForm = (sel, fn) => {
      const f = document.querySelector(sel);
      if (!f || f.dataset.bound) return;
      f.dataset.bound = '1';
      f.onsubmit = async (e) => {
        e.preventDefault();
        const btn = f.querySelector('button[type=submit]');
        btn.disabled = true;
        try { await fn(formValues(f), f); } catch (err) { toast(err.message, true); } finally { btn.disabled = false; }
      };
    };
    const poll = async () => {
      clearTimeout(liveTimer);
      try {
        const s = await api(`/live/${occId}`);
        if (seq !== renderSeq) return;
        // Float the reactions other people sent since the last poll.
        const counts = s.presenter?.reactions || s.reactions;
        if (s.presenter?.team_id === last.presenter?.team_id) {
          for (const [e, n] of Object.entries(counts)) {
            for (let i = 0; i < Math.min(6, n - (lastCounts[e] || 0)); i++) floatEmoji(e);
          }
        }
        lastCounts = { ...counts };
        paint('ritual-head', ritualHeader(s));
        paint('ritual-react', reactionBar(s));
        paint('ritual-body', bodyOf(s));
        if (s.ritual.live !== last.ritual.live) refreshClock();
        last = s;
      } catch (e) { /* transient; try again */ }
      if (seq === renderSeq) liveTimer = setTimeout(poll, document.hidden ? 10000 : 2000);
    };
    ['ritual-head', 'ritual-react', 'ritual-body'].forEach((id) => {
      document.getElementById(id).dataset.html = id === 'ritual-head' ? ritualHeader(s0) : id === 'ritual-react' ? reactionBar(s0) : bodyOf(s0);
    });
    bind();
    liveTimer = setTimeout(poll, 2000);

    const root = document.querySelector('.ritual');
    root.addEventListener('click', async (e) => {
      const r = e.target.closest('.react');
      if (r && !r.disabled) {
        floatEmoji(r.dataset.emoji);
        lastCounts[r.dataset.emoji] = (lastCounts[r.dataset.emoji] || 0) + 1; // so the next poll doesn't float our own tap again
        api(`/live/${occId}/react`, { emoji: r.dataset.emoji }).catch((err) => { if (err.status !== 429) toast(err.message, true); });
        return;
      }
      const b = e.target.closest('[data-live]');
      if (!b) return;
      try {
        if (b.dataset.live === 'fan') {
          const res = await api(`/ideas/${b.dataset.id}/fan`, {});
          toast(res.in ? "You're in — they'll see you" : 'Removed');
        } else if (b.dataset.live === 'unstage') {
          if (!confirm('Take your team out of the lineup?')) return;
          await api(`/live/${occId}/lineup/leave`, { team_id: +b.dataset.id });
          toast('Withdrawn from the lineup');
        } else if (b.dataset.live === 'form-team') {
          const open = last.challenges.filter((c) => c.status !== 'past');
          modal('Turn your idea into a team', `<p class="small muted" style="margin:0">“${esc(b.dataset.text)}”</p>
            <label>Team name<input name="name" required maxlength="50"></label>
            <label>Challenge<select name="challenge_id">${open.map((c) => `<option value="${c.id}">${esc(c.title)} — ${esc(c.sponsor.name)}</option>`).join('')}</select></label>
            <p class="small muted" style="margin:0">Everyone who tapped “I'm in” gets an invite.</p>`, 'Create team', async (v) => {
            const res = await api(`/ideas/${b.dataset.id}/form-team`, { name: v.name, challenge_id: +v.challenge_id });
            await refreshMe();
            const busy = res.already_on_a_team ? ` (${res.already_on_a_team} already on a team for that challenge)` : '';
            toast(`Team created${res.invited ? ` — invited ${res.invited}` : ''}${busy} 🎉`);
            location.hash = `#/t/${res.team_id}/room`;
          });
          return;
        }
        poll();
      } catch (err) { toast(err.message, true); }
    });
  }];
}

function viewLive(occId) {
  return occId ? viewRitual(occId) : viewLiveHub();
}
