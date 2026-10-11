'use strict';
// Builders directory: find teammates by skill, place, availability and fit. Shared pieces (match score, builder
// card, profile and invite dialogs) are also used by the home page and Buildmate.
// Loaded before app.js; uses its globals (api, esc, me, toast, avatar, …) at call time.

const B_EXPERIENCE = ['Early career', 'Mid-level', 'Senior'];
const B_COLLAB = ['Remote', 'Hybrid', 'Local'];
const B_SEEKING = ['Teammates', 'Co-founders'];
const B_ROLES = ['Full-stack engineer', 'AI / ML engineer', 'Product designer', 'Backend engineer', 'Frontend engineer'];
let builderState = { saved: new Set(), connected: new Set(), loadedFor: null };
let builderFilters = { q: '', matching: false, savedOnly: false };
let builderCache = [];

const lowerSet = (xs) => new Set((xs || []).map((x) => String(x).toLowerCase()));
const firstName = (b) => b.name.split(' ')[0];
const place = (b) => [b.city, b.country].filter(Boolean).join(', ') || 'Somewhere on Earth';

async function loadBuilderState(force) {
  if (!me) { builderState = { saved: new Set(), connected: new Set(), loadedFor: null }; return builderState; }
  if (!force && builderState.loadedFor === me.id) return builderState;
  const s = await api('/saved');
  builderState = { saved: new Set(s.saved), connected: new Set(s.connected), loadedFor: me.id };
  return builderState;
}

// Compatibility, not a probability: complementary skills, shared interests, similar commitment, nearby time zones.
function matchBuilder(self, other) {
  const mine = lowerSet(self.skills);
  const complementary = other.skills.filter((s) => !mine.has(s.toLowerCase()));
  const interests = lowerSet(self.interests);
  const common = other.interests.filter((s) => interests.has(s.toLowerCase()));
  const overlap = Math.abs((other.hours || 0) - (self.hours || 0)) <= 10 && other.hours && self.hours;
  const near = Math.abs((other.tz || 0) - (self.tz || 0)) <= 5;
  const score = Math.min(98, 35 + (complementary.length ? 20 : 0) + common.length * 12 + (overlap ? 10 : 0) + (near ? 8 : 0) + (other.collab === 'Remote' ? 5 : 0));
  const reasons = [
    complementary.length ? `Adds ${complementary.slice(0, 2).join(' + ')}` : 'Shared technical foundation',
    ...(common.length ? [`Both into ${common.join(' & ')}`] : []),
    ...(overlap ? [`Compatible ${other.hours}h/week commitment`] : []),
    ...(near ? ['Time zones within 5 hours'] : []),
  ];
  return { score, reasons };
}

function builderCard(b, opts = {}) {
  const saved = builderState.saved.has(b.id);
  const m = opts.match && me && me.role === 'hacker' && b.id !== me.id ? matchBuilder(me, b) : null;
  return `<article class="builder-card" data-builder="${b.id}">
    <div class="card-top">${avatar(b, 'lg')}
      ${me && b.id !== me.id ? `<button type="button" class="icon-btn ${saved ? 'on' : ''}" data-b="save" data-id="${b.id}" aria-label="${saved ? 'Unsave' : 'Save'} ${esc(b.name)}" aria-pressed="${saved}">${saved ? '★' : '☆'}</button>` : ''}</div>
    <button type="button" class="name-link" data-b="profile" data-id="${b.id}">${esc(b.name)} <span aria-hidden="true">↗</span></button>
    <p class="b-role">${esc(b.title || 'Builder')}</p>
    <p class="b-loc">⌖ ${esc(place(b))}</p>
    ${chips(b.skills)}
    <p class="b-bio">${esc(b.bio || 'Ready for the next adventure.')}</p>
    ${m ? `<div class="b-match">✦ ${m.score}% fit · ${esc(m.reasons[0])}</div>` : ''}
    <div class="card-bottom"><span>${b.looking ? '<i class="dot"></i>Looking for a team' : `${b.hours ? `${b.hours}h / week` : 'On a team'}`}</span>
      <button type="button" data-b="profile" data-id="${b.id}">Meet ${esc(firstName(b))} ↗</button></div>
  </article>`;
}

function builderById(id) {
  return builderCache.find((b) => b.id === +id);
}

