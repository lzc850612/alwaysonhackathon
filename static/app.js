'use strict';

const app = document.getElementById('app');
const nav = document.getElementById('nav');
let me = null;
let renderSeq = 0;

// ---------- utilities ----------

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, body) {
  const opts = { credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch('/api' + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = isErr ? 'err' : ''; }, 2800);
}

// Server time, so every countdown on every screen shows the same seconds (live.js sets the skew).
let clockSkew = 0;
const nowSec = () => Date.now() / 1000 + clockSkew;

const pad = (n) => String(n).padStart(2, '0');
function until(ts) {
  let s = Math.floor(ts - nowSec());
  if (s <= 0) return 'now';
  const d = Math.floor(s / 86400); s %= 86400;
  const h = Math.floor(s / 3600); s %= 3600;
  const m = Math.floor(s / 60);
  return d ? `${d}d ${h}h ${m}m` : `${pad(h)}:${pad(m)}:${pad(s % 60)}`;
}
setInterval(() => {
  document.querySelectorAll('[data-until]').forEach((el) => { el.textContent = until(+el.dataset.until); });
}, 1000);

const ago = (ts) => {
  const m = Math.max(0, Math.round((nowSec() - ts) / 60));
  return m < 1 ? 'just now' : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : fmtDate(ts);
};
const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const tzLabel = (tz) => `UTC${tz >= 0 ? '+' : ''}${tz}`;
const browserTz = () => Math.round(-new Date().getTimezoneOffset() / 60);
const splitList = (s) => String(s || '').split(',').map((x) => x.trim()).filter(Boolean);

function timing(c) {
  if (c.status === 'past') return `ended ${fmtDate(c.ends_at)}`;
  const target = c.status === 'upcoming' ? c.starts_at : c.ends_at;
  return `${c.status === 'upcoming' ? 'starts in' : 'ends in'} <span class="countdown" data-until="${target}">${until(target)}</span>`;
}

