'use strict';
// Buildmate: a floating assistant that finds builders, teams, events, projects and sponsor challenges.
// Ported from the companion Next.js demo's copilot: a deterministic keyword/rule search (no LLM), so it
// never invents matches — when nothing fits it says so. Follow-ups ("only remote", "make that worldwide")
// refine the previous search. Chat history lives in this browser only.
// Loaded before app.js; uses its globals (api, esc, me, toast, …) at call time.

const BM_KEY = 'aoh-buildmate-v1';
const BM_BLANK = { kind: 'builders', count: 3, skills: [], anySkill: false, location: '', interest: '', role: '', experience: '', mode: '', hours: 0, goal: '', savedOnly: false };
const BM_STARTERS = ['Find 3 React builders worldwide', 'Find Python people in New York', 'I am building a climate app worldwide',
  'Find in-person hackathons in Berlin', 'Teams that need design', 'Show projects using Python'];
const BM_INTRO = { id: 'intro', role: 'assistant', text: 'Hi, I’m Buildmate. Tell me what you’re building and who you need. I can search builders, teams, events, projects, and sponsor challenges. Try a skill, a city, and how many people you want.' };

const bmNorm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
const bmHas = (text, word) => new RegExp(`(^|[^a-z0-9])${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`, 'i').test(text);
const BM_SKILLS = { React: ['react', 'reactjs', 'react.js'], TypeScript: ['typescript', 'ts'], 'Next.js': ['next.js', 'nextjs', 'next js'], Python: ['python'], PyTorch: ['pytorch'], AI: ['ai', 'artificial intelligence'], Figma: ['figma'], 'UX research': ['ux research', 'user research'], 'Design systems': ['design systems'], Go: ['go', 'golang'], PostgreSQL: ['postgresql', 'postgres', 'sql'], Docker: ['docker'], CSS: ['css'], Accessibility: ['accessibility', 'accessible'], Rust: ['rust'], 'Node.js': ['node.js', 'nodejs', 'node'], Java: ['java'], 'C++': ['c++'], Swift: ['swift'], Kotlin: ['kotlin'], ML: ['ml', 'machine learning'], NLP: ['nlp'], Design: ['design'] };
const BM_DOMAINS = { 'Climate tech': ['climate', 'carbon', 'sustainability', 'environment', 'green energy'], Healthcare: ['healthcare', 'health', 'medical', 'care'], Education: ['education', 'learning', 'edtech', 'students'], 'Developer tools': ['developer tools', 'devtools', 'developer tooling'], 'AI for good': ['ai for good', 'social impact', 'ethical ai'] };
const BM_ROLES = { 'Product designer': ['designer', 'designers', 'product design', 'ux designer', 'ux design'], 'Frontend engineer': ['frontend', 'front-end', 'front end'], 'Backend engineer': ['backend', 'back-end', 'back end'], 'Full-stack engineer': ['fullstack', 'full-stack', 'full stack'], 'AI / ML engineer': ['ml engineer', 'machine learning engineer', 'ai engineer'] };
const bmHasSkill = (b, s) => b.skills.some((x) => x.toLowerCase() === s.toLowerCase());
const bmHasInterest = (xs, i) => xs.some((x) => x.toLowerCase() === i.toLowerCase());