async function openBuilderProfile(id) {
  await loadBuilderState();
  let b = builderById(id);
  if (!b) {
    const all = (await api('/people')).people;
    builderCache = all;
    b = builderById(id);
  }
  if (!b) return;
  const m = me && me.role === 'hacker' && b.id !== me.id ? matchBuilder(me, b) : null;
  const tz = `UTC${b.tz >= 0 ? '+' : ''}${b.tz}`;
  const d = document.createElement('dialog');
  d.className = 'profile-dialog';
  d.innerHTML = `<button type="button" class="dialog-close" aria-label="Close profile">✕</button>
    <span class="eyebrow">Builder profile</span>
    <div class="profile-heading">${avatar(b, 'xl')}<div><h2>${esc(b.name)}</h2><p>${esc(b.title || 'Builder')} · <a href="#/u/${esc(b.handle)}">@${esc(b.handle)}</a></p></div></div>
    <p class="b-loc">⌖ ${esc(place(b))} · ${tz}${b.linkedin ? ` · <a href="${esc(b.linkedin)}" target="_blank" rel="noopener noreferrer">LinkedIn ↗</a>` : ''}</p>
    <p class="profile-bio">${esc(b.bio || 'Ready for the next adventure.')}</p>
    ${chips(b.skills)}
    <div class="profile-details">
      <div><span>Commitment</span><strong>${b.hours ? `${b.hours}h / week` : '—'}</strong><small>${esc(b.collab || 'Flexible')} collaboration</small></div>
      <div><span>Looking for</span><strong>${esc(b.seeking || (b.looking ? 'A team' : 'On a team'))}</strong><small>${esc(b.experience || 'Experience not listed')}</small></div>
    </div>
    ${b.interests.length ? `<h4>What they care about</h4>${chips(b.interests)}` : ''}
    ${m ? `<div class="match-box"><b>✦ ${m.score}% match with you</b>${m.reasons.map((r) => `<p>✓ ${esc(r)}</p>`).join('')}</div>` : ''}
    ${me && me.role === 'hacker' && b.id !== me.id ? `<div class="row profile-actions">
        <button type="button" class="btn" data-p="connect">${builderState.connected.has(b.id) ? 'Connected ✓' : 'Connect ↗'}</button>
        <button type="button" class="btn ghost" data-p="invite">Invite to team +</button>
        <button type="button" class="btn ghost" data-p="save">${builderState.saved.has(b.id) ? '★ Saved' : '☆ Save'}</button></div>`
      : !me ? '<p class="small muted"><a href="#/join">Sign in</a> to connect, save, or invite.</p>' : ''}
    <p class="fine-print">Connect sends ${esc(firstName(b))} a notification. Invites arrive in their inbox.</p>`;
  document.body.append(d);
  d.addEventListener('close', () => d.remove());
  d.addEventListener('click', async (e) => {
    if (e.target === d || e.target.closest('.dialog-close')) { d.close(); return; }
    const a = e.target.closest('[data-p]');
    if (!a) return;
    try {
      if (a.dataset.p === 'connect') {
        const r = await api(`/people/${b.id}/connect`, {});
        builderState.connected.add(b.id);
        a.textContent = 'Connected ✓';
        toast(r.already ? 'Already connected' : r.mutual ? `You and ${firstName(b)} are connected 🤝` : `${firstName(b)} got your hello`);
      } else if (a.dataset.p === 'save') {
        const r = await toggleSaveBuilder(b.id);
        a.textContent = r ? '★ Saved' : '☆ Save';
      } else if (a.dataset.p === 'invite') {
        d.close();
        openInviteBuilder(b);
      }
    } catch (err) { toast(err.message, true); }
  });
  d.showModal();
}

async function toggleSaveBuilder(id) {
  if (!me) { location.hash = '#/join'; return false; }
  const r = await api(`/people/${id}/save`, {});
  if (r.saved) builderState.saved.add(+id); else builderState.saved.delete(+id);
  document.querySelectorAll(`[data-b="save"][data-id="${id}"]`).forEach((btn) => {
    btn.classList.toggle('on', r.saved);
    btn.textContent = r.saved ? '★' : '☆';
    btn.setAttribute('aria-pressed', String(r.saved));
  });
  const counter = document.getElementById('saved-count');
  if (counter) counter.textContent = builderState.saved.size;
  toast(r.saved ? 'Saved to your shortlist' : 'Removed from your shortlist');
  return r.saved;
}

async function openInviteBuilder(b) {
  if (!me) { location.hash = '#/join'; return; }
  const mine = (await api(`/people/${me.handle}`)).teams.filter((t) => t.owner_id === me.id && t.challenge_status !== 'past');
  const d = document.createElement('dialog');
  d.className = 'profile-dialog';
  d.innerHTML = `<button type="button" class="dialog-close" aria-label="Close">✕</button><span class="eyebrow">Make the first move</span>
    <h2>Invite ${esc(firstName(b))}.</h2><p class="muted">Pick one of your teams. They'll get an invite in their inbox.</p>
    <div class="invite-list">${mine.length ? mine.map((t) => `<button type="button" class="invite-row" data-team="${t.id}" ${t.open ? '' : 'disabled'}>
        <span><strong>${esc(t.name)}</strong><small>${esc(t.challenge_title)} · ${t.members.length}/${t.max_size}${t.open ? '' : ' · full or shipped'}</small></span><b>↗</b></button>`).join('')
      : `<div class="empty">You don't own a team yet. <a href="#/challenges">Start one on a challenge</a>, then come back.</div>`}</div>`;
  document.body.append(d);
  d.addEventListener('close', () => d.remove());
  d.addEventListener('click', async (e) => {
    if (e.target === d || e.target.closest('.dialog-close')) { d.close(); return; }
    const row = e.target.closest('[data-team]');
    if (!row || row.disabled) return;
    try {
      await api(`/teams/${row.dataset.team}/invite`, { user_id: b.id, message: `Saw your profile — want to build with us?` });
      row.disabled = true;
      row.querySelector('b').textContent = '✓';
      toast(`Invite sent to ${firstName(b)}`);
    } catch (err) { toast(err.message, true); }
  });
  d.showModal();
}