function hue(s) {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
function avatar(u, cls = '') {
  const ini = u.name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  return `<span class="avatar ${cls}" style="--h:${hue(u.handle)}" title="${esc(u.name)}">${esc(ini)}</span>`;
}
function chips(list, cls = '', hits = []) {
  const h = new Set(hits.map((x) => x.toLowerCase()));
  return `<div class="chips">${list.map((x) =>
    `<span class="chip ${cls} ${h.has(x.toLowerCase()) ? 'hit' : ''}">${esc(x)}</span>`).join('')}</div>`;
}
const pill = (s) => `<span class="pill ${s}">${{ live: 'Live', upcoming: 'Soon', past: 'Ended' }[s]}</span>`;
const scoreRing = (n) => `<div class="score" style="--p:${n}" title="Match score"><span>${n}</span></div>`;
const reasons = (rs) => rs && rs.length ? `<ul class="reasons">${rs.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : '';
const empty = (html) => `<div class="empty">${html}</div>`;
const tzOptions = (sel) => Array.from({ length: 27 }, (_, i) => i - 12)
  .map((t) => `<option value="${t}" ${t === sel ? 'selected' : ''}>${tzLabel(t)}</option>`).join('');

function formValues(form) {
  const out = Object.fromEntries(new FormData(form));
  form.querySelectorAll('input[type=checkbox]').forEach((cb) => { out[cb.name] = cb.checked; });
  return out;
}

function onSubmit(selector, handler) {
  const form = app.querySelector(selector);
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('button[type=submit], button:not([type])');
    if (btn) btn.disabled = true;
    try { await handler(formValues(form), form); } catch (err) { toast(err.message, true); } finally { if (btn) btn.disabled = false; }
  });
}

function modal(title, bodyHtml, okLabel, onOk) {
  if (document.querySelector('dialog[open]')) return; // one dialog at a time (e.g. a double click)
  const d = document.createElement('dialog');
  d.innerHTML = `<form class="stack"><h2>${esc(title)}</h2>${bodyHtml}
    <div class="row" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close>Cancel</button>
    <button type="submit" class="btn">${esc(okLabel)}</button></div></form>`;
  document.body.append(d);
  const form = d.querySelector('form');
  d.querySelector('[data-close]').onclick = () => d.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    try { await onOk(formValues(form)); d.close(); } catch (err) { toast(err.message, true); }
  };
  d.addEventListener('close', () => d.remove());
  d.showModal();
}

async function refreshMe() {
  const before = `${me?.id}:${me?.tz}:${(me?.teams || []).map((t) => t.id)}`;
  me = (await api('/me')).user;
  renderNav();
  // The clock bar's region and deadline are per person: refresh it when who you are, your timezone or your teams change.
  if (`${me?.id}:${me?.tz}:${(me?.teams || []).map((t) => t.id)}` !== before) refreshClock();
}

// ---------- shared components ----------

const fmtRange = (c) => {
  const day = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  const a = day(c.starts_at);
  const b = day(c.ends_at);
  return a === b ? a : `${a.replace(/, \d{4}$/, '')} – ${b}`;
};
const formatPill = (c) => `<span class="fmt-pill">${c.format === 'In person' ? '📍 In person' : '🌐 Online'}</span>`;
const lumaLabel = (c) => (c.luma_status === 'Waitlist' ? 'Join waitlist on Luma' : 'RSVP on Luma');

// A hackathon in the list. In-person events can link out to their Luma page for RSVP.
function challengeCard(c) {
  return `<article class="card challenge-card ${c.is_real ? 'real-event' : ''}" style="--c:${esc(c.sponsor.color)}">
    <a class="card-art" href="#/c/${c.id}" tabindex="-1" aria-hidden="true"><span class="art-label">${esc(c.is_real ? 'Real event · Luma' : c.tags[0] || 'Open hackathon')}</span>
      <div class="orbital"><span></span><span></span><span></span></div>
      <span class="art-num">${esc(c.sponsor.name.toUpperCase())}</span><span class="art-pill">${formatPill(c)} ${pill(c.status)}</span></a>
    <div class="card-body">
      <span class="sponsor">${esc(fmtRange(c))}${c.time_label ? ` · ${esc(c.time_label)}` : ''} · ${esc(c.location || 'Worldwide')}</span>
      <h3><a href="#/c/${c.id}">${esc(c.title)}</a></h3>
      <p class="muted small" style="margin:0">${esc(c.summary)}</p>
      ${c.prize ? `<div class="prize">${esc(c.prize)}</div>` : ''}
      <div class="meta"><span>${c.status === 'past' ? 'Ended' : timing(c)}</span><span>${c.team_count} teams · ${c.hacker_count} hackers</span></div>
      <div class="card-actions"><a class="btn sm ghost" href="#/c/${c.id}">View hackathon ↗</a>
        ${c.luma_url ? `<a class="btn sm luma" href="${esc(c.luma_url)}" target="_blank" rel="noopener noreferrer">${lumaLabel(c)} ↗</a>` : ''}</div>
      ${c.is_real ? `<p class="rsvp-note"><b>${c.luma_status === 'Waitlist' ? 'Waitlist at last check' : 'Registration on Luma'}</b>${c.verified_at ? ` · checked ${esc(c.verified_at)}` : ''}. Luma has current availability.</p>` : ''}
    </div>
  </article>`;
}

function joinAction(t, ctx = {}) {
  if (!me) return `<a class="btn sm" href="#/join">Sign in to join</a>`;
  if (me.role !== 'hacker') return '';
  if (t.members.some((m) => m.id === me.id)) return `<a class="btn sm ghost" href="#/t/${t.id}">Your team →</a>`;
  if (ctx.myTeamId) return '';
  if (t.requested || (ctx.pending || []).includes(t.id)) return `<button class="btn sm ghost" disabled>Requested</button>`;
  if (!t.open) return `<span class="small muted">Full</span>`;
  return `<button class="btn sm" data-act="join" data-id="${t.id}" data-name="${esc(t.name)}">Request to join</button>`;
}

function teamCard(t, opts = {}) {
  const slots = Math.max(0, t.max_size - t.members.length);
  return `<div class="card team-card">
    <div class="row spread" style="align-items:flex-start;flex-wrap:nowrap">
      <div><a href="#/t/${t.id}"><h3>${esc(t.name)}</h3></a>
      ${opts.showChallenge ? `<div class="small muted">for <a href="#/c/${t.challenge_id}">${esc(t.challenge_title)}</a></div>` : ''}</div>
      ${opts.score != null ? scoreRing(opts.score) : ''}
    </div>
    ${t.idea ? `<p class="small" style="margin:0">${esc(t.idea)}</p>` : ''}
    ${t.looking_for.length ? `<div><div class="small muted" style="margin-bottom:4px">Looking for</div>${chips(t.looking_for, 'need', me ? me.skills : [])}</div>` : ''}
    ${reasons(opts.reasons)}
    <div class="foot-row">
      <div class="avatars">${t.members.map((m) => avatar(m)).join('')}${'<span class="slot"></span>'.repeat(slots)}</div>
      ${opts.action ?? ''}
    </div>
  </div>`;
}

function personCard(p, extra = '') {
  return `<div class="card person">
    ${avatar(p, 'lg')}
    <div class="who">
      <div class="row spread"><div><a class="name" href="#/u/${esc(p.handle)}">${esc(p.name)}</a>
        <div class="handle">@${esc(p.handle)} · ${tzLabel(p.tz)}</div></div>
        ${p.score != null ? scoreRing(p.score) : p.looking ? '<span class="pill live">Looking</span>' : ''}</div>
      ${p.bio ? `<p class="small" style="margin:8px 0">${esc(p.bio)}</p>` : '<div style="height:8px"></div>'}
      ${chips(p.skills)}
      ${reasons(p.reasons)}
      ${extra}
    </div>
  </div>`;
}

const PERK_LABEL = { credits: '💳 Credits', mentorship: '🧑‍🏫 Mentorship', office_hours: '🕐 Office hours', api_access: '🔑 API access', swag: '🎁 Swag' };

function demoCard(d, opts = {}) {
  const when = d.status === 'live' ? '<span class="pill live">Live now</span>'
    : d.status === 'upcoming' ? `<span class="pill upcoming">in <span data-until="${d.starts_at}">${until(d.starts_at)}</span></span>`
    : '<span class="pill past">Ended</span>';
  const btn = d.stage ? (d.status === 'live' ? `<a class="btn sm live-btn" href="#/t/${d.team_id}/stage">▶ Watch live</a>` : `<a class="btn sm ghost" href="#/t/${d.team_id}/stage">Recap</a>`)
    : d.status === 'past' ? ''
    : `<button class="btn sm ${d.status === 'live' ? '' : 'ghost'}" data-act="watch" data-id="${d.id}">${d.status === 'live' ? 'Join on Zoom ↗' : d.watching ? 'Going ✓ — open link' : "I'll watch"}</button>`;
  return `<div class="card demo">
    <div class="row spread">${when}<span class="small muted">${d.stage ? `🎬 in-app${d.peak ? ` · ${d.peak} watching at peak` : ''}` : `${d.watchers} watching`}</span></div>
    <h3 style="margin:8px 0 2px">${esc(d.title)}</h3>
    <div class="small muted"><a href="#/t/${d.team_id}">${esc(d.team_name)}</a> · <a href="#/c/${d.challenge_id}">${esc(d.challenge_title)}</a></div>
    <div class="small muted">${new Date(d.starts_at * 1000).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })} · ${d.duration_min} min</div>
    <div class="row" style="margin-top:10px">${btn}${opts.cancel && !d.stage ? `<button class="btn sm danger" data-act="cancel-demo" data-id="${d.id}">Cancel</button>` : ''}</div>
  </div>`;
}

function perkCard(p) {
  const action = !me ? '<a class="btn sm ghost" href="#/join">Sign in to claim</a>'
    : me.role !== 'hacker' ? '' : `<button class="btn sm ${p.claimed ? 'ghost' : ''}" data-act="claim" data-id="${p.id}">${p.claimed ? 'Claimed — open' : 'Claim'}</button>`;
  return `<div class="perk"><div class="small muted">${PERK_LABEL[p.kind] || esc(p.kind)} · ${esc(p.sponsor_name)}</div>
    <b>${esc(p.title)}</b>${p.details ? `<div class="small muted">${esc(p.details)}</div>` : ''}
    <div class="row spread" style="margin-top:6px">${action}<span class="small muted">${p.claims} claimed</span></div></div>`;
}

const judgeBadge = (s) => s.judge_count ? `<span class="chip hit" title="${s.judge_count} judge score(s)">⚖ ${s.judge_score}/10</span>` : '';

// ---------- views ----------

// The hero's neural-ribbon illustration (two glowing orbits around a bright core).
function neuralArt() {
  const strands = (n, cy, rx, ry, w, fade) => Array.from({ length: n }, (_, i) =>
    `<ellipse cx="300" cy="${cy + i * 2}" rx="${rx}" ry="${ry}" stroke="url(#edge)" stroke-width="${w}" opacity="${(fade - i * (fade / n)).toFixed(3)}"/>`).join('');
  return `<div class="neural-art" aria-hidden="true"><svg viewBox="0 0 600 600" fill="none">
    <defs>
      <linearGradient id="ribbon" x1="60" y1="100" x2="530" y2="450" gradientUnits="userSpaceOnUse"><stop stop-color="#8cf0ff"/><stop offset=".25" stop-color="#2666ff"/><stop offset=".55" stop-color="#7245f8"/><stop offset=".8" stop-color="#ffa9d4"/><stop offset="1" stop-color="#ff643a"/></linearGradient>
      <radialGradient id="core"><stop stop-color="#fff"/><stop offset=".28" stop-color="#c3cbff"/><stop offset=".72" stop-color="#7567f7"/><stop offset="1" stop-color="#445beb" stop-opacity="0"/></radialGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="10"/></filter>
      <linearGradient id="edge"><stop stop-color="#fff"/><stop offset=".5" stop-color="#bde9ff"/><stop offset="1" stop-color="#9a75ff"/></linearGradient>
    </defs>
    <circle cx="300" cy="300" r="185" fill="url(#core)" opacity=".36"/>
    <g opacity=".3" stroke="#778bdf"><circle cx="300" cy="300" r="240" stroke-dasharray="3 12"/><circle cx="300" cy="300" r="204"/><path d="M30 300H570M300 30V570" stroke-dasharray="2 8"/></g>
    <g transform="rotate(-32 300 300)"><ellipse cx="300" cy="300" rx="205" ry="95" stroke="url(#ribbon)" stroke-width="46" opacity=".35" filter="url(#glow)"/><ellipse cx="300" cy="300" rx="205" ry="95" stroke="url(#ribbon)" stroke-width="36"/><ellipse cx="300" cy="282" rx="204" ry="93" stroke="url(#edge)" stroke-width="1.5" opacity=".85"/>${strands(16, 286, 204, 95, .55, .65)}</g>
    <g transform="rotate(42 300 300)"><ellipse cx="300" cy="300" rx="180" ry="89" stroke="url(#ribbon)" stroke-width="32"/><ellipse cx="300" cy="285" rx="179" ry="88" stroke="url(#edge)" stroke-width="1.8"/>${strands(15, 287, 179, 89, .5, .6)}</g>
    <circle cx="300" cy="300" r="15" fill="white" filter="url(#glow)"/><circle cx="300" cy="300" r="4" fill="white"/>
    <g fill="#4065ed"><circle cx="87" cy="175" r="4"/><circle cx="482" cy="143" r="3"/><circle cx="470" cy="456" r="5"/></g>
  </svg></div>`;
}

async function viewHome() {
  const [stats, live, upcoming, show, sponsors, demos, looking] = await Promise.all([
    api('/stats'), api('/challenges?status=live'), api('/challenges?status=upcoming'),
    api('/showcase'), api('/sponsors'), api('/demos'), api('/people?looking=1')]);
  const soonDemos = demos.demos.filter((d) => d.status !== 'past').slice(0, 3);
  const liveDemo = soonDemos.find((d) => d.status === 'live');
  const endingSoon = [...live.challenges].sort((a, b) => a.ends_at - b.ends_at)[0];
  const seeker = looking.people[0];
  const missing = await missingPieceSection().catch(() => '');
  const liveTop = [...live.challenges].sort((a, b) => a.ends_at - b.ends_at).slice(0, 4);
  // Floating cards show what's actually happening right now.
  const f1 = liveDemo
    ? `<a class="floating f1" href="${liveDemo.stage ? `#/t/${liveDemo.team_id}/stage` : '#/demos'}"><span class="fi">🎬</span><span><strong>${esc(liveDemo.team_name)} is demoing</strong><small>Live now · join the audience</small></span><i class="dot"></i></a>`
    : endingSoon ? `<a class="floating f1" href="#/c/${endingSoon.id}"><span class="fi">⏱</span><span><strong>${esc(endingSoon.title)}</strong><small>ends in <span data-until="${endingSoon.ends_at}">${until(endingSoon.ends_at)}</span></small></span><i class="dot"></i></a>` : '';
  const f2 = seeker ? `<a class="floating f2" href="#/u/${esc(seeker.handle)}">${avatar(seeker)}<span><strong>${esc(seeker.name.split(' ')[0])} is looking for a team</strong><small>${esc(seeker.skills.slice(0, 2).join(' · ') || 'Open to anything')}</small></span><i class="dot"></i></a>` : '';
  const f3 = `<a class="floating f3" href="#/challenges"><span class="fi" style="color:#6853dd">✳</span><span><strong>${stats.here_now} hacking right now</strong><small>${stats.open_help} hands raised on the Floor</small></span></a>`;
  return `
  <section class="hero">
    <div>
      <span class="live-label"><i class="dot"></i>THERE’S ALWAYS SOMETHING LIVE</span>
      <h1>Your next big idea<br>starts with<br><em>a stranger.</em><span class="hero-star">✳</span></h1>
      <p class="lede">Rolling sponsor challenges and a fresh open sprint every Monday. Find a team in minutes, ship something this week, demo it live.</p>
      <div class="row">
        <a class="btn lg" href="#/teams">Find your teammates ↗</a>
        <a class="btn lg ghost" href="#/challenges">Explore hackathons →</a>
      </div>
      ${me ? '' : '<p class="hero-note">No application, no waitlist. <a href="#/join">Join in 30 seconds →</a></p>'}
    </div>
    <div class="hero-visual">${neuralArt()}<span class="coordinate c1">ONE WORLD · MANY TIME ZONES</span><span class="visual-tag">● ALWAYS CONNECTED</span>${f1}${f2}${f3}</div>
  </section>
  <div class="stats-strip">
    <span><strong>${stats.live}</strong>live challenges</span>
    <span><strong>${stats.hackers}</strong>hackers</span>
    <span><strong>${stats.looking}</strong>looking for a team</span>
    <span><strong>${stats.teams}</strong>teams formed</span>
    <span><strong>${stats.submissions}</strong>projects shipped</span>
  </div>
  ${missing}
  <section class="section">
    <div class="section-head"><div><span class="eyebrow">Less scrolling. More shipping.</span><h2>Hackathons live right now.</h2><p>Online and in person. Pick one, find a crew, beat the clock.</p></div><a href="#/challenges">All hackathons ↗</a></div>
    <div class="grid fill">${liveTop.map(challengeCard).join('') || empty('Nothing live — check back Monday.')}</div>
  </section>
  ${soonDemos.length ? `<section class="section">
    <div class="section-head"><div><span class="eyebrow">Show, don’t tell</span><h2>Demos to watch.</h2></div></div>
    <div class="grid">${soonDemos.map((d) => demoCard(d)).join('')}</div></section>` : ''}
  ${upcoming.challenges.length ? `<section class="section">
    <div class="section-head"><div><span class="eyebrow">The next starting line</span><h2>Starting soon.</h2><p>Teams can form before the clock starts.</p></div></div>
    <div class="grid fill">${upcoming.challenges.slice(0, 4).map(challengeCard).join('')}</div></section>` : ''}
  <section class="section">
    <div class="section-head"><div><span class="eyebrow">From “what if” to “we built this”</span><h2>How it works.</h2></div></div>
    <div class="grid steps">
      <div class="card flat"><h3>Pick a challenge</h3><p class="muted small" style="margin:0">Sponsor tracks run for a week or two, on a rolling schedule. The open sprint restarts every Monday.</p></div>
      <div class="card flat"><h3>Get matched</h3><p class="muted small" style="margin:0">Teams post the roles they need. We rank teams for you by role fit, new skills, interests and timezone.</p></div>
      <div class="card flat"><h3>Build &amp; demo live</h3><p class="muted small" style="margin:0">Build together in your Team Room with a coding agent, then demo on the stage and get scored by judges and the crowd.</p></div>
    </div>
  </section>
  ${show.projects.length ? `<section class="section">
    <div class="section-head"><div><span class="eyebrow">A weekend project. A future company.</span><h2>Top projects.</h2></div></div>
    <div class="grid two">${show.projects.map((p, i) => `<div class="card project"><div class="rank">0${i + 1}</div><div class="body">
      <h3>${esc(p.title)}</h3><div class="small muted">${esc(p.team_name)} · <a href="#/c/${p.challenge_id}">${esc(p.challenge_title)}</a></div>
      <p class="small" style="margin:6px 0 0">${esc(p.description)}</p></div><div class="small muted">▲ ${p.votes}</div></div>`).join('')}</div>
  </section>` : ''}
  <section class="section community-banner"><span class="large-star">✳</span><div><span class="eyebrow">Built for ecosystems</span><h2>Your technology.<br>Their next big idea.</h2><p>Sponsors run rolling challenges and watch the funnel from views to shipped projects.</p></div>
    <div class="stack"><div class="sponsor-strip">${sponsors.sponsors.map((s) => `<span class="sponsor-chip" style="--c:${esc(s.color)}"><i></i>${esc(s.name)}</span>`).join('')}</div>
    <a class="btn" href="#/sponsor">Sponsor a challenge ↗</a></div></section>`;
}

let hackFilters = { q: '', format: 'All', theme: 'All' };

async function viewChallenges(tab) {
  tab = ['live', 'upcoming', 'past', 'all'].includes(tab) ? tab : 'live';
  const data = await api(tab === 'all' ? '/challenges' : `/challenges?status=${tab}`);
  const tabs = [['live', 'Live'], ['upcoming', 'Upcoming'], ['past', 'Past'], ['all', 'All']];
  const themes = ['All', ...new Set(data.challenges.map((c) => c.tags[0]).filter(Boolean))];
  const paint = () => {
    const f = hackFilters;
    const list = data.challenges.filter((c) => (f.format === 'All' || c.format === f.format) && (f.theme === 'All' || c.tags[0] === f.theme)
      && [c.title, c.location, c.sponsor.name, ...c.tags].join(' ').toLowerCase().includes(f.q.toLowerCase()));
    document.getElementById('hack-grid').innerHTML = list.map(challengeCard).join('')
      || `<div class="empty" style="grid-column:1/-1"><h3>No hackathons match these filters.</h3><button class="btn ghost" type="button" data-hf="reset">Reset filters</button></div>`;
    document.getElementById('hack-count').textContent = list.length;
  };
  return [`<div class="page-intro"><span class="eyebrow">The next chapter starts here</span><h1>Make something happen.</h1>
      <p>Online sprints and in-person weekends, all year round. In-person events link to Luma for RSVP.</p></div>
    <div class="directory-toolbar">
      <label class="search-box"><span aria-hidden="true">⌕</span><input id="hack-q" aria-label="Search hackathons" placeholder="Search hackathons or cities…" value="${esc(hackFilters.q)}"></label>
      <select id="hack-format" aria-label="Format" style="width:auto;margin:0">${['All', 'Online', 'In person'].map((x) => `<option ${hackFilters.format === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
      <select id="hack-theme" aria-label="Theme" style="width:auto;margin:0">${themes.map((x) => `<option ${hackFilters.theme === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
    </div>
    <nav class="tabs" style="margin-bottom:22px">${tabs.map(([k, l]) => `<a href="#/challenges/${k}" class="${k === tab ? 'on' : ''}">${l}</a>`).join('')}
      <span class="small muted" style="margin-left:auto;align-self:center"><b id="hack-count">0</b> hackathons</span></nav>
    <div class="grid fill" id="hack-grid"></div>`, () => {
    paint();
    document.getElementById('hack-q').addEventListener('input', (e) => { hackFilters.q = e.target.value; paint(); });
    document.getElementById('hack-format').addEventListener('change', (e) => { hackFilters.format = e.target.value; paint(); });
    document.getElementById('hack-theme').addEventListener('change', (e) => { hackFilters.theme = e.target.value; paint(); });
    document.getElementById('hack-grid').addEventListener('click', (e) => {
      if (e.target.closest('[data-hf="reset"]')) { hackFilters = { q: '', format: 'All', theme: 'All' }; render(); }
    });
  }];
}

function videoEmbed(url) {
  try {
    const u = new URL(url);
    const yt = u.hostname === 'youtu.be' ? u.pathname.slice(1) : /(^|\.)youtube\.com$/.test(u.hostname) ? u.searchParams.get('v') : null;
    if (yt && /^[\w-]{11}$/.test(yt)) return `<iframe src="https://www.youtube-nocookie.com/embed/${yt}" title="Opening video" allow="fullscreen; picture-in-picture" allowfullscreen></iframe>`;
    const vimeo = /(^|\.)vimeo\.com$/.test(u.hostname) && u.pathname.match(/(\d+)\/?$/)?.[1];
    if (vimeo) return `<iframe src="https://player.vimeo.com/video/${vimeo}" title="Opening video" allow="fullscreen" allowfullscreen></iframe>`;
    if (u.protocol === 'https:' && /\.(mp4|webm|ogg)$/i.test(u.pathname)) return `<video src="${esc(url)}" controls playsinline></video>`;
  } catch (e) { /* not a URL */ }
  return '';
}

function personTile(p) {
  return `<article class="person-tile" data-b="profile" data-id="${p.id}" tabindex="0" role="button" aria-label="Open ${esc(p.name)}'s profile">
    ${avatar(p, 'lg')}<div class="who"><b>${esc(p.name)}</b><small>${esc(p.title || 'Builder')}${p.city ? ` · ${esc(p.city)}` : ''}</small>
    ${p.team ? `<span class="chip">🧩 ${esc(p.team.name)}</span>` : '<span class="chip need">Looking for a team</span>'}</div>
    ${p.linkedin ? `<a class="li-link" href="${esc(p.linkedin)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(p.name)} on LinkedIn" data-stop>in</a>` : ''}
  </article>`;
}

function demoListItem(d) {
  const watch = d.stage ? `<a class="btn sm ${d.status === 'live' ? 'live-btn' : 'ghost'}" href="#/t/${d.team_id}/stage">${d.status === 'live' ? '▶ Watch live' : d.status === 'past' ? 'Demo recap ↗' : 'Stage ↗'}</a>`
    : d.status === 'past' ? '<span class="small muted">Zoom demo · ended</span>' : `<button class="btn sm" data-act="watch" data-id="${d.id}">${d.status === 'live' ? 'Join on Zoom ↗' : "I'll watch"}</button>`;
  return `<div class="card demo-row">${pill(d.status === 'past' ? 'past' : d.status)}<div class="who"><b>${esc(d.title)}</b>
    <div class="small muted"><a href="#/t/${d.team_id}">${esc(d.team_name)}</a> · ${new Date(d.starts_at * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}${d.peak ? ` · ${d.peak} watching at peak` : ''}</div></div>${watch}</div>`;
}

async function viewChallenge(id, params) {
  const [d, f] = await Promise.all([api(`/challenges/${id}`), api(`/floor?challenge_id=${id}`)]);
  const c = d.challenge;
  const ctx = { myTeamId: d.my_team_id, pending: d.pending_team_ids };
  const myTeam = d.teams.find((t) => t.id === d.my_team_id);
  const tabs = [['overview', 'Overview'], ['floor', '● The Floor'], ['teams', `Teams · ${d.teams.length}`], ['people', `People · ${d.people.length}`],
    ['demos', c.status === 'past' ? `Demos · ${d.demos.length + d.submissions.length}` : 'Demos & projects']];
  const tab = tabs.some(([k]) => k === params?.get('tab')) ? params.get('tab') : c.status === 'past' ? 'demos' : 'overview';
  let side = '';
  if (myTeam) {
    side = `<div class="card"><h3>You're on ${esc(myTeam.name)}</h3><p class="small muted">${myTeam.members.length}/${myTeam.max_size} members</p>
      <div class="row"><a class="btn" href="#/t/${myTeam.id}/room">🚪 Team room</a><a class="btn ghost" href="#/t/${myTeam.id}">${c.status === 'live' ? 'Manage & submit' : 'Manage team'}</a></div></div>`;
  } else if (c.status !== 'past' && me && me.role === 'hacker') {
    side = `<form class="card stack" id="new-team"><h3>Start a team</h3>
      <label>Team name<input name="name" required maxlength="50" placeholder="e.g. Null Pointers"></label>
      <label>The idea<textarea name="idea" maxlength="600" placeholder="One or two sentences. Rough is fine."></textarea></label>
      <label>Roles you need<input name="looking_for" placeholder="react, design, ml"><div class="hint">Comma-separated skills. These drive matching.</div></label>
      <label>Max team size<select name="max_size">${Array.from({ length: c.max_team }, (_, i) => i + 1)
        .map((n) => `<option ${n === c.max_team ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
      <button class="btn" type="submit">Create team</button></form>`;
  } else if (!me && c.status !== 'past') {
    side = `<div class="card"><h3>Want in?</h3><p class="small muted">Create a profile to join, start a team, or walk onto the floor.</p><a class="btn" href="#/join">Join</a></div>`;
  }
  const host = c.sponsor;
  const sponsorCards = [
    ...(host.id ? [{ name: host.name, color: host.color, tier: c.is_real ? 'Organizer' : 'Host sponsor', offer: c.title, details: host.tagline, link: host.product_url || host.website, host: true }] : []),
    ...d.sponsors,
  ];
  const video = c.video_url ? videoEmbed(c.video_url) : '';
  const food = c.food.length ? `<ul class="food">${c.food.map((x) => `<li><span class="mono">${esc(x.time)}</span><div><b>${esc(x.item)}</b><small>${esc(x.detail)}</small></div></li>`).join('')}</ul>`
    : c.is_real ? `<p class="muted small" style="margin:0">Food, venue and schedule are managed by the organizers. <a href="${esc(c.luma_url)}" target="_blank" rel="noopener noreferrer">See the Luma page ↗</a></p>`
      : '<p class="muted small" style="margin:0">Nothing listed yet.</p>';
  const overview = `<div class="split"><div class="stack">
      <div class="card flat"><span class="eyebrow">About</span><p class="desc" style="margin:0 0 12px">${esc(c.description)}</p>${chips(c.tags)}</div>
      <div class="card"><span class="eyebrow">Information & instructions</span>
        ${c.venue || c.time_label ? `<p class="small" style="margin:0 0 10px">${c.time_label ? `🕘 ${esc(c.time_label)} · ` : ''}${c.venue ? `📍 ${esc(c.venue)}` : esc(c.location)}</p>` : ''}
        <p class="desc" style="margin:0">${esc(c.info || 'Details coming soon.')}</p>${c.is_real ? '<p class="small muted" style="margin:10px 0 0">This listing reflects the organizer’s Luma page; Luma is authoritative.</p>' : ''}</div>
      <div class="card"><span class="eyebrow">Opening ceremony</span>${video ? `<div class="video-frame">${video}</div>`
        : `<div class="video-frame empty-video"><b>▶</b><span>${c.status === 'upcoming' ? 'The opening ceremony streams when the hackathon starts.' : 'The opening video appears here when the organizers post it.'}</span></div>`}</div>
      <div class="card"><span class="eyebrow">Sponsors & partners</span>${sponsorCards.length ? `<div class="sponsor-grid">${sponsorCards.map((x) => `<div class="sponsor-card" style="--c:${esc(x.color || '#6750eb')}">
          <span class="tier">${esc(x.tier)}</span><b>${esc(x.name)}</b><span class="offer">${esc(x.offer)}</span>${x.details ? `<small>${esc(x.details)}</small>` : ''}
          ${x.host && (host.product_url || c.resource_url) ? `<button class="btn sm ghost" data-act="try" data-id="${c.id}">Try ${esc(x.name)} ↗</button>`
            : x.link ? `<a class="small" href="${esc(x.link)}" target="_blank" rel="noopener noreferrer">${esc(x.link.replace(/^https?:\/\//, ''))} ↗</a>` : ''}</div>`).join('')}</div>`
        : '<p class="muted small" style="margin:0">No sponsors listed.</p>'}
        ${d.perks.length ? `<div class="stack" style="margin-top:14px">${d.perks.map(perkCard).join('')}</div>` : ''}</div>
    </div><aside class="stack">${side}
      <div class="card"><span class="eyebrow">Food & beverage</span>${food}</div>
      <div class="card flat small"><b>Rules of the road</b><ul style="padding-left:18px;margin:8px 0 0" class="muted">
        <li>Start fresh: code written during the hackathon.</li><li>One team per hacker per hackathon.</li>
        <li>Submit a repo or demo link before the deadline.</li><li>Be kind. Help beginners.</li></ul></div>
    </aside></div>`;
  const teams = `<div class="split"><div class="grid two">${d.teams.map((t) => teamCard(t, { action: c.status === 'past' ? '' : joinAction(t, ctx) })).join('')
      || empty('No teams yet — be the first.')}</div><aside class="stack">${side}</aside></div>`;
  const people = `<div class="row spread" style="margin-bottom:14px"><p class="muted small" style="margin:0">Everyone who joined or is on a team. Click someone to see their profile${me ? ', connect, or invite them' : ''}.</p>
      <input id="people-q" placeholder="Filter by name, skill or city…" style="max-width:280px;margin:0"></div>
    <div class="people-grid" id="people-grid">${d.people.map(personTile).join('') || empty(c.is_real ? 'Join on Luma, then mark yourself as attending here to meet other builders.' : 'Nobody yet — join and be the first.')}</div>`;
  const past = c.status === 'past';
  const demos = `<section><div class="section-head"><div><span class="eyebrow">${past ? 'The show is over — the demos live on' : 'Show, don’t tell'}</span><h2>${past ? 'Demos from this hackathon.' : 'Demos.'}</h2></div></div>
      <div class="stack">${d.demos.map(demoListItem).join('') || empty(past ? 'No recorded demos for this hackathon.' : 'No demos scheduled yet — teams go live from their Team Room.')}</div></section>
    <section class="section"><div class="section-head"><div><span class="eyebrow">Community vote</span><h2>Projects.</h2></div></div>
      <div class="stack">${d.submissions.map((s, i) => `<div class="card project">
        <div class="rank">${String(i + 1).padStart(2, '0')}</div>
        <div class="body"><div class="row"><h3 style="margin:0">${esc(s.title)}</h3>${judgeBadge(s)}</div><div class="small muted">by <a href="#/t/${s.team_id}">${esc(s.team_name)}</a></div>
          <p class="small" style="margin:6px 0">${esc(s.description)}</p>
          <div class="row small">${s.repo_url ? `<a href="${esc(s.repo_url)}" target="_blank" rel="noopener">Repo ↗</a>` : ''}
          ${s.demo_url ? `<a href="${esc(s.demo_url)}" target="_blank" rel="noopener">Try the demo ↗</a>` : ''}<a href="#/t/${s.team_id}/stage">Demo stage ↗</a></div></div>
        <button class="btn vote ${s.voted ? 'on' : ''}" data-act="vote" data-id="${s.id}" aria-label="Vote"><span>▲</span><b>${s.votes}</b></button>
      </div>`).join('') || empty('No projects yet.')}</div></section>`;
  const html = `
  <div class="banner" style="--c:${esc(c.sponsor.color)}">
    <div class="row"><span class="pill">${{ live: '● Live', upcoming: 'Starting soon', past: 'Ended' }[c.status]}</span>${formatPill(c)}<b>${esc(c.sponsor.name)}</b></div>
    <h1>${esc(c.title)}</h1>
    <p style="max-width:62ch;margin:0 0 6px">${esc(c.summary)}</p>
    <p class="small" style="margin:0 0 16px;opacity:.85">📅 ${esc(fmtRange(c))}${c.time_label ? ` · ${esc(c.time_label)}` : ''} · 📍 ${esc(c.location || 'Worldwide')}</p>
    <div class="row" style="position:relative;z-index:1">
      ${c.luma_url ? `<a class="btn luma" href="${esc(c.luma_url)}" target="_blank" rel="noopener noreferrer">${lumaLabel(c)} ↗</a>` : ''}
      ${me && me.role === 'hacker' && c.status !== 'past' ? `<button class="btn ${c.luma_url ? 'ghost' : ''}" data-hk="attend">${d.attending ? '✓ You’re in' : c.luma_url ? 'Mark me as attending' : 'Join this hackathon'}</button>` : ''}
      ${c.status !== 'past' ? `<button class="btn ghost" data-hk="floor"><span class="dot"></span>Walk onto the floor${f.here.length ? ` · ${f.here.length} here` : ''}</button>` : ''}
    </div>
    <div class="banner-meta">
      ${c.prize ? `<div><span>Prize</span><b>${esc(c.prize)}</b></div>` : ''}
      <div><span>${c.status === 'upcoming' ? 'Starts in' : c.status === 'live' ? 'Ends in' : 'Ended'}</span><b>${c.status === 'past' ? fmtDate(c.ends_at)
        : `<span class="countdown" data-until="${c.status === 'upcoming' ? c.starts_at : c.ends_at}">…</span>`}</b></div>
      <div><span>Teams</span><b>${c.team_count}</b></div>
      <div><span>People</span><b>${d.people.length}</b></div>
      <div><span>Team size</span><b>1–${c.max_team}</b></div>
    </div>
  </div>
  <nav class="tabs section hack-tabs" role="tablist" style="margin-top:24px">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" class="${k === tab ? 'on' : ''}">${l}</button>`).join('')}</nav>
  <div class="section" style="margin-top:22px">
    <div data-pane="overview" ${tab === 'overview' ? '' : 'hidden'}>${overview}</div>
    <div data-pane="floor" ${tab === 'floor' ? '' : 'hidden'}>${floorSection(f, c)}</div>
    <div data-pane="teams" ${tab === 'teams' ? '' : 'hidden'}>${teams}</div>
    <div data-pane="people" ${tab === 'people' ? '' : 'hidden'}>${people}</div>
    <div data-pane="demos" ${tab === 'demos' ? '' : 'hidden'}>${demos}</div>
  </div>`;
  return [html, () => {
    app.querySelectorAll('[data-until]').forEach((el) => { el.textContent = until(+el.dataset.until); });
    const show = (k) => {
      app.querySelectorAll('.hack-tabs [data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === k));
      app.querySelectorAll('[data-pane]').forEach((p) => { p.hidden = p.dataset.pane !== k; });
      history.replaceState(null, '', `#/c/${c.id}?tab=${k}`);
      if (k === 'floor') startFloor(c.id);
    };
    app.querySelector('.hack-tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) show(b.dataset.tab); });
    if (tab === 'floor') startFloor(c.id);
    app.querySelector('.banner').addEventListener('click', async (e) => {
      const b = e.target.closest('[data-hk]');
      if (!b) return;
      if (b.dataset.hk === 'floor') {
        show('floor');
        const input = app.querySelector('#checkin [name=status]');
        app.querySelector('[data-pane="floor"]').scrollIntoView({ behavior: 'smooth', block: 'start' });
        input?.focus();
      } else if (b.dataset.hk === 'attend') {
        try {
          const r = await api(`/challenges/${c.id}/attend`, {});
          toast(r.attending ? `You're in for ${c.title} 🎉` : 'Removed from the attendee list');
          render();
        } catch (err) { toast(err.message, true); }
      }
    });
    const pq = app.querySelector('#people-q');
    pq?.addEventListener('input', () => {
      const q = pq.value.toLowerCase();
      app.querySelectorAll('#people-grid .person-tile').forEach((el) => { el.hidden = q && !el.textContent.toLowerCase().includes(q); });
    });
    app.querySelector('#people-grid')?.addEventListener('keydown', (e) => {
      const t = e.target.closest('.person-tile');
      if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openBuilderProfile(+t.dataset.id); }
    });
    bindFloor(c.id);
    onSubmit('#new-team', async (v) => {
      const r = await api('/teams', { ...v, challenge_id: c.id, looking_for: splitList(v.looking_for), max_size: +v.max_size });
      await refreshMe();
      toast('Team created');
      location.hash = `#/t/${r.team.id}`;
    });
  }];
}

async function viewTeams() {
  const [all, match, ch] = await Promise.all([
    api('/teams?open=1'),
    me && me.role === 'hacker' ? api('/match/teams') : Promise.resolve(null),
    api('/challenges'),
  ]);
  const open = ch.challenges.filter((c) => c.status !== 'past');
  let html = `<div class="page-intro"><span class="eyebrow">Better, together</span><h1>Find your missing piece.</h1><p>Teams post the roles they need. Request to join, or start your own on any challenge and invite people.</p></div>`;
  if (match) {
    html += `<section class="section"><div class="section-head"><h2>Recommended for you</h2>
      <a class="small" href="#/me">Tune your skills →</a></div>
      ${me.skills.length ? '' : '<p class="notice">Add skills to your profile to get better matches.</p>'}
      <div class="grid two">${match.teams.map((t) => teamCard(t, { showChallenge: true, score: t.score, reasons: t.reasons, action: joinAction(t) })).join('')
        || empty('No open teams that fit right now — <a href="#/challenges">start one</a>.')}</div></section>`;
  } else if (!me) {
    html += `<p class="notice"><a href="#/join">Sign in</a> to see teams ranked for your skills and timezone.</p>`;
  }
  html += `<section class="section"><div class="section-head"><h2>All open teams</h2>
    <select id="filter" style="width:auto;margin:0"><option value="">All challenges</option>
    ${open.map((c) => `<option value="${c.id}">${esc(c.title)}</option>`).join('')}</select></div>
    <div class="grid two" id="all-teams">${all.teams.map((t) => `<div data-c="${t.challenge_id}">${teamCard(t, { showChallenge: true, action: joinAction(t) })}</div>`).join('')
      || empty('No open teams.')}</div></section>`;
  return [html, () => {
    app.querySelector('#filter').onchange = (e) => {
      app.querySelectorAll('#all-teams > [data-c]').forEach((el) => { el.hidden = !!e.target.value && el.dataset.c !== e.target.value; });
    };
  }];
}

async function viewTeam(id) {
  const d = await api(`/teams/${id}`);
  const t = d.team;
  const isMember = me && t.members.some((m) => m.id === me.id);
  const isOwner = me && me.id === t.owner_id;
  const sugg = isOwner && t.open && t.challenge_status !== 'past' ? (await api(`/teams/${id}/suggestions`)).people : [];
  let action = '';
  if (isMember) action = `<div class="row"><a class="btn" href="#/t/${t.id}/room">🚪 Enter team room</a><button class="btn sm danger" data-act="leave" data-id="${t.id}" data-c="${t.challenge_id}">Leave team</button></div>`;
  else if (d.my_request && d.my_request.kind === 'join') action = `<button class="btn sm ghost" data-act="decide" data-id="${d.my_request.id}" data-action="cancel">Cancel request</button>`;
  else if (d.my_request && d.my_request.kind === 'invite') action = `<a class="btn sm" href="#/inbox">You're invited — respond</a>`;
  else if (t.challenge_status !== 'past') action = joinAction(t, { myTeamId: d.my_team_in_challenge });

  const sub = d.submission;
  const canSubmit = isMember && t.challenge_status === 'live';
  let html = `<div class="row small muted"><a href="#/c/${t.challenge_id}">← ${esc(t.challenge_title)}</a>${pill(t.challenge_status)}</div>
  <div class="row spread" style="margin-top:12px"><div class="row"><h1 style="margin:0">${esc(t.name)}</h1>
    ${t.status === 'shipped' ? `<span class="pill live">Shipped</span><a class="btn sm ghost" href="#/t/${t.id}/stage">🎬 Demo stage</a>` : ''}</div>${t.status === 'shipped' && !isMember ? '' : action}</div>
  ${t.idea ? `<p class="muted" style="max-width:65ch;margin-top:8px">${esc(t.idea)}</p>` : ''}
  <div class="split section" style="margin-top:20px"><div class="stack">
    <div class="card"><div class="section-head"><h2>Members</h2><span class="small muted">${t.members.length}/${t.max_size}</span></div>
      <div class="stack">${t.members.map((m) => `<div class="person">${avatar(m)}<div class="who">
        <a class="name" href="#/u/${esc(m.handle)}">${esc(m.name)}</a> ${m.id === t.owner_id ? '<span class="chip">owner</span>' : ''}
        <div class="handle">@${esc(m.handle)} · ${tzLabel(m.tz)}</div>${chips(m.skills)}</div></div>`).join('')}</div>
      ${t.looking_for.length && t.open ? `<div style="margin-top:16px"><div class="small muted" style="margin-bottom:4px">Still looking for</div>${chips(t.looking_for, 'need')}</div>` : ''}
    </div>`;
  if (sub) {
    html += `<div class="card"><h2>Submission</h2><h3>${esc(sub.title)}</h3><p class="small">${esc(sub.description)}</p>
      <div class="row small">${sub.repo_url ? `<a href="${esc(sub.repo_url)}" target="_blank" rel="noopener">Repo ↗</a>` : ''}
      ${sub.demo_url ? `<a href="${esc(sub.demo_url)}" target="_blank" rel="noopener">Demo ↗</a>` : ''}</div></div>`;
  }
  if (canSubmit) {
    html += `<details class="card" ${sub ? '' : 'open'}><summary><b>${sub ? 'Update submission' : 'Submit your project'}</b></summary>
      <form class="stack" id="submit" style="margin-top:12px">
        <label>Project title<input name="title" required maxlength="80" value="${esc(sub?.title)}"></label>
        <label>What does it do?<textarea name="description" maxlength="1200">${esc(sub?.description)}</textarea></label>
        <div class="form-grid"><label>Repo URL<input name="repo_url" type="url" placeholder="https://github.com/…" value="${esc(sub?.repo_url)}"></label>
        <label>Demo URL<input name="demo_url" type="url" placeholder="https://…" value="${esc(sub?.demo_url)}"></label></div>
        <button class="btn" type="submit">${sub ? 'Update' : 'Submit'}</button></form></details>`;
  }
  if (d.demos.length || (isMember && t.challenge_status !== 'upcoming')) {
    html += `<div class="card"><div class="section-head"><h2>Live demo</h2></div>
      ${d.demos.length ? `<div class="grid">${d.demos.map((x) => demoCard(x, { cancel: isMember && x.status !== 'past' })).join('')}</div>` : ''}
      ${isMember && t.challenge_status !== 'upcoming' ? `<details ${d.demos.length ? '' : 'open'} style="margin-top:12px"><summary><b>Schedule a Zoom demo</b></summary>
        <p class="small muted">Everyone on Always-On gets notified and can join to watch.</p>
        <form class="stack" id="demo-form">
          <label>Title<input name="title" maxlength="80" placeholder="${esc(t.name)} demo"></label>
          <label>Zoom meeting link<input name="zoom_url" type="url" required placeholder="https://us02web.zoom.us/j/…"></label>
          <div class="form-grid"><label>Starts<select name="when"><option value="0">Right now</option><option value="900">In 15 minutes</option>
            <option value="3600">In 1 hour</option><option value="custom">Pick a time…</option></select></label>
          <label>Length<select name="duration_min"><option>10</option><option selected>15</option><option>30</option><option>60</option></select></label></div>
          <label data-custom hidden>Start time<input name="at" type="datetime-local"></label>
          <button class="btn" type="submit">Schedule &amp; notify everyone</button></form></details>` : ''}
    </div>`;
  }
  html += `</div><aside class="stack">`;
  if (isOwner) {
    html += `<div class="card"><h3>Requests</h3>${d.requests.length ? `<div class="stack">${d.requests.map((r) => `<div>
        <div class="person">${avatar(r.user)}<div class="who"><a class="name" href="#/u/${esc(r.user.handle)}">${esc(r.user.name)}</a>
        <div class="handle">${r.kind === 'invite' ? 'invited — waiting on them' : 'wants to join'}</div>
        ${r.message ? `<p class="small" style="margin:4px 0">“${esc(r.message)}”</p>` : ''}${chips(r.user.skills, '', t.looking_for)}</div></div>
        ${r.kind === 'join' ? `<div class="row" style="margin-top:8px"><button class="btn sm" data-act="decide" data-id="${r.id}" data-action="accept">Accept</button>
        <button class="btn sm ghost" data-act="decide" data-id="${r.id}" data-action="decline">Decline</button></div>`
        : `<button class="btn sm ghost" style="margin-top:8px" data-act="decide" data-id="${r.id}" data-action="cancel">Withdraw invite</button>`}
      </div>`).join('')}</div>` : '<p class="small muted" style="margin:0">No pending requests.</p>'}</div>`;
    if (sugg.length) {
      html += `<div class="card"><h3>Suggested teammates</h3><p class="small muted">Looking for a team, ranked by fit.</p><div class="stack">
        ${sugg.map((p) => `<div class="person">${avatar(p)}<div class="who"><div class="row spread"><a class="name" href="#/u/${esc(p.handle)}">${esc(p.name)}</a><b class="small">${p.score}</b></div>
          ${chips(p.skills, '', t.looking_for)}${reasons(p.reasons)}
          ${p.pending ? '<span class="small muted">Pending</span>' : `<button class="btn sm" style="margin-top:6px" data-act="invite" data-team="${t.id}" data-user="${p.id}" data-name="${esc(p.name)}">Invite</button>`}
        </div></div>`).join('')}</div></div>`;
    }
    html += `<details class="card"><summary><b>Edit team</b></summary><form class="stack" id="edit-team" style="margin-top:12px">
      <label>Name<input name="name" required maxlength="50" value="${esc(t.name)}"></label>
      <label>Idea<textarea name="idea" maxlength="600">${esc(t.idea)}</textarea></label>
      <label>Roles you need<input name="looking_for" value="${esc(t.looking_for.join(', '))}"></label>
      <label>Max size<input name="max_size" type="number" min="${t.members.length}" max="8" value="${t.max_size}"></label>
      <button class="btn" type="submit">Save</button></form></details>`;
  }
  html += `</aside></div>`;
  return [html, () => {
    const df = app.querySelector('#demo-form');
    if (df) df.when.onchange = () => { df.querySelector('[data-custom]').hidden = df.when.value !== 'custom'; };
    onSubmit('#demo-form', async (v) => {
      const startsAt = v.when === 'custom' ? Math.floor(new Date(v.at).getTime() / 1000) : Math.floor(Date.now() / 1000) + +v.when;
      if (!startsAt) throw new Error('Pick a start time');
      await api(`/teams/${t.id}/demos`, { title: v.title, zoom_url: v.zoom_url, starts_at: startsAt, duration_min: +v.duration_min });
      toast('Demo scheduled — everyone has been notified'); render();
    });
    onSubmit('#submit', async (v) => { await api('/submissions', { ...v, team_id: t.id }); toast('Project submitted 🚀'); render(); });
    onSubmit('#edit-team', async (v) => {
      await api(`/teams/${t.id}`, { ...v, looking_for: splitList(v.looking_for), max_size: +v.max_size });
      toast('Saved'); render();
    });
  }];
}

async function viewPeople(params) {
  const q = params.get('q') || '', skill = params.get('skill') || '', looking = params.get('looking') === '1';
  const data = await api(`/people?q=${encodeURIComponent(q)}&skill=${encodeURIComponent(skill)}&looking=${looking ? 1 : ''}`);
  return [`<div class="page-intro"><span class="eyebrow">Your people are out there</span><h1>Meet the builders.</h1><p>Different skills, shared ambition. Filter by skill or find people still looking for a team.</p></div>
    <form class="row" id="pf" style="margin:16px 0 20px">
      <input name="q" placeholder="Search name, bio, skill…" value="${esc(q)}" style="flex:2;min-width:180px;margin:0">
      <input name="skill" placeholder="Exact skill, e.g. react" value="${esc(skill)}" style="flex:1;min-width:140px;margin:0">
      <label class="row small" style="margin:0"><input type="checkbox" name="looking" ${looking ? 'checked' : ''}>Looking for a team</label>
      <button class="btn" type="submit">Filter</button></form>
    <div class="grid two">${data.people.map((p) => personCard(p)).join('') || empty('No one matches that.')}</div>`, () => {
    app.querySelector('#pf').onsubmit = (e) => {
      e.preventDefault();
      const v = formValues(e.target);
      const sp = new URLSearchParams();
      if (v.q) sp.set('q', v.q);
      if (v.skill) sp.set('skill', v.skill);
      if (v.looking) sp.set('looking', '1');
      location.hash = '#/people' + (sp.toString() ? '?' + sp : '');
    };
  }];
}

async function viewPerson(handle) {
  const d = await api(`/people/${handle}`);
  const p = d.person;
  let invite = '';
  if (me && me.role === 'hacker' && me.id !== p.id && p.role === 'hacker') {
    const mine = (await api(`/people/${me.handle}`)).teams.filter((t) =>
      t.owner_id === me.id && t.open && t.challenge_status !== 'past' && !d.teams.some((x) => x.challenge_id === t.challenge_id));
    if (mine.length) {
      invite = `<div class="card"><h3>Invite ${esc(p.name.split(' ')[0])}</h3><div class="stack">${mine.map((t) =>
        `<div class="row spread"><span class="small">${esc(t.name)} <span class="muted">· ${esc(t.challenge_title)}</span></span>
        <button class="btn sm" data-act="invite" data-team="${t.id}" data-user="${p.id}" data-name="${esc(p.name)}">Invite</button></div>`).join('')}</div></div>`;
    }
  }
  return `<div class="split"><div class="stack">${personCard(p, p.helped ? `<p class="small" style="margin:10px 0 0">🙌 Helped <b>${p.helped}</b> hacker${p.helped === 1 ? '' : 's'} get unstuck on the floor</p>` : '')}
    <section class="section"><h2>Teams</h2><div class="grid two">${d.teams.map((t) => teamCard(t, { showChallenge: true })).join('') || empty('Not on any teams yet.')}</div></section>
    </div><aside class="stack">${invite}
    ${p.interests.length ? `<div class="card flat"><h3>Interests</h3>${chips(p.interests)}</div>` : ''}</aside></div>`;
}

async function viewDemos() {
  const d = await api('/demos');
  const by = (st) => d.demos.filter((x) => x.status === st);
  const sec = (title, list, none) => `<section class="section"><h2>${title}</h2><div class="grid">${list.map((x) => demoCard(x)).join('') || empty(none)}</div></section>`;
  return `<div class="page-intro"><span class="eyebrow">Show, don’t tell</span><h1>Demos to watch.</h1><p>Teams demo live on their in-app stage or on Zoom. You get a notification when one starts.</p></div>
    ${sec('Live now', by('live'), 'No one is on stage right now.')}
    ${sec('Coming up', by('upcoming'), 'Nothing scheduled yet. On a team? Schedule one from your team page.')}
    ${by('past').length ? sec('Earlier today', by('past'), '') : ''}`;
}

async function viewNotifications() {
  if (!me) { location.hash = '#/join'; return ''; }
  const d = await api('/notifications');
  if (me.unread) { await api('/notifications/read', {}); me.unread = 0; renderNav(); }
  return `<h1>Notifications</h1><div class="stack" style="max-width:720px">${d.notifications.map((n) =>
    `<a class="card notif ${n.read ? '' : 'unread'}" href="${esc(n.link || '#/')}"><span>${esc(n.text)}</span><span class="small muted">${ago(n.created_at)}</span></a>`).join('')
    || empty('All quiet. You\'ll hear about demos, invites and team updates here.')}</div>`;
}

async function viewJudge() {
  if (!me || me.role !== 'judge') {
    return empty('This area is for judges. <a href="#/join?judge=1">Sign up with a judge code</a> or try the demo judge <button class="btn sm" data-act="login-as" data-handle="judy">@judy</button>');
  }
  const d = await api('/judge/queue');
  const todo = d.submissions.filter((x) => !x.my_score).length;
  const rubric = { innovation: 'Innovation', technical: 'Technical depth', design: 'Design & UX', impact: 'Impact' };
  return [`<div class="row spread"><h1 style="margin:0">Judging</h1><span class="pill ${todo ? 'upcoming' : 'live'}">${todo ? `${todo} to score` : 'All scored'}</span></div>
    <p class="muted">Score each project 1–10 on four criteria. Teams see the average, not who gave it.</p>
    <div class="stack">${d.submissions.map((x) => `<div class="card"><div class="split" style="gap:20px">
      <div><div class="row">${pill(x.challenge_status)}<span class="small muted">${esc(x.challenge_title)}</span></div>
        <h2 style="margin:8px 0 2px">${esc(x.title)}</h2>
        <div class="small muted">by <a href="#/t/${x.team_id}">${esc(x.team_name)}</a> · ${x.members.map((m) => '@' + esc(m.handle)).join(', ')}</div>
        <p class="small" style="margin:10px 0">${esc(x.description)}</p>
        <div class="row small">${x.repo_url ? `<a href="${esc(x.repo_url)}" target="_blank" rel="noopener">Repo ↗</a>` : ''}
        ${x.demo_url ? `<a href="${esc(x.demo_url)}" target="_blank" rel="noopener">Demo ↗</a>` : ''}
        <span class="muted">▲ ${x.votes} votes</span>${judgeBadge(x)}</div></div>
      <form class="stack score-form" data-id="${x.id}">
        ${d.rubric.map((f) => `<label>${rubric[f]} <output>${x.my_score ? x.my_score[f] : 5}</output>
          <input type="range" name="${f}" min="1" max="10" value="${x.my_score ? x.my_score[f] : 5}"></label>`).join('')}
        <label>Feedback for the team<textarea name="comment" rows="2" maxlength="1000">${esc(x.my_score?.comment)}</textarea></label>
        <button class="btn" type="submit">${x.my_score ? 'Update score' : 'Submit score'}</button>
      </form></div></div>`).join('') || empty('No projects submitted yet.')}</div>`, () => {
    app.querySelectorAll('.score-form').forEach((f) => {
      f.addEventListener('input', (e) => { if (e.target.type === 'range') e.target.previousElementSibling.textContent = e.target.value; });
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const v = formValues(f);
        try {
          const r = await api(`/submissions/${f.dataset.id}/score`, { ...v, innovation: +v.innovation, technical: +v.technical, design: +v.design, impact: +v.impact });
          toast(`Saved — average now ${r.judge_score}/10`); render();
        } catch (err) { toast(err.message, true); }
      });
    });
  }];
}

let floorTimer = null;
let floorFilter = 'all';

function whoLine(u) {
  const where = u.org ? `<span class="chip org">${esc(u.org)}</span>` : u.role === 'judge' ? '<span class="chip org">judge</span>'
    : u.team ? `<a href="#/t/${u.team.id}">${esc(u.team.name)}</a>` : '';
  return `<a class="name" href="#/u/${esc(u.handle)}">${esc(u.name)}</a> ${where}`;
}

function floorHere(f) {
  return `<div class="row spread"><h3 style="margin:0"><span class="dot"></span> Here now</h3><span class="small muted">${f.here.length}</span></div>
    <div class="stack" style="margin-top:12px">${f.here.map((u) => `<div class="person">${avatar(u)}<div class="who">
      <div>${whoLine(u)}</div><div class="small">${esc(u.status) || '<span class="muted">heads down</span>'}</div>
      <div class="small muted">here since ${new Date(u.since * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}${u.helped ? ` · 🙌 helped ${u.helped}` : ''}</div>
    </div></div>`).join('') || '<p class="small muted" style="margin:0">Quiet right now. Walk on and get it started.</p>'}</div>`;
}

function floorPost(p) {
  const mine = me && p.author.id === me.id;
  const badge = p.kind === 'help'
    ? (p.resolved_by ? `<span class="pill live">Solved by @${esc(p.resolved_by.handle)}</span>` : '<span class="pill upcoming">🙋 Needs a hand</span>')
    : p.ritual ? `<a class="pill past" href="#/live/${esc(p.ritual)}">🔔 Check-in</a>` : '<span class="pill past">Ship log</span>';
  const repliers = [...new Map(p.replies.filter((r) => r.author.id !== p.author.id).map((r) => [r.author.id, r.author])).values()];
  return `<div class="card post ${p.kind === 'help' && !p.resolved_by ? 'open-help' : ''}"><div class="person">${avatar(p.author)}<div class="who">
    <div class="row spread"><div>${whoLine(p.author)} <span class="small muted">· ${ago(p.created_at)}</span></div>${badge}</div>
    <p style="margin:6px 0">${esc(p.text)}</p>${p.tags.length ? chips(p.tags, '', me ? me.skills : []) : ''}
    ${p.replies.length ? `<div class="replies">${p.replies.map((r) => `<div class="reply">${avatar(r.author)}<div><b>${esc(r.author.name)}</b>
      ${r.author.org ? `<span class="chip org">${esc(r.author.org)}</span>` : ''} <span class="small muted">${ago(r.created_at)}</span>
      <div class="small">${esc(r.text)}</div></div></div>`).join('')}</div>` : ''}
    <div class="row" style="margin-top:10px">
      <button class="btn sm ghost ${p.highfived ? 'on' : ''}" data-act="highfive" data-id="${p.id}">🙌 <b>${p.highfives}</b></button>
      <button class="btn sm ghost" data-act="reply" data-id="${p.id}" data-kind="${p.kind}" data-name="${esc(p.author.name)}">${p.kind === 'help' && !p.resolved_by && !mine ? 'I can help' : 'Reply'}</button>
      ${mine && p.kind === 'help' && !p.resolved_by && repliers.length ? `<button class="btn sm" data-act="resolve" data-id="${p.id}"
        data-helpers="${esc(JSON.stringify(repliers.map((r) => [r.id, r.name])))}">Mark solved</button>` : ''}
    </div></div></div></div>`;
}

function floorFeed(f) {
  const posts = f.posts.filter((p) => floorFilter === 'all' || (floorFilter === 'help' ? p.kind === 'help' && !p.resolved_by : p.kind === 'update'));
  return posts.map(floorPost).join('') || empty(floorFilter === 'help' ? 'No open hands. Everyone is unstuck 🎉' : 'Nothing yet — post the first update.');
}

async function viewFloor() {
  // The Floor now lives inside each hackathon. The old link goes to the always-live Open Sprint's floor.
  const live = (await api('/challenges?status=live')).challenges;
  const target = live.find((c) => !c.sponsor.id) || live[0];
  location.hash = target ? `#/c/${target.id}?tab=floor` : '#/challenges';
  return '';
}

function floorSection(f, c) {
  const openHelp = f.posts.filter((p) => p.kind === 'help' && !p.resolved_by).length;
  const checkin = !me ? `<div class="card checkin"><b>This is the hacking floor.</b> <span class="muted">See who's building right now, share progress, and raise your hand when you're stuck.</span>
      <a class="btn" href="#/join">Join to walk in</a></div>`
    : f.me_here ? `<form class="card checkin" id="checkin"><span class="dot"></span><b>You're on the floor.</b>
      <input name="status" maxlength="120" value="${esc(f.here.find((h) => h.id === me.id)?.status)}" placeholder="What are you working on?">
      <button class="btn sm ghost" type="submit">Update</button><button class="btn sm danger" type="button" data-act="step-out">Step out</button></form>`
    : `<form class="card checkin" id="checkin"><input name="status" maxlength="120" placeholder="What are you working on right now?" required>
      <button class="btn" type="submit">Walk onto the floor</button></form>`;
  const tabs = [['all', 'Everything'], ['help', `Hands raised${openHelp ? ` (${openHelp})` : ''}`], ['update', 'Ship log']];
  return `<p class="muted" style="margin:0 0 16px">The room at 2am, online — who’s building ${esc(c.title)} right now, what just shipped, and who could use a hand.</p>
    <div class="split"><div class="stack">
      ${c.status === 'past' ? '<div class="notice">This hackathon has ended — the floor is read-only history.</div>' : checkin}
      ${me && c.status !== 'past' ? `<form class="card stack" id="composer">
        <nav class="tabs"><button type="button" class="on" data-kind="update">📦 Ship update</button><button type="button" data-kind="help">🙋 Raise your hand</button></nav>
        <textarea name="text" required maxlength="500" rows="2" placeholder="What did you just get working?"></textarea>
        <label data-help hidden>What skills could help?<input name="tags" placeholder="react, auth, swift"><div class="hint">People on the floor with these skills (and matching sponsors) get a tap on the shoulder.</div></label>
        <div class="row spread"><span class="small muted" data-hint>Small wins count. Posting keeps your team visible.</span><button class="btn" type="submit">Post</button></div>
      </form>` : ''}
      <nav class="tabs" id="floor-tabs">${tabs.map(([k, l]) => `<button type="button" data-filter="${k}" class="${k === floorFilter ? 'on' : ''}">${l}</button>`).join('')}</nav>
      <div class="stack" id="floor-feed">${floorFeed(f)}</div>
    </div><aside class="card" id="floor-here">${floorHere(f)}</aside></div>`;
}

// Poll the floor while its tab is open (render() clears the timer when you navigate away).
function startFloor(cid) {
  clearInterval(floorTimer);
  const refresh = async () => {
    if (app.querySelector('[data-pane="floor"]')?.hidden) return;
    const next = await api(`/floor?challenge_id=${cid}`);
    for (const [id, html] of [['floor-feed', floorFeed(next)], ['floor-here', floorHere(next)]]) {
      const el = document.getElementById(id);
      if (el && el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; }
    }
  };
  floorTimer = setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 8000);
}

function bindFloor(cid) {
  app.querySelectorAll('#floor-tabs [data-filter]').forEach((b) => {
    b.onclick = () => { floorFilter = b.dataset.filter; render(); };
  });
  onSubmit('#checkin', async (v) => { await api('/floor/checkin', { ...v, challenge_id: cid }); await refreshMe(); toast('You\'re on the floor 👋'); render(); });
  const comp = app.querySelector('#composer');
  if (!comp) return;
  let kind = 'update';
  comp.querySelectorAll('[data-kind]').forEach((b) => {
    b.onclick = () => {
      kind = b.dataset.kind;
      comp.querySelectorAll('[data-kind]').forEach((x) => x.classList.toggle('on', x === b));
      comp.querySelector('[data-help]').hidden = kind !== 'help';
      comp.text.placeholder = kind === 'help' ? 'What are you stuck on? Error messages welcome.' : 'What did you just get working?';
      comp.querySelector('[data-hint]').textContent = kind === 'help' ? 'Someone on the floor has probably hit this before.' : 'Small wins count. Posting keeps your team visible.';
    };
  });
  onSubmit('#composer', async (v) => {
    await api('/posts', { kind, text: v.text, tags: splitList(v.tags), challenge_id: cid });
    toast(kind === 'help' ? 'Hand raised — tapping the right shoulders 🙋' : 'Posted 📦');
    render();
  });
}

async function viewInbox() {
  if (!me) { location.hash = '#/join'; return ''; }
  const d = await api('/inbox');
  const item = (r, actions) => `<div class="card person">${avatar(r.user)}<div class="who">
    <div><a class="name" href="#/u/${esc(r.user.handle)}">${esc(r.user.name)}</a> → <a href="#/t/${r.team_id}">${esc(r.team_name)}</a>
    <span class="small muted">· ${esc(r.challenge_title)}</span></div>
    ${r.message ? `<p class="small" style="margin:4px 0">“${esc(r.message)}”</p>` : ''}${chips(r.user.skills)}
    <div class="row" style="margin-top:8px">${actions}</div></div></div>`;
  const decide = (r) => `<button class="btn sm" data-act="decide" data-id="${r.id}" data-action="accept">Accept</button>
    <button class="btn sm ghost" data-act="decide" data-id="${r.id}" data-action="decline">Decline</button>`;
  return `<div class="page-intro"><span class="eyebrow">Make the first move</span><h1>Inbox.</h1><p>Invites for you, requests to join your teams, and what you’ve sent.</p></div>
    <section class="section"><h2>Invites for you</h2><div class="stack">${d.invites.map((r) => item(r, decide(r))).join('') || empty('No invites yet. <a href="#/me">Make sure “looking for a team” is on.</a>')}</div></section>
    <section class="section"><h2>Requests to join your teams</h2><div class="stack">${d.join_requests.map((r) => item(r, decide(r))).join('') || empty('Nothing pending.')}</div></section>
    <section class="section"><h2>Sent</h2><div class="stack">${d.outgoing.map((r) => item(r,
      `<span class="chip">${r.kind === 'join' ? 'you asked to join' : 'you invited'}</span><span class="chip ${r.status === 'accepted' ? 'hit' : ''}">${esc(r.status)}</span>
      ${r.status === 'pending' ? `<button class="btn sm ghost" data-act="decide" data-id="${r.id}" data-action="cancel">Withdraw</button>` : ''}`)).join('') || empty('Nothing sent in the last 30 days.')}</div></section>`;
}

async function viewProfile() {
  if (!me) { location.hash = '#/join'; return ''; }
  return [`<div class="split"><form class="card stack" id="profile"><h1>Your profile</h1>
    <div class="form-grid"><label>Name<input name="name" required maxlength="60" value="${esc(me.name)}"></label>
    <label>Timezone<select name="tz">${tzOptions(me.tz)}</select></label></div>
    <label>Bio<textarea name="bio" maxlength="280">${esc(me.bio)}</textarea></label>
    ${me.role === 'hacker' ? `<label>Skills<input name="skills" value="${esc(me.skills.join(', '))}" placeholder="python, react, design"><div class="hint">Comma-separated. Teams match on these.</div></label>
    <label>Interests<input name="interests" value="${esc(me.interests.join(', '))}" placeholder="ai, fintech, accessibility"></label>
    <div class="form-grid"><label>Role<select name="title"><option value="">—</option>${B_ROLES.map((r) => `<option ${me.title === r ? 'selected' : ''}>${r}</option>`).join('')}</select></label>
      <label>Experience<select name="experience"><option value="">—</option>${B_EXPERIENCE.map((r) => `<option ${me.experience === r ? 'selected' : ''}>${r}</option>`).join('')}</select></label>
      <label>City<input name="city" maxlength="60" value="${esc(me.city)}"></label><label>Country<input name="country" maxlength="60" value="${esc(me.country)}"></label>
      <label>Hours per week<input name="hours" type="number" min="0" max="80" value="${me.hours || ''}"></label>
      <label>Collaboration<select name="collab"><option value="">—</option>${B_COLLAB.map((r) => `<option ${me.collab === r ? 'selected' : ''}>${r}</option>`).join('')}</select></label>
      <label>Looking for<select name="seeking"><option value="">—</option>${B_SEEKING.map((r) => `<option ${me.seeking === r ? 'selected' : ''}>${r}</option>`).join('')}</select></label>
      <label>LinkedIn<input name="linkedin" type="url" placeholder="https://www.linkedin.com/in/you" value="${esc(me.linkedin)}"></label></div>
    <label class="row"><input type="checkbox" name="looking" ${me.looking ? 'checked' : ''}>I'm looking for a team (show me to team owners)</label>` : ''}
    <div class="row"><button class="btn" type="submit">Save</button><button type="button" class="btn ghost" data-act="logout">Sign out</button></div>
  </form><aside class="stack"><div class="card flat"><div class="row">${avatar(me, 'lg')}<div><b>@${esc(me.handle)}</b><div class="small muted">${me.role}</div></div></div>
    <p class="small muted" style="margin:12px 0 0"><a href="#/u/${esc(me.handle)}">View public profile →</a></p>
    ${me.role === 'sponsor' ? '<p class="small" style="margin:8px 0 0"><a href="#/sponsor">Sponsor dashboard →</a></p>' : ''}</div></aside></div>`, () => {
    onSubmit('#profile', async (v) => {
      await api('/me', { ...v, tz: +v.tz, hours: +v.hours || 0, skills: splitList(v.skills), interests: splitList(v.interests) });
      await refreshMe();
      toast('Profile saved');
    });
  }];
}

async function viewSponsor() {
  if (!me || me.role !== 'sponsor') {
    return `<section class="hero"><div><span class="live-label"><i class="dot"></i>FOR SPONSORS & DEVREL</span>
      <h1>Builders,<br><em>every week.</em><br>Not once a year.</h1>
      <p class="lede">Run a rolling challenge on your API. Hackers find your product, form teams around it, and ship real projects — while you watch the funnel.</p>
      <div class="row"><a class="btn lg" href="#/join?sponsor=1">Launch a challenge ↗</a>
      <button class="btn lg ghost" data-act="login-as" data-handle="nimbus">See a demo dashboard</button></div></div>
      <div class="hero-visual">${neuralArt()}
        <div class="floating f1"><span class="fi">👀</span><span><strong>Views → clicks</strong><small>who saw it, who tried your product</small></span></div>
        <div class="floating f2"><span class="fi">🛠</span><span><strong>Teams building on you</strong><small>and the skills they bring</small></span></div>
        <div class="floating f3"><span class="fi" style="color:#6853dd">✳</span><span><strong>Shipped projects</strong><small>demoed live, scored by judges</small></span></div></div></section>
      <div class="grid steps section">
        <div class="card flat"><h3>Always-on reach</h3><p class="small muted" style="margin:0">Your challenge sits next to a live, weekly community instead of one weekend's crowd.</p></div>
        <div class="card flat"><h3>A funnel you can measure</h3><p class="small muted" style="margin:0">Page views → product clicks → teams → shipped projects, all on one dashboard.</p></div>
        <div class="card flat"><h3>Talent signal</h3><p class="small muted" style="margin:0">See the top skills of the people building on your platform. Great for DevRel and hiring.</p></div>
      </div>`;
  }
  const a = await api('/sponsor/analytics');
  const t = a.totals;
  const maxV = Math.max(1, ...a.daily_views.map((x) => x.views));
  const maxS = Math.max(1, ...a.top_skills.map((x) => x[1]));
  const tile = (n, label) => `<div class="stat"><b>${n ?? 0}</b><span>${label}</span></div>`;
  const nextMon = new Date(); nextMon.setDate(nextMon.getDate() + ((8 - nextMon.getDay()) % 7 || 7)); nextMon.setHours(9, 0, 0, 0);
  const localIso = (dt) => new Date(dt - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  return [`<div class="row spread"><div><div class="small muted">Sponsor dashboard</div><h1 style="margin:0">${esc(a.sponsor.name)}</h1></div>
    <a class="btn" href="#new-challenge" data-act="scroll" data-target="new-challenge">+ New challenge</a></div>
    <div class="stats">${tile(t.views, 'challenge views')}${tile(t.clicks, 'product clicks')}${tile(t.ctr + '%', 'click-through')}
      ${tile(t.teams, 'teams formed')}${tile(t.hackers, 'hackers building')}${tile(t.submissions, 'projects shipped')}${tile(t.perk_claims, 'support claimed')}</div>
    <div class="grid two section">
      <div class="card"><h3>Views, last 14 days</h3><div class="spark">${a.daily_views.map((x) =>
        `<div style="height:${(100 * x.views / maxV).toFixed(1)}%" title="${fmtDate(x.day)}: ${x.views} views"></div>`).join('')}</div>
        <div class="spark-labels"><span>${fmtDate(a.daily_views[0].day)}</span><span>today</span></div></div>
      <div class="card"><h3>What your builders know</h3>${a.top_skills.length ? `<div class="bars">${a.top_skills.map(([s, n]) =>
        `<div class="bar"><span>${esc(s)}</span><div class="track"><div class="fill" style="width:${(100 * n / maxS).toFixed(1)}%"></div></div><span class="n">${n}</span></div>`).join('')}</div>`
        : '<p class="small muted">Shows up once teams form on your challenges.</p>'}</div>
    </div>
    <section class="section card"><h3>Challenges</h3><div class="table-wrap"><table>
      <thead><tr><th>Challenge</th><th>Status</th><th class="num">Views</th><th class="num">Clicks</th><th class="num">CTR</th><th class="num">Teams</th><th class="num">Hackers</th><th class="num">Projects</th></tr></thead>
      <tbody>${a.challenges.map((c) => `<tr><td><a href="#/c/${c.id}">${esc(c.title)}</a></td><td>${pill(c.status)}</td>
        <td class="num">${c.views}</td><td class="num">${c.clicks}</td><td class="num">${c.ctr}%</td><td class="num">${c.team_count}</td>
        <td class="num">${c.hacker_count}</td><td class="num">${c.submission_count}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">No challenges yet.</td></tr>'}</tbody>
    </table></div></section>
    <section class="section grid two">
      <div class="card"><h3>Support you're offering</h3>${a.perks.length ? `<div class="stack">${a.perks.map((p) => `<div class="perk">
        <div class="small muted">${PERK_LABEL[p.kind]} · ${p.challenge_title ? esc(p.challenge_title) : 'all your challenges'}</div>
        <b>${esc(p.title)}</b><div class="small muted">${p.claims} hackers claimed</div></div>`).join('')}</div>` : '<p class="small muted">Nothing yet — credits and office hours are the fastest way to get teams building on you.</p>'}</div>
      <form class="card stack" id="new-perk"><h3>Offer support</h3>
        <div class="form-grid"><label>Type<select name="kind">${Object.entries(PERK_LABEL).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
        <label>For<select name="challenge_id"><option value="">All my challenges</option>${a.challenges.filter((c) => c.status !== 'past').map((c) => `<option value="${c.id}">${esc(c.title)}</option>`).join('')}</select></label></div>
        <label>Title<input name="title" required maxlength="80" placeholder="$500 in credits per team"></label>
        <label>Details<textarea name="details" rows="2" maxlength="600" placeholder="How to redeem, office-hour times, who to ask…"></textarea></label>
        <label>Link<input name="link" type="url" placeholder="https://… (redeem page, Zoom, Calendly)"></label>
        <button class="btn" type="submit">Publish</button></form>
    </section>
    <form class="card stack section" id="new-challenge"><h2>Launch a challenge</h2>
      <label>Title<input name="title" required maxlength="80" placeholder="Build a voice agent with our API"></label>
      <label>One-line summary<input name="summary" maxlength="160"></label>
      <label>Details &amp; judging criteria<textarea name="description" maxlength="4000" rows="5"></textarea></label>
      <div class="form-grid">
        <label>Prize<input name="prize" maxlength="120" placeholder="$2,000 + credits"></label>
        <label>Tags<input name="tags" placeholder="ai, voice, mobile"><div class="hint">Matched against hacker interests.</div></label>
        <label>Docs / starter kit URL<input name="resource_url" type="url" placeholder="https://"></label>
        <label>Format<select name="format"><option>Online</option><option>In person</option></select></label>
        <label>Location<input name="location" maxlength="60" placeholder="Worldwide, or a city for in-person"></label>
        <label>Luma event page<input name="luma_url" type="url" placeholder="https://luma.com/your-event"><div class="hint">In-person events: RSVPs happen on Luma.</div></label>
        <label>Max team size<input name="max_team" type="number" min="1" max="8" value="4"></label>
        <label>Starts<input name="starts" type="datetime-local" required value="${localIso(nextMon)}"></label>
        <label>Length (days)<input name="days" type="number" min="1" max="60" value="7"></label>
      </div>
      <button class="btn" type="submit">Launch</button></form>`, () => {
    onSubmit('#new-perk', async (v) => {
      await api('/perks', { ...v, challenge_id: v.challenge_id ? +v.challenge_id : null });
      toast('Support published'); render();
    });
    onSubmit('#new-challenge', async (v) => {
      const starts = Math.floor(new Date(v.starts).getTime() / 1000);
      const r = await api('/challenges', { ...v, tags: splitList(v.tags), max_team: +v.max_team, starts_at: starts, ends_at: starts + (+v.days) * 86400 });
      toast('Challenge launched');
      location.hash = `#/c/${r.challenge.id}`;
    });
  }];
}

async function viewJoin(params) {
  if (me) { location.hash = '#/me'; return ''; }
  const initial = params.get('sponsor') === '1' ? 'sponsor' : params.get('judge') === '1' ? 'judge' : 'hacker';
  const demo = [['ben', 'Ben — frontend, has an invite'], ['lena', 'Lena — NLP, looking'], ['ada', 'Ada — owns a team, live demo'],
    ['judy', 'Judy — judge'], ['nimbus', 'Nimbus — sponsor']];
  const roleTab = (val, label) => `<label class="${initial === val ? 'on' : ''}" style="padding:6px 14px;border-radius:9px;cursor:pointer"><input type="radio" name="role" value="${val}" ${initial === val ? 'checked' : ''} hidden>${label}</label>`;
  return [`<div class="split"><div class="card">
    <nav class="tabs" style="margin-bottom:18px"><button type="button" class="on" data-tab="signup">Create profile</button><button type="button" data-tab="login">Sign in</button></nav>
    <form class="stack" id="signup">
      <div class="tabs" role="radiogroup">${roleTab('hacker', "I'm a hacker")}${roleTab('judge', "I'm a judge")}${roleTab('sponsor', "I'm a sponsor")}</div>
      <div class="form-grid"><label>Your name<input name="name" required maxlength="60"></label>
      <label>Handle<input name="handle" required pattern="[a-z0-9_\\-]{2,24}" maxlength="24" placeholder="lowercase, no spaces"></label></div>
      <div data-for="sponsor" class="stack">
        <div class="form-grid"><label>Company<input name="org" maxlength="60"></label><label>Brand color<input name="color" type="color" value="#ff6b35"></label></div>
        <label>Tagline<input name="tagline" maxlength="140" placeholder="What your product does, in one line"></label>
        <div class="form-grid"><label>Website<input name="website" type="url" placeholder="https://"></label>
        <label>Product sign-up URL<input name="product_url" type="url" placeholder="https://"><div class="hint">Where “Try it” sends hackers. Clicks are tracked.</div></label></div>
      </div>
      <div data-for="judge" class="stack">
        <label>Judge code<input name="judge_code" autocomplete="off"><div class="hint">Organizers hand these out. Demo code: <span class="mono">judge-demo</span></div></label>
      </div>
      <div data-for="hacker" class="stack">
        <label>Skills<input name="skills" placeholder="python, react, design"><div class="hint">Comma-separated. This is what teams match on.</div></label>
        <label>Interests<input name="interests" placeholder="ai, fintech, accessibility"></label>
        <label>One-line bio<input name="bio" maxlength="280"></label>
      </div>
      <label>Timezone<select name="tz">${tzOptions(browserTz())}</select></label>
      <button class="btn lg" type="submit">Let's go</button>
    </form>
    <form class="stack" id="login" hidden>
      <label>Handle<input name="handle" required placeholder="ada"></label>
      <button class="btn" type="submit">Sign in</button>
      <p class="small muted" style="margin:0">Demo mode: sign-in is handle-only. Production would use MyMLH / GitHub OAuth.</p>
    </form>
  </div>
  <aside class="card flat"><h3>Try a demo account</h3><p class="small muted">Jump in as someone from the seed data.</p><div class="stack">
    ${demo.map(([h, l]) => `<button class="btn ghost" style="width:100%;justify-content:flex-start" data-act="login-as" data-handle="${h}">@${h} <span class="muted small" style="font-weight:400">${l}</span></button>`).join('')}
  </div></aside></div>`, () => {
    const signup = app.querySelector('#signup');
    const sync = () => {
      const role = signup.querySelector('input[name=role]:checked').value;
      signup.querySelectorAll('[role=radiogroup] label').forEach((l) => l.classList.toggle('on', l.querySelector('input').checked));
      signup.querySelectorAll('[data-for]').forEach((el) => { el.hidden = el.dataset.for !== role; });
      signup.querySelector('[name=org]').required = role === 'sponsor';
      signup.querySelector('[name=judge_code]').required = role === 'judge';
    };
    signup.addEventListener('change', sync);
    sync();
    app.querySelectorAll('[data-tab]').forEach((b) => {
      b.onclick = () => {
        app.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('on', x === b));
        app.querySelector('#signup').hidden = b.dataset.tab !== 'signup';
        app.querySelector('#login').hidden = b.dataset.tab !== 'login';
      };
    });
    onSubmit('#signup', async (v) => {
      await api('/signup', { ...v, tz: +v.tz, skills: splitList(v.skills), interests: splitList(v.interests) });
      await refreshMe();
      toast(`Welcome, ${me.name.split(' ')[0]}!`);
      location.hash = home();
    });
    onSubmit('#login', async (v) => { await login(v.handle); });
  }];
}

const home = () => ({ sponsor: '#/sponsor', judge: '#/judge' }[me.role] || '#/teams');

async function login(handle) {
  await api('/login', { handle });
  await refreshMe();
  toast(`Signed in as @${me.handle}`);
  location.hash = home();
  render();
}

// Demo mode: the server approves join requests on the owner's behalf after a short wait.
async function awaitApproval(el, tid, seconds) {
  el.disabled = true;
  el.textContent = 'Waiting for approval…';
  toast(`Request sent — waiting for ${el.dataset.name} to approve…`);
  const deadline = Date.now() + seconds * 1000 + 6000;
  await new Promise((ok) => setTimeout(ok, seconds * 1000));
  while (Date.now() < deadline) {
    const t = (await api(`/teams/${tid}`)).team;
    if (t.members.some((m) => m.id === me.id)) {
      await refreshMe();
      toast(`You're in! Welcome to ${t.name} 🎉`);
      location.hash = `#/t/${tid}/room`;
      return;
    }
    await new Promise((ok) => setTimeout(ok, 500));
  }
  toast('Still pending — the team owner will decide');
  render();
}

// ---------- actions ----------

const actions = {
  menu: () => nav.classList.toggle('open'),
  buildmate: () => bmToggle(true),
  async logout() { await api('/logout', {}); me = null; renderNav(); location.hash = '#/'; },
  'login-as': (el) => login(el.dataset.handle),
  scroll: (el) => document.getElementById(el.dataset.target)?.scrollIntoView({ behavior: 'smooth' }),
  async try(el) {
    const w = window.open('', '_blank');
    const { url } = await api(`/challenges/${el.dataset.id}/click`, {});
    if (w && url) { w.opener = null; w.location = url; } else if (w) w.close();
  },
  async 'step-out'() { await api('/floor/leave', {}); await refreshMe(); toast('Stepped out — see you soon'); render(); },
  async highfive(el) {
    if (!me) { location.hash = '#/join'; return; }
    const r = await api(`/posts/${el.dataset.id}/highfive`, {});
    el.classList.toggle('on', r.on);
    el.querySelector('b').textContent = r.count;
  },
  reply(el) {
    if (!me) { location.hash = '#/join'; return; }
    const helping = el.dataset.kind === 'help' && el.textContent.trim() === 'I can help';
    modal(helping ? `Help ${el.dataset.name}` : `Reply to ${el.dataset.name}`,
      `<label>${helping ? 'Your suggestion, or offer to hop on a call' : 'Reply'}<textarea name="text" required maxlength="500"></textarea></label>`,
      helping ? 'Send help' : 'Reply', async (v) => { await api(`/posts/${el.dataset.id}/reply`, v); toast('Sent'); render(); });
  },
  resolve(el) {
    const helpers = JSON.parse(el.dataset.helpers);
    modal('Who got you unstuck?', `<label>They'll get +1 helper karma on their profile<select name="helper_id">
      ${helpers.map(([id, name]) => `<option value="${id}">${esc(name)}</option>`).join('')}</select></label>`,
      'Mark solved 🙌', async (v) => { await api(`/posts/${el.dataset.id}/resolve`, { helper_id: +v.helper_id }); toast('Solved — karma sent 🙌'); render(); });
  },
  async watch(el) {
    if (!me) { location.hash = '#/join'; return; }
    const w = window.open('', '_blank');
    const r = await api(`/demos/${el.dataset.id}/watch`, {});
    if (r.status === 'upcoming') {
      w?.close();
      toast("Saved — you'll find it under Demos. Link opens when it starts.");
      render();
      return;
    }
    if (w) { w.opener = null; w.location = r.zoom_url; }
  },
  async 'cancel-demo'(el) {
    if (!confirm('Cancel this demo? Watchers will be notified.')) return;
    await api(`/demos/${el.dataset.id}/cancel`, {});
    toast('Demo cancelled'); render();
  },
  async claim(el) {
    const w = window.open('', '_blank');
    const r = await api(`/perks/${el.dataset.id}/claim`, {});
    if (w && r.link) { w.opener = null; w.location = r.link; } else { w?.close(); toast(r.details || 'Claimed!'); }
    render();
  },
  join(el) {
    modal(`Join ${el.dataset.name}`, `<label>Say hi — what would you work on?<textarea name="message" maxlength="400" placeholder="I can take the frontend and the demo video."></textarea></label>`,
      'Send request', async (v) => {
        const tid = el.dataset.id;
        const r = await api(`/teams/${tid}/join`, v);
        if (!r.auto_approve_in) { toast('Request sent'); render(); return; }
        awaitApproval(el, tid, r.auto_approve_in); // not awaited, so the dialog closes now
      });
  },

  invite(el) {
    modal(`Invite ${el.dataset.name}`, `<label>Message<textarea name="message" maxlength="400" placeholder="We'd love your help with…"></textarea></label>`,
      'Send invite', async (v) => { await api(`/teams/${el.dataset.team}/invite`, { ...v, user_id: +el.dataset.user }); toast('Invite sent'); render(); });
  },
  async decide(el) {
    const r = await api(`/requests/${el.dataset.id}`, { action: el.dataset.action });
    toast({ accept: 'Accepted — welcome to the team!', decline: 'Declined', cancel: 'Withdrawn' }[el.dataset.action]);
    await refreshMe();
    if (el.dataset.action === 'accept' && location.hash.startsWith('#/inbox')) location.hash = `#/t/${r.team_id}`;
    else render();
  },
  async leave(el) {
    if (!confirm('Leave this team? If you are the last member, the team is deleted.')) return;
    await api(`/teams/${el.dataset.id}/leave`, {});
    await refreshMe();
    toast('You left the team');
    location.hash = `#/c/${el.dataset.c}`;
  },
  async vote(el) {
    if (!me) { location.hash = '#/join'; return; }
    const r = await api(`/submissions/${el.dataset.id}/vote`, {});
    el.classList.toggle('on', r.voted);
    el.querySelector('b').textContent = r.votes;
  },
};

document.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  e.preventDefault();
  try { await actions[el.dataset.act](el); } catch (err) { toast(err.message, true); }
});

// ---------- router ----------

const routes = [
  [/^$/, viewHome],
  [/^(?:challenges|hackathons)(?:\/(live|upcoming|past|all))?$/, viewChallenges],
  [/^c\/(\d+)$/, viewChallenge],
  [/^teams$/, viewTeams],
  [/^t\/(\d+)$/, viewTeam],
  [/^t\/(\d+)\/room$/, viewRoom],
  [/^t\/(\d+)\/stage$/, viewStage],
  [/^people$/, viewBuilders],
  [/^builders$/, viewBuilders],
  [/^u\/([a-z0-9_-]+)$/, viewPerson],
  [/^inbox$/, viewInbox],
  [/^demos$/, viewDemos],
  [/^floor$/, viewFloor],
  [/^notifications$/, viewNotifications],
  [/^judge$/, viewJudge],
  [/^live(?:\/([a-z0-9-]+))?$/, viewLive],
  [/^me$/, viewProfile],
  [/^sponsor$/, viewSponsor],
  [/^join$/, viewJoin],
];

// "My team" goes straight to the Team Room; with teams in several challenges it becomes a small menu.
function myTeamNav() {
  const teams = me?.teams || [];
  if (!teams.length) return '';
  const here = location.hash.match(/^#\/t\/(\d+)/)?.[1];
  const active = teams.some((t) => String(t.id) === here) ? 'active' : '';
  if (teams.length === 1) {
    const t = teams[0];
    return `<a href="#/t/${t.id}/room" class="my-team ${active}" title="${esc(t.name)} · ${esc(t.challenge_title)}">🚪 My team <span class="muted">· ${esc(t.name)}</span></a>`;
  }
  return `<details class="nav-menu ${active}"><summary class="my-team">🚪 My teams <span class="muted">· ${teams.length}</span></summary><div class="menu">
    ${teams.map((t) => `<a href="#/t/${t.id}/room" class="${String(t.id) === here ? 'active' : ''}"><b>${esc(t.name)}</b><span class="small muted">${esc(t.challenge_title)}</span></a>`).join('')}
  </div></details>`;
}

function renderNav() {
  const path = location.hash.replace(/^#\/?/, '').split(/[/?]/)[0];
  const link = (href, label, extra = '') =>
    `<a href="#/${href}" class="${path === href.split('/')[0] ? 'active' : ''}">${label}${extra}</a>`;
  let html = myTeamNav() + link('challenges', 'Hackathons') + link('teams', 'Find a team') + link('builders', 'Find a builder');
  if (me) {
    if (me.role === 'judge') html += link('judge', 'Judging');
    if (me.role === 'hacker') html += link('inbox', 'Inbox', me.inbox ? `<span class="badge">${me.inbox}</span>` : '');
    html += link('notifications', '<span aria-label="Notifications">🔔</span>', me.unread ? `<span class="badge">${me.unread}</span>` : '');
    html += link('me', `@${esc(me.handle)}`);
  } else {
    html += `<a href="#/join" class="btn sm" style="color:var(--accent-ink);background:var(--accent)">Join</a>`;
  }
  nav.innerHTML = html;
}

async function render() {
  const seq = ++renderSeq;
  clearInterval(floorTimer);
  leaveRoom();
  leaveStage();
  stopLive();
  const [path, query] = location.hash.replace(/^#\/?/, '').split('?');
  const params = new URLSearchParams(query || '');
  nav.classList.remove('open');
  renderNav();
  const found = routes.find(([rx]) => rx.test(path));
  if (!found) { app.innerHTML = empty('Page not found. <a href="#/">Go home</a>'); return; }
  const args = path.match(found[0]).slice(1);
  if (!app.innerHTML) app.innerHTML = '<div class="loading">Loading…</div>';
  try {
    // Views take their route captures (missing optional ones as undefined) followed by the query params.
    const out = await found[1](...(args.length ? args : [params]), params);
    if (seq !== renderSeq) return;
    const [html, after] = Array.isArray(out) ? out : [out];
    app.innerHTML = html;
    if (after) after();
  } catch (err) {
    if (seq !== renderSeq) return;
    if (err.status === 401) { location.hash = '#/join'; return; }
    app.innerHTML = empty(esc(err.message));
  }
}

let lastPath = null;
window.addEventListener('hashchange', () => {
  const path = location.hash.split('?')[0];
  if (path !== lastPath) window.scrollTo(0, 0);
  lastPath = path;
  render();
});

// Poll for new notifications (demo going live, invites…) and surface them as a toast.
setInterval(async () => {
  if (!me || document.hidden) return;
  const before = me.unread;
  try { await refreshMe(); } catch { return; }
  if (me && me.unread > before) {
    const latest = (await api('/notifications')).notifications[0];
    if (latest) toast(latest.text);
  }
}, 20000);

startClock();
mountBuildmate();
refreshMe().catch(() => {}).finally(render);