function bmParse(prompt, data, previous) {
  const text = bmNorm(prompt);
  const followup = Boolean(previous) && (/\b(only|instead|also|make (it|that)|what about|same|more|those|them)\b/.test(text) || /^(worldwide|globally|remote|senior|any role|any skill)\b/.test(text) || text.split(/\s+/).length <= 3);
  const c = followup ? { ...previous, skills: [...previous.skills] } : { ...BM_BLANK, skills: [] };
  if (/\b(reset|start over|new search)\b/.test(text)) return { ...BM_BLANK, skills: [] };
  if (/\b(database|everything|capabilities|what can you|all data)\b/.test(text)) c.kind = 'overview';
  else if (/\b(hackathons?|events?)\b/.test(text)) c.kind = 'events';
  else if (/\b(sponsors?|sponsored|campaigns?|challenges?)\b/.test(text)) c.kind = 'challenges';
  else if (/\b(projects?|showcase|prototypes?)\b/.test(text) && !/\b(my|our|idea|building|build|want|need)\b/.test(text)) c.kind = 'projects';
  else if (/\b(teams?|crews?)\b/.test(text) && !/\b(my|our|idea|building|build)\b/.test(text)) c.kind = 'teams';
  else if (/\b(people|builders?|teammates?|cofounders?|co-founders?|designers?|engineers?)\b/.test(text)) c.kind = 'builders';
  if (previous && c.kind !== previous.kind) Object.assign(c, { ...BM_BLANK, kind: c.kind, skills: [] });
  const amount = text.match(/\b(\d{1,2})\s*(people|builders?|teammates?|engineers?|designers?|teams?|events?|hackathons?|projects?|results?)\b/) || text.match(/\b(top|first|show|find me)\s+(\d{1,2})\b/);
  if (amount) c.count = Math.max(1, Math.min(10, Number(/^\d+$/.test(amount[1]) ? amount[1] : amount[2])));
  else for (const [word, n] of Object.entries({ one: 1, two: 2, three: 3, four: 4, five: 5 })) if (bmHas(text, word)) c.count = n;
  const skills = Object.entries(BM_SKILLS).filter(([, names]) => names.some((a) => bmHas(text, a))).map(([skill]) => skill);
  // Keep explicit skill requirements even when nobody here has that skill.
  const requested = text.match(/\bwith\s+(?:skills?(?:\s+in)?\s*:?\s*)?(.+?)(?=\s+(?:in|near|for|who|available|worldwide|globally)\b|[!?]|$)/)?.[1];
  if (requested) {
    for (const phrase of requested.split(/\s+(?:and|or)\s+|,/)) {
      const skill = phrase.replace(/\b(experience|expertise|skills|knowledge|development)\b/g, '').trim();
      if (skill && !/\d|\b(my|a|an|their|these|those|any|all|interest|hours|week|availability)\b/.test(skill)
        && !Object.values(BM_SKILLS).flat().some((a) => bmHas(skill, a)) && !Object.values(BM_DOMAINS).flat().some((a) => bmHas(skill, a))) skills.push(skill);
    }
  }
  // "design" is both a skill and a role word; prefer the role when someone asks for designers.
  if (skills.includes('Design') && /\bdesigners?\b/.test(text)) skills.splice(skills.indexOf('Design'), 1);
  if (skills.length) c.skills = followup && bmHas(text, 'also') ? [...new Set([...c.skills, ...skills])] : skills;
  if (/\b(no skill|any skill|all skills)\b/.test(text)) c.skills = [];
  if (skills.length) c.anySkill = /\bor\b|\bany of\b/.test(text);
  if (/\b(show all|all sponsor)\b/.test(text)) { c.skills = []; c.count = 10; }
  const locations = [...new Set(data.builders.flatMap((b) => [b.city, b.country]).concat(data.events.map((e) => e.location)))].filter((l) => l && l !== 'Worldwide').sort((a, b) => b.length - a.length);
  const found = locations.find((l) => bmHas(text, bmNorm(l)));
  if (found) c.location = found;
  if (/\b(nyc|new york city|manhattan)\b/.test(text)) c.location = 'New York';
  if (/\b(sf|san fran)\b/.test(text)) c.location = 'San Francisco';
  if (/\b(usa|us|united states)\b/.test(text)) c.location = 'United States';
  if (/\b(uk)\b/.test(text)) c.location = 'United Kingdom';
  if (/\b(worldwide|global|globally|anywhere|world|international|no location)\b/.test(text)) c.location = '';
  // Don't silently turn an unknown city into a worldwide search.
  if (!found && !/\b(nyc|manhattan|usa|uk|worldwide|global|globally|anywhere|world|international)\b/.test(text)) {
    const unknown = prompt.match(/\b(?:in|near|located in|based in)\s+([A-Za-zÀ-ž][A-Za-zÀ-ž .-]*?)(?=\s+(?:with|who|for|using|and|or|to|available)\b|[,.!?]|$)/i)?.[1]?.trim();
    if (unknown && !Object.values(BM_SKILLS).flat().some((a) => bmNorm(unknown) === a) && !['my project', 'a team', 'ai', 'person'].includes(bmNorm(unknown))) c.location = unknown;
  }
  for (const [domain, names] of Object.entries(BM_DOMAINS)) if (names.some((a) => bmHas(text, a))) c.interest = domain;
  if (/\b(any interest|all interests|any domain)\b/.test(text)) c.interest = '';
  for (const [role, names] of Object.entries(BM_ROLES)) if (names.some((a) => bmHas(text, a))) { c.role = role; if (bmHas(text, 'instead')) c.skills = []; }
  if (skills.length && followup && bmHas(text, 'instead')) c.role = '';
  if (/\b(any role|all roles)\b/.test(text)) c.role = '';
  if (bmHas(text, 'senior')) c.experience = 'Senior';
  else if (/\b(junior|early career|entry level)\b/.test(text)) c.experience = 'Early career';
  else if (/\b(mid-level|mid level)\b/.test(text)) c.experience = 'Mid-level';
  if (bmHas(text, 'remote')) c.mode = 'Remote';
  else if (bmHas(text, 'hybrid')) c.mode = 'Hybrid';
  else if (/\b(in person|in-person|local)\b/.test(text)) c.mode = c.kind === 'events' ? 'In person' : 'Local';
  else if (bmHas(text, 'online')) c.mode = 'Online';
  const hours = text.match(/\b(\d{1,2})\s*(?:\+\s*)?(?:hours?|hrs?|h)(?:\s*(?:\/|per|a)\s*week)?\b/);
  if (hours) c.hours = Number(hours[1]);
  if (/\b(saved|bookmarked|shortlist)\b/.test(text)) c.savedOnly = true;
  if (/\b(all builders|not just saved)\b/.test(text)) c.savedOnly = false;
  if (/\b(my project|my idea|our project|building|i want to build|i am building|i'm building|help me build|for a project|for an idea|for my|project idea)\b/.test(text)) { c.goal = prompt; c.kind = 'builders'; }
  return c;
}

function bmBuilderResult(b, c) {
  const reasons = [
    c.location ? `Located in ${b.city}, ${b.country}` : `Worldwide search · ${b.city || 'location not listed'}`,
    ...c.skills.filter((s) => bmHasSkill(b, s)).map((s) => `Has ${s}`),
    ...(c.interest ? [`Interested in ${c.interest}`] : []), ...(c.role ? [`Matches ${c.role}`] : []),
    ...(c.goal ? [`${b.role || 'Builder'} contributes ${b.skills.slice(0, 2).join(' + ')}`] : []),
    `${b.hours ? `${b.hours}h/week` : 'Hours not listed'} · ${b.mode || 'flexible'}${b.looking ? ' · looking for a team' : ''}`,
  ];
  return { kind: 'builders', id: b.id, title: b.name, subtitle: `${b.role || 'Builder'} · ${b.city || '—'}`, detail: b.bio, tags: b.skills, reasons };
}

function bmAnswer(prompt, data, previous) {
  const c = bmParse(prompt, data, previous);
  const filters = [...(c.location ? [c.location] : ['Worldwide']), ...c.skills, ...(c.anySkill && c.skills.length > 1 ? ['Any listed skill'] : []),
    ...[c.interest, c.role, c.experience, c.mode].filter(Boolean), ...(c.hours ? [`${c.hours}+ hours/week`] : []), ...(c.savedOnly ? ['Saved builders'] : [])];
  const reply = (text, results, suggestions) => ({ text, results, context: c, filters, suggestions });
  if (c.kind === 'overview') {
    return reply(`I can search ${data.builders.length} builders, ${data.teams.length} teams, ${data.events.length} events, ${data.projects.length} projects, and ${data.challenges.length} sponsor challenges. Tell me the skills, location, or project idea. I use rules and keyword matching—not an AI model—so I never make up matches.`,
      [], ['Find 3 React builders worldwide', 'Find in-person hackathons in Berlin', 'Show projects using Python']);
  }
  if (c.kind === 'builders') {
    let matches = data.builders.filter((b) => (!c.location || [b.city, b.country].some((l) => bmNorm(l || '') === bmNorm(c.location)))
      && (!c.skills.length || (c.anySkill ? c.skills.some((s) => bmHasSkill(b, s)) : c.skills.every((s) => bmHasSkill(b, s))))
      && (!c.interest || bmHasInterest(b.interests, c.interest)) && (!c.role || b.role === c.role) && (!c.experience || b.experience === c.experience)
      && (!c.mode || b.mode === c.mode) && (b.hours || 0) >= c.hours && (!c.savedOnly || data.saved.includes(b.id)));
    // People still looking for a team first, then by availability.
    matches.sort((a, b) => (b.looking - a.looking) || (b.hours || 0) - (a.hours || 0) || a.name.localeCompare(b.name));
    if (c.goal) {
      const diverse = [];
      const used = new Set();
      for (const b of matches) if (!used.has(b.role)) { diverse.push(b); used.add(b.role); }
      matches = [...diverse, ...matches.filter((b) => !diverse.includes(b))];
    }
    const found = matches.slice(0, c.count);
    if (!found.length) {
      return reply(`I found no builders matching ${filters.join(' · ')}. I won't fill the list with people who miss your requirements. ${c.skills.length > 1 && !c.anySkill ? 'Your skills are required together on each profile. Try “React or Python” to match either skill. ' : ''}${c.location ? 'Try worldwide to broaden the location. ' : ''}`,
        [], [...(c.location ? ['Make that worldwide'] : []), ...(c.skills.length > 1 ? [`Find ${c.count} people with ${c.skills.join(' or ')}${c.location ? ` in ${c.location}` : ' worldwide'}`] : []), 'Start over']);
    }
    return reply(`${found.length < c.count ? `I found ${found.length} matching ${found.length === 1 ? 'builder' : 'builders'}, fewer than the ${c.count} requested.` : `Here are ${found.length} matching builders.`} ${c.goal ? 'For your idea, I put different roles first so the shortlist brings complementary skills. ' : ''}Everyone shown meets every filter.`,
      found.map((b) => bmBuilderResult(b, c)), [...(c.location ? ['Make that worldwide'] : ['Only remote']), ...(c.role ? ['Any role'] : ['Show designers instead']), 'Show my saved builders']);
  }
  if (c.kind === 'teams') {
    const matches = data.teams.filter((t) => (!c.interest || bmHasInterest(t.interests, c.interest))
      && (!c.skills.length || c.skills.some((s) => t.needs.some((n) => bmHas(bmNorm(n), bmNorm(s)))))
      && (!c.role || c.role !== 'Product designer' || t.needs.some((n) => /figma|design|ux/i.test(n))));
    const found = matches.slice(0, c.count).map((t) => ({ kind: 'teams', id: t.id, title: t.name, subtitle: `${t.members}/${t.capacity} members · ${t.challenge}`, detail: t.description, tags: t.needs, reasons: [t.needs.length ? `Needs ${t.needs.join(' + ')}` : 'Open to any skills', ...t.interests] }));
    return reply(`${found.length ? `Found ${matches.length} matching open teams. Showing ${found.length}.` : 'No open teams match those needs.'} Teams don't have a location, so place filters don't apply to them.`, found, ['Teams that need design', 'Show climate teams', 'Find builders worldwide']);
  }
  if (c.kind === 'events') {
    const found = data.events.filter((e) => (!c.location || bmNorm(e.location) === bmNorm(c.location)) && (!c.mode || e.format === c.mode)
      && (!c.interest || bmHasInterest([e.theme], c.interest))).slice(0, c.count)
      .map((e) => ({ kind: 'events', id: e.id, title: e.title, subtitle: `${e.date} · ${e.location} · ${e.format}`, detail: `${e.prize || 'No prize listed'} · supported by ${e.sponsor}.`, tags: [e.theme, e.status === 'live' ? 'Live now' : 'Upcoming'], reasons: [e.size, `Hosted / supported by ${e.sponsor}`] }));
    return reply(found.length ? `Here are ${found.length} matching events.` : 'No events match that location, format, and theme. Try worldwide or another format.', found, ['Find in-person hackathons in Berlin', 'Show online events worldwide', 'Find teams']);
  }
  if (c.kind === 'projects') {
    const found = data.projects.filter((p) => !c.skills.length || c.skills.some((s) => p.stack.some((x) => x.toLowerCase() === s.toLowerCase()))).slice(0, c.count)
      .map((p) => ({ kind: 'projects', id: p.id, teamId: p.teamId, title: p.name, subtitle: `${p.stage} · ${p.team}`, detail: p.description, tags: p.stack, reasons: [`Built by ${p.members.join(' & ') || 'a demo team'}`] }));
    return reply(found.length ? `Here are ${found.length} projects${c.skills.length ? ` using ${c.skills.join(' or ')}` : ''}.` : 'No projects use those technologies yet.', found, ['Show projects using React', 'Find Python builders worldwide', 'Show sponsor challenges']);
  }
  const found = data.challenges.filter((ch) => !c.skills.length || c.skills.some((s) => bmHas(bmNorm(`${ch.tech} ${ch.title}`), bmNorm(s)))).slice(0, c.count)
    .map((ch) => ({ kind: 'challenges', id: ch.id, title: ch.title, subtitle: ch.name, detail: `${ch.prize || 'No prize listed'} · ${ch.tech}`, tags: ['Sponsor challenge', ch.tech], reasons: [ch.summary] }));
  return reply(found.length ? `Here are ${found.length} sponsor challenges.` : 'No sponsor challenges match that technology.', found, ['Show all sponsor challenges', 'Find AI builders worldwide', 'Show hackathons']);
}

// ---------- data from the live API ----------

const BM_DOMAIN_NAMES = Object.keys(BM_DOMAINS);
const bmDomain = (tag) => BM_DOMAIN_NAMES.find((d) => d.toLowerCase() === String(tag).toLowerCase()) || tag;

async function bmLoadData() {
  const [people, teams, challenges, projects, saved] = await Promise.all([
    api('/people'), api('/teams?open=1'), api('/challenges'), api('/projects'), me ? api('/saved') : Promise.resolve({ saved: [] })]);
  const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const open = challenges.challenges.filter((c) => c.status !== 'past');
  return {
    builders: people.people.filter((b) => !me || b.id !== me.id).map((b) => ({ id: b.id, handle: b.handle, name: b.name, role: b.title, city: b.city, country: b.country,
      skills: b.skills, interests: b.interests, experience: b.experience, hours: b.hours || 0, mode: b.collab, bio: b.bio, looking: b.looking })),
    teams: teams.teams.map((t) => ({ id: t.id, name: t.name, description: t.idea, interests: t.challenge_tags.map(bmDomain), needs: t.looking_for,
      members: t.members.length, capacity: t.max_size, challenge: t.challenge_title })),
    events: open.map((c) => ({ id: c.id, title: c.title, theme: bmDomain(c.tags[0] || 'Open'), location: c.location, format: c.format,
      date: `${fmtDay(c.starts_at)}–${fmtDay(c.ends_at)}`, prize: c.prize, sponsor: c.sponsor.name, size: `1–${c.max_team} builders`, status: c.status })),
    projects: projects.projects.map((p) => ({ id: p.id, teamId: p.team_id, name: p.title, description: p.description, stack: p.stack, team: p.team_name,
      members: p.members.map((m) => m.name), stage: p.stage })),
    challenges: open.filter((c) => c.sponsor.id).map((c) => ({ id: c.id, name: c.sponsor.name, title: c.title, prize: c.prize, tech: c.tags[1] || c.tags[0] || 'their platform', summary: c.summary })),
    saved: saved.saved,
  };
}

// ---------- the panel ----------

const bm = { open: false, messages: [BM_INTRO], context: null, data: null };

function bmRestore() {
  try {
    const saved = JSON.parse(localStorage.getItem(BM_KEY) || 'null');
    if (saved && Array.isArray(saved.messages) && saved.messages.every((m) => typeof m.text === 'string' && ['user', 'assistant'].includes(m.role))) {
      bm.messages = saved.messages.slice(-30);
      bm.context = saved.context && Array.isArray(saved.context.skills) ? saved.context : null;
    }
  } catch (e) { /* storage unavailable: chat still works for this visit */ }
}

function bmPersist() {
  try { localStorage.setItem(BM_KEY, JSON.stringify({ messages: bm.messages.slice(-30), context: bm.context })); } catch (e) { /* ignore */ }
}

function bmResultCard(r) {
  const saved = r.kind === 'builders' && builderState.saved.has(r.id);
  const view = { builders: 'View profile', projects: 'View project', teams: 'View team', events: 'View event', challenges: 'View challenge' }[r.kind];
  return `<article class="chat-result"><div class="chat-result-heading"><span class="chat-result-icon">${esc(r.title.split(' ').slice(0, 2).map((w) => w[0]).join(''))}</span>
      <div><strong>${esc(r.title)}</strong><small>${esc(r.subtitle)}</small></div></div>
    <div class="chat-tags">${r.tags.map((t) => `<span>${esc(t)}</span>`).join('')}</div>
    ${r.detail ? `<p>${esc(r.detail)}</p>` : ''}
    <ul>${r.reasons.map((x) => `<li>✓ ${esc(x)}</li>`).join('')}</ul>
    <div class="chat-result-actions"><button type="button" data-bm="view" data-kind="${r.kind}" data-id="${r.id}" data-team="${r.teamId || ''}">${view} ↗</button>
      ${r.kind === 'builders' ? `<button type="button" class="${saved ? 'is-saved' : ''}" data-bm="save" data-id="${r.id}">${saved ? '★ Saved' : '☆ Save'}</button>
        <button type="button" data-bm="invite" data-id="${r.id}">+ Invite</button>` : ''}</div></article>`;
}

function bmPaint() {
  const box = document.getElementById('bm-messages');
  if (!box) return;
  box.innerHTML = bm.messages.map((m) => `<div class="chat-message ${m.role}">${m.role === 'assistant' ? '<span class="chat-speaker">✦ BUILDMATE</span>' : ''}
      <p class="chat-message-text">${esc(m.text)}</p>
      ${m.reply ? `${m.reply.context.kind !== 'overview' ? `<div class="chat-filters">${m.reply.filters.map((f) => `<span>${esc(f)}</span>`).join('')}</div>` : ''}
        ${m.reply.results.map(bmResultCard).join('')}
        <div class="chat-followups">${m.reply.suggestions.map((s) => `<button type="button" data-bm-say="${esc(s)}">${esc(s)} ↗</button>`).join('')}</div>` : ''}
      ${m.id === 'intro' ? `<div class="chat-starters">${BM_STARTERS.map((s) => `<button type="button" data-bm-say="${esc(s)}">💬 ${esc(s)}</button>`).join('')}</div>` : ''}</div>`).join('');
  box.scrollTop = box.scrollHeight;
  const d = bm.data;
  document.getElementById('bm-source').innerHTML = d ? `<i class="dot"></i>${d.builders.length} builders · ${d.teams.length} open teams · ${d.events.length} events <span>LIVE DATA</span>` : '<i class="dot"></i>Loading…';
}

async function bmSend(prompt) {
  const text = String(prompt || '').trim().slice(0, 1200);
  if (!text) return;
  try {
    bm.data = await bmLoadData();  // always search the latest data
    await loadBuilderState().catch(() => null);
  } catch (e) { toast(e.message, true); return; }
  const reply = bmAnswer(text, bm.data, bm.context);
  bm.messages = [...bm.messages, { id: `u${Date.now()}`, role: 'user', text }, { id: `a${Date.now()}`, role: 'assistant', text: reply.text, reply }].slice(-30);
  bm.context = reply.context;
  bmPersist();
  const input = document.getElementById('bm-input');
  if (input) input.value = '';
  bmPaint();
}

function bmToggle(open) {
  bm.open = open ?? !bm.open;
  const panel = document.getElementById('bm-panel');
  const launcher = document.getElementById('bm-launcher');
  panel.hidden = !bm.open;
  launcher.classList.toggle('open', bm.open);
  launcher.setAttribute('aria-expanded', String(bm.open));
  launcher.innerHTML = bm.open ? '✕' : '✦ <span>Buildmate <small>Find your people</small></span>';
  if (bm.open) {
    bmPaint();
    if (!bm.data) bmLoadData().then((d) => { bm.data = d; bmPaint(); }).catch(() => {});
    setTimeout(() => document.getElementById('bm-input')?.focus(), 30);
  }
}

function mountBuildmate() {
  bmRestore();
  const wrap = document.createElement('div');
  wrap.innerHTML = `<button type="button" class="chat-launcher" id="bm-launcher" aria-controls="bm-panel" aria-expanded="false">✦ <span>Buildmate <small>Find your people</small></span></button>
    <section class="chat-panel" id="bm-panel" role="region" aria-label="Buildmate assistant" hidden>
      <div class="chat-header"><div class="chat-header-icon">✦</div><div><h2>Buildmate</h2><p>Your idea. The right people.</p></div>
        <button type="button" class="chat-icon" data-bm="new" aria-label="New chat" title="New chat">↺</button>
        <button type="button" class="chat-icon" data-bm="close" aria-label="Close Buildmate">✕</button></div>
      <div class="chat-source-bar" id="bm-source"></div>
      <div class="chat-messages" id="bm-messages" role="log" aria-live="polite"></div>
      <form class="chat-composer" id="bm-form"><label class="sr-only" for="bm-input">Message Buildmate</label>
        <textarea id="bm-input" rows="2" maxlength="1200" placeholder="Find 3 people with React in New York…"></textarea>
        <button type="submit" aria-label="Send">↑</button></form>
      <p class="chat-disclosure">Keyword & rule search over live data · No AI model · Never invents matches</p>
    </section>`;
  document.body.append(...wrap.children);
  document.getElementById('bm-launcher').addEventListener('click', () => bmToggle());
  const form = document.getElementById('bm-form');
  form.addEventListener('submit', (e) => { e.preventDefault(); bmSend(form.querySelector('textarea').value); });
  form.querySelector('textarea').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); bmSend(e.target.value); }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && bm.open && !document.querySelector('dialog[open]')) bmToggle(false); });
  document.getElementById('bm-panel').addEventListener('click', async (e) => {
    const say = e.target.closest('[data-bm-say]');
    if (say) { bmSend(say.dataset.bmSay); return; }
    const b = e.target.closest('[data-bm]');
    if (!b) return;
    const act = b.dataset.bm;
    try {
      if (act === 'close') bmToggle(false);
      else if (act === 'new') { bm.messages = [BM_INTRO]; bm.context = null; bmPersist(); bmPaint(); }
      else if (act === 'save') {
        const on = await toggleSaveBuilder(+b.dataset.id);
        b.classList.toggle('is-saved', on);
        b.textContent = on ? '★ Saved' : '☆ Save';
      } else if (act === 'invite') {
        const person = (await api('/people')).people.find((p) => p.id === +b.dataset.id);
        if (person) { bmToggle(false); openInviteBuilder(person); }
      } else if (act === 'view') {
        const kind = b.dataset.kind;
        if (kind === 'builders') { builderCache = (await api('/people')).people; openBuilderProfile(+b.dataset.id); return; }
        bmToggle(false);
        location.hash = kind === 'teams' ? `#/t/${b.dataset.id}` : kind === 'projects' ? `#/t/${b.dataset.team}` : `#/c/${b.dataset.id}`;
      }
    } catch (err) { toast(err.message, true); }
  });
}