// Card clicks anywhere (home, builders page, Buildmate results) route through here.
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-stop]')) return;  // e.g. a LinkedIn link inside a person tile
  const t = e.target.closest('[data-b]');
  if (!t) return;
  e.preventDefault();
  if (t.dataset.b === 'profile') openBuilderProfile(+t.dataset.id).catch((err) => toast(err.message, true));
  else if (t.dataset.b === 'save') toggleSaveBuilder(+t.dataset.id).catch((err) => toast(err.message, true));
});

// ---------- the Builders page ----------

function filteredBuilders() {
  const f = builderFilters;
  const q = f.q.toLowerCase();
  let list = builderCache.filter((b) => {
    const hay = [b.name, b.handle, b.city, b.country, b.title, ...b.skills, ...b.interests].join(' ').toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (f.savedOnly && !builderState.saved.has(b.id)) return false;
    if (f.country && b.country !== f.country) return false;
    if (f.city && b.city !== f.city) return false;
    if (f.skill && !b.skills.includes(f.skill)) return false;
    if (f.interest && !b.interests.includes(f.interest)) return false;
    if (f.title && b.title !== f.title) return false;
    if (f.experience && b.experience !== f.experience) return false;
    if (f.collab && b.collab !== f.collab) return false;
    if (f.seeking && b.seeking !== f.seeking) return false;
    if (f.hours && (b.hours || 0) < +f.hours) return false;
    if (f.zone && me && Math.abs(b.tz - me.tz) > +f.zone) return false;
    if (f.lookingOnly && !b.looking) return false;
    return true;
  });
  if (me) list = list.filter((b) => b.id !== me.id);
  if (f.matching && me && me.role === 'hacker') list = [...list].sort((a, b) => matchBuilder(me, b).score - matchBuilder(me, a).score);
  return list;
}

function builderSelect(key, label, options) {
  return `<label class="filter"><span>${label}</span><select data-f="${key}"><option value="">All ${label.toLowerCase()}</option>
    ${options.map((o) => `<option ${builderFilters[key] === o ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></label>`;
}

function builderFilterPanel() {
  const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const cities = uniq(builderCache.filter((b) => !builderFilters.country || b.country === builderFilters.country).map((b) => b.city));
  return `<h3>⚙ Make it your kind of people</h3>
    ${builderSelect('country', 'Country', uniq(builderCache.map((b) => b.country)))}
    ${builderSelect('city', 'City', cities)}
    ${builderSelect('skill', 'Skill', uniq(builderCache.flatMap((b) => b.skills)))}
    ${builderSelect('interest', 'Interest', uniq(builderCache.flatMap((b) => b.interests)))}
    ${builderSelect('title', 'Role', B_ROLES)}
    ${builderSelect('experience', 'Experience', B_EXPERIENCE)}
    ${builderSelect('collab', 'Collaboration', B_COLLAB)}
    ${builderSelect('seeking', 'Looking for', B_SEEKING)}
    <label class="filter"><span>Weekly availability</span><select data-f="hours"><option value="">Any commitment</option>
      ${[10, 15, 20, 30].map((n) => `<option value="${n}" ${+builderFilters.hours === n ? 'selected' : ''}>${n}+ hours / week</option>`).join('')}</select></label>
    <label class="filter"><span>Time zone compatibility</span><select data-f="zone" ${me ? '' : 'disabled'}><option value="">Anywhere in the world</option>
      <option value="3" ${builderFilters.zone === '3' ? 'selected' : ''}>Within 3 hours of me</option><option value="5" ${builderFilters.zone === '5' ? 'selected' : ''}>Within 5 hours of me</option></select></label>
    <label class="filter-check"><input type="checkbox" data-f="lookingOnly" ${builderFilters.lookingOnly ? 'checked' : ''}> Only people looking for a team</label>
    <button type="button" class="link-btn" data-bf="reset">Reset filters ✕</button>`;
}

function paintBuilderResults() {
  const list = filteredBuilders();
  document.getElementById('b-count').textContent = list.length;
  document.getElementById('b-mode').textContent = builderFilters.matching && me ? `Matched to you · ${esc(me.name)}` : 'Global minds. Local connections.';
  document.getElementById('b-results').innerHTML = list.length ? list.map((b) => builderCard(b, { match: builderFilters.matching })).join('')
    : `<div class="empty" style="grid-column:1/-1"><h3>No builders found</h3><p>Try another skill or broaden your location.</p>
       <button type="button" class="btn ghost" data-bf="reset">Clear filters</button></div>`;
}

async function viewBuilders(params) {
  if (params?.get('skill')) builderFilters = { ...builderFilters, skill: params.get('skill') };
  if (params?.get('looking') === '1') builderFilters = { ...builderFilters, lookingOnly: true };
  if (params?.get('q')) builderFilters = { ...builderFilters, q: params.get('q') };
  const [people] = await Promise.all([api('/people'), loadBuilderState()]);
  builderCache = people.people;
  const canMatch = me && me.role === 'hacker';
  return [`<div class="page-intro"><span class="eyebrow">Your people are out there</span><h1>Find your missing piece.</h1>
      <p>Different skills. Shared ambition. Meet the people you could build with.</p></div>
    <div class="directory-toolbar">
      <label class="search-box"><span aria-hidden="true">⌕</span><input id="b-q" aria-label="Search builders" placeholder="Search by name, city, skill, or interest…" value="${esc(builderFilters.q)}"></label>
      <button type="button" class="btn ghost ${builderFilters.matching ? 'on' : ''}" data-bf="match" ${canMatch ? '' : 'title="Sign in as a hacker to see matches"'}>✦ ${builderFilters.matching ? 'Best matches first' : 'Find my matches'}</button>
      ${me ? `<button type="button" class="btn ghost ${builderFilters.savedOnly ? 'on' : ''}" data-bf="saved">☆ Saved (<span id="saved-count">${builderState.saved.size}</span>)</button>` : ''}
    </div>
    <div class="directory-layout">
      <aside class="filter-panel" id="b-filters">${builderFilterPanel()}</aside>
      <div><div class="result-bar"><span><strong id="b-count">0</strong> builders to meet</span><span id="b-mode"></span></div>
        <div class="builder-grid" id="b-results"></div></div>
    </div>`, () => {
    paintBuilderResults();
    const page = document.querySelector('.directory-layout').parentElement;
    document.getElementById('b-q').addEventListener('input', (e) => { builderFilters.q = e.target.value; paintBuilderResults(); });
    document.getElementById('b-filters').addEventListener('change', (e) => {
      const key = e.target.dataset.f;
      if (!key) return;
      builderFilters[key] = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
      if (key === 'country') { builderFilters.city = ''; document.getElementById('b-filters').innerHTML = builderFilterPanel(); }
      paintBuilderResults();
    });
    page.addEventListener('click', (e) => {
      const b = e.target.closest('[data-bf]');
      if (!b) return;
      if (b.dataset.bf === 'reset') {
        builderFilters = { q: '', matching: builderFilters.matching, savedOnly: false };
        document.getElementById('b-q').value = '';
        document.getElementById('b-filters').innerHTML = builderFilterPanel();
      } else if (b.dataset.bf === 'match') {
        if (!canMatch) { toast('Sign in as a hacker to see who complements you'); return; }
        builderFilters.matching = !builderFilters.matching;
        b.classList.toggle('on', builderFilters.matching);
        b.textContent = `✦ ${builderFilters.matching ? 'Best matches first' : 'Find my matches'}`;
      } else if (b.dataset.bf === 'saved') {
        builderFilters.savedOnly = !builderFilters.savedOnly;
        b.classList.toggle('on', builderFilters.savedOnly);
      }
      paintBuilderResults();
    });
  }];
}

// Home page section: four people worth meeting (best fits when signed in).
async function missingPieceSection() {
  const [people] = await Promise.all([api('/people?looking=1'), loadBuilderState().catch(() => null)]);
  builderCache = people.people.length ? people.people : builderCache;
  let list = people.people.filter((b) => !me || b.id !== me.id);
  const canMatch = me && me.role === 'hacker';
  if (canMatch) list = [...list].sort((a, b) => matchBuilder(me, b).score - matchBuilder(me, a).score);
  list = list.slice(0, 4);
  if (!list.length) return '';
  return `<section class="section">
    <div class="section-head"><div><span class="eyebrow">Good people. Great possibilities.</span><h2>Find your missing piece.</h2>
      <p>A designer to your developer. A dreamer to your doer.${canMatch ? ' Ranked by how well they complement you.' : ''}</p></div><a href="#/builders">Meet all builders ↗</a></div>
    <div class="builder-grid home-builders">${list.map((b) => builderCard(b, { match: canMatch })).join('')}</div></section>`;
}
