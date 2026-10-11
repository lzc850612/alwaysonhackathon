'use strict';
// Build lab: the team's shared three-file prototype plus a coding agent. The agent (Claude when the server has
// credentials, built-in templates otherwise) only ever *proposes* changes; a teammate reviews the diff and applies
// or discards it. The preview runs the real files in a sandboxed iframe with an opaque origin, so prototype code
// can't reach this app, its cookies, or its API. Loaded before app.js; uses its globals (api, esc, me, …) at call time.

const LAB_FILES = ['index.html', 'styles.css', 'app.js'];
const LAB_PROMPTS = [
  'Build a landing page for our idea',
  'Add a progress dashboard with sample data',
  'Improve accessibility and keyboard navigation',
];

// Inline styles.css / app.js into index.html so the sandboxed preview needs no other requests.
function labPreviewDoc(files) {
  const css = `<style>\n${files['styles.css'].replace(/<\/style/gi, '<\\/style')}\n</style>`;
  const js = `<script>\n${files['app.js'].replace(/<\/script/gi, '<\\/script')}\n<\/script>`;
  let html = files['index.html'];
  const linked = /<link[^>]*href=["']styles\.css["'][^>]*>/i;
  const sourced = /<script[^>]*src=["']app\.js["'][^>]*>\s*<\/script>/i;
  html = linked.test(html) ? html.replace(linked, () => css) : html.replace(/<\/head>/i, () => `${css}</head>`);
  html = sourced.test(html) ? html.replace(sourced, () => js) : html.replace(/<\/body>/i, () => `${js}</body>`);
  return html;
}

// Line diff (LCS). Fine for prototype-sized files; very large files just show the new content.
function labDiff(before, after) {
  const a = before.split('\n');
  const b = after.split('\n');
  if (a.length * b.length > 2_500_000) return b.map((line) => ['+', line]);
  const dp = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push([' ', a[i]]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(['-', a[i++]]); else out.push(['+', b[j++]]);
  }
  while (i < a.length) out.push(['-', a[i++]]);
  while (j < b.length) out.push(['+', b[j++]]);
  return out;
}

// Collapse long unchanged stretches so the change itself stays visible.
function labDiffHtml(rows) {
  const html = [];
  let run = [];
  const flush = (last) => {
    if (run.length > 6) {
      run.slice(0, 2).forEach(([, l]) => html.push(`<div class="d ctx">${esc(l) || ' '}</div>`));
      html.push(`<div class="d gap">⋯ ${run.length - (last ? 2 : 4)} unchanged lines</div>`);
      if (!last) run.slice(-2).forEach(([, l]) => html.push(`<div class="d ctx">${esc(l) || ' '}</div>`));
    } else run.forEach(([, l]) => html.push(`<div class="d ctx">${esc(l) || ' '}</div>`));
    run = [];
  };
  for (const row of rows) {
    if (row[0] === ' ') { run.push(row); continue; }
    flush(false);
    html.push(`<div class="d ${row[0] === '+' ? 'add' : 'del'}"><b>${row[0]}</b>${esc(row[1]) || ' '}</div>`);
  }
  flush(true);
  return html.join('');
}

function mountBuildLab(el, team) {
  const lab = {
    state: null, view: 'preview', file: 'index.html', drafts: {}, dirty: false, shownVersion: null,
    timer: null, alive: true, pendingFocus: false,
  };

  const agentLabel = () => (lab.state.agent.mode === 'claude' ? 'Claude Opus 5.5' : 'Simulated · no API key on this server');
  const latestReady = () => [...lab.state.runs].reverse().find((r) => r.status === 'ready');

  function shell() {
    el.innerHTML = `<section class="lab">
      <div class="lab-heading"><div><span class="lab-kicker"><i></i>THE BUILD SPACE</span>
        <h2>Ideas meet <em>execution.</em></h2>
        <p>Your team's context, a shared prototype, and an agent that proposes the next change. Nothing lands until a teammate applies it.</p></div>
        <span class="lab-badge" id="lab-badge"></span></div>
      <div class="lab-shell">
        <div class="lab-toolbar"><span><b>▦</b> ${esc(team.name)} <small>/ build lab</small></span><span class="lab-branch" id="lab-version"></span></div>
        <div class="lab-grid">
          <aside class="lab-agent">
            <div class="lab-agent-title"><div class="lab-orb">✦</div><div><h3>Build agent</h3><small id="lab-agent-sub"></small></div><span class="lab-status" id="lab-status"></span></div>
            <div class="lab-context"><span>TEAM CONTEXT</span><strong>${esc(team.name)}</strong><p>${esc(team.idea || 'No idea written yet — the agent works from the files.')}</p>
              <small>Challenge</small><p>${esc(team.challenge_title)}</p></div>
            <div class="lab-thread" id="lab-thread" aria-live="polite"></div>
            <div class="lab-suggestions" id="lab-suggestions">${LAB_PROMPTS.map((p) => `<button type="button" data-lab-prompt="${esc(p)}">✧ ${esc(p)}</button>`).join('')}</div>
            <form class="lab-prompt" id="lab-form"><label for="lab-input">Give the agent a task</label>
              <textarea id="lab-input" name="prompt" rows="3" maxlength="2000" placeholder="Add a signup form that validates the email…"></textarea>
              <div><small id="lab-hint">Teammates see every task and proposal</small><button type="submit" aria-label="Send task to the agent">↑</button></div></form>
          </aside>
          <div class="lab-workbench">
            <div class="lab-view-tabs" role="tablist" aria-label="Build lab views">
              ${[['preview', '▶ Preview'], ['code', '‹/› Code'], ['changes', '⑂ Changes']].map(([k, l]) => `<button type="button" role="tab" data-lab-view="${k}">${l}<i hidden></i></button>`).join('')}
            </div>
            <div class="lab-view" id="lab-view"></div>
            <div class="lab-console"><span>⌁ Activity</span><p id="lab-activity"></p></div>
          </div>
        </div>
        <div class="lab-bottom"><span><i></i>History</span><div class="lab-history" id="lab-history"></div></div>
      </div></section>`;
  }

  function paintMeta() {
    const s = lab.state;
    const running = s.runs.find((r) => r.status === 'running');
    document.getElementById('lab-badge').textContent = s.agent.mode === 'claude' ? '✦ Claude · live agent' : '✦ Simulated agent';
    document.getElementById('lab-badge').classList.toggle('sim', s.agent.mode !== 'claude');
    document.getElementById('lab-agent-sub').textContent = agentLabel();
    document.getElementById('lab-status').classList.toggle('running', !!running);
    const head = s.versions[0];
    document.getElementById('lab-version').textContent = head ? `v${head.id} · ${head.note}${head.by ? ` · @${head.by}` : ''}` : '';
    document.getElementById('lab-activity').innerHTML = running
      ? `@${esc(running.user?.handle)} asked: “${esc(running.prompt.slice(0, 90))}” — working…`
      : head ? `Saved v${head.id} ${ago(head.created_at)} · ${esc(head.note)}` : 'Ready';
    const pending = latestReady();
    el.querySelectorAll('.lab-view-tabs [data-lab-view]').forEach((b) => {
      b.setAttribute('aria-selected', String(b.dataset.labView === lab.view));
      if (b.dataset.labView === 'changes') b.querySelector('i').hidden = !pending;
    });
    const form = document.getElementById('lab-form');
    form.querySelector('button').disabled = !!running;
    document.querySelectorAll('[data-lab-prompt]').forEach((b) => { b.disabled = !!running; });
    document.getElementById('lab-history').innerHTML = s.versions.slice(0, 8).map((v, i) => `<button type="button" class="${i === 0 ? 'current' : ''}"
      ${i === 0 ? 'disabled' : `data-lab-restore="${v.id}"`} title="${esc(v.note)}">v${v.id}<small>${esc(v.note.slice(0, 32))}</small></button>`).join('');
  }

  function paintThread() {
    const box = document.getElementById('lab-thread');
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    const runs = lab.state.runs;
    box.innerHTML = runs.length ? runs.map((r) => `<div class="lab-msg user"><span class="lab-who">@${esc(r.user?.handle || '?')}</span>${esc(r.prompt)}</div>
      <div class="lab-msg agent ${r.status}"><span class="lab-who">✦ ${r.mode === 'claude' ? 'CLAUDE' : 'SIMULATED'}</span>${
        r.status === 'running' ? '<span class="lab-working"><i></i><i></i><i></i> Reading the brief and current files…</span>'
        : r.status === 'failed' ? `⚠ ${esc(r.error)}`
        : `${esc(r.summary)}<span class="lab-tag">${{ ready: 'Ready to review', applied: '✓ Applied', discarded: 'Discarded' }[r.status]}</span>`}
        ${r.status === 'ready' ? '<button type="button" class="lab-link" data-lab-view="changes">Review changes →</button>' : ''}</div>`).join('')
      : `<div class="lab-msg agent"><span class="lab-who">✦ BUILD AGENT</span>What should we build next? Pick a suggestion or describe a change — I'll propose it as a diff your team can apply.</div>`;
    if (near || lab.pendingFocus) box.scrollTop = box.scrollHeight;
    lab.pendingFocus = false;
  }

  function filesNow() {
    return { ...lab.state.files, ...lab.drafts };
  }

  function paintView(force) {
    const view = document.getElementById('lab-view');
    if (lab.view === 'preview') {
      if (!force && view.dataset.kind === 'preview' && lab.shownVersion === lab.state.version) return;
      view.dataset.kind = 'preview';
      lab.shownVersion = lab.state.version;
      view.innerHTML = `<div class="lab-browser"><div class="lab-browser-bar"><span><i></i><i></i><i></i></span><small>preview · v${lab.state.version}${lab.dirty ? ' · unsaved edits not shown' : ''}</small>
        <button type="button" class="lab-link" data-lab-reload>↻ Reload</button></div>
        <iframe title="${esc(team.name)} prototype preview" sandbox="allow-scripts allow-forms allow-modals" referrerpolicy="no-referrer"></iframe></div>`;
      view.querySelector('iframe').srcdoc = labPreviewDoc(lab.state.files);
    } else if (lab.view === 'code') {
      if (!force && view.dataset.kind === `code:${lab.file}`) return;
      view.dataset.kind = `code:${lab.file}`;
      const value = filesNow()[lab.file];
      view.innerHTML = `<div class="lab-file-tabs">${LAB_FILES.map((f) => `<button type="button" class="${f === lab.file ? 'active' : ''}" data-lab-file="${f}">${f}${lab.drafts[f] !== undefined ? ' •' : ''}</button>`).join('')}
          <span class="lab-spacer"></span>
          <button type="button" data-lab-download>⤓ Download</button>
          <button type="button" data-lab-revert ${lab.dirty ? '' : 'disabled'}>Discard edits</button>
          <button type="button" class="lab-save" data-lab-save ${lab.dirty ? '' : 'disabled'}>Save version</button></div>
        <label class="lab-editor-label" for="lab-code">${esc(lab.file)} · edits are yours until you save a version</label>
        <textarea id="lab-code" class="lab-code" spellcheck="false">${esc(value)}</textarea>`;
      view.querySelector('#lab-code').addEventListener('input', (e) => {
        lab.drafts[lab.file] = e.target.value;
        lab.dirty = LAB_FILES.some((f) => lab.drafts[f] !== undefined && lab.drafts[f] !== lab.state.files[f]);
        view.querySelector('[data-lab-save]').disabled = !lab.dirty;
        view.querySelectorAll('[data-lab-file]').forEach((b) => {
          const f = b.dataset.labFile;
          b.textContent = f + (lab.drafts[f] !== undefined && lab.drafts[f] !== lab.state.files[f] ? ' •' : '');
        });
        view.querySelector('[data-lab-revert]').disabled = !lab.dirty;
      });
    } else {
      const run = latestReady();
      const key = `changes:${run?.id || 'none'}:${lab.state.version}`;
      if (!force && view.dataset.kind === key) return;
      view.dataset.kind = key;
      if (!run) {
        view.innerHTML = `<div class="lab-changes"><span class="lab-kicker">REVIEW BEFORE YOU APPLY</span><h3>No pending changes.</h3>
          <p>Give the agent a task. Its proposal shows up here as a diff, and nothing changes until someone on the team applies it.</p></div>`;
        return;
      }
      const stale = run.base_version !== lab.state.version;
      view.innerHTML = `<div class="lab-changes"><span class="lab-kicker">REVIEW BEFORE YOU APPLY · @${esc(run.user?.handle)}'s task</span>
        <h3>“${esc(run.prompt.slice(0, 120))}”</h3><p>${esc(run.summary)}</p>
        ${stale ? `<p class="lab-warn">⚠ The files changed after this task started (now v${lab.state.version}, it was based on v${run.base_version}). Applying replaces the files it touches.</p>` : ''}
        ${Object.entries(run.files).map(([path, content]) => {
          const rows = labDiff(lab.state.files[path] || '', content);
          const add = rows.filter((r) => r[0] === '+').length;
          const del = rows.filter((r) => r[0] === '-').length;
          return `<div class="lab-change-file">${esc(path)}<span><b class="plus">+${add}</b> <b class="minus">−${del}</b></span></div><pre class="lab-diff">${labDiffHtml(rows)}</pre>`;
        }).join('')}
        <div class="lab-review-actions"><button type="button" class="btn" data-lab-apply="${run.id}" data-stale="${stale ? 1 : ''}">✓ Apply to project</button>
          <button type="button" class="btn ghost" data-lab-discard="${run.id}">Discard proposal</button></div></div>`;
    }
  }

  async function refresh(force) {
    try {
      const next = await api(`/teams/${team.id}/build`);
      if (!lab.alive) return;
      const prevVersion = lab.state?.version;
      const prevRuns = JSON.stringify(lab.state?.runs);
      const finished = lab.state && lab.state.runs.some((r) => r.status === 'running') && !next.runs.some((r) => r.status === 'running');
      lab.state = next;
      next.runs.filter((r) => r.status === 'running' && !r.started_at).forEach((r) => startRun(r.id));
      if (prevVersion && prevVersion !== next.version && lab.dirty) toast(`A teammate saved v${next.version} — your unsaved edits are kept`);
      if (!lab.dirty) lab.drafts = {};
      paintMeta();
      if (force || prevRuns !== JSON.stringify(next.runs)) paintThread();
      if (finished) {
        const last = next.runs[next.runs.length - 1];
        if (last.status === 'ready') { lab.view = 'changes'; toast('The agent has a proposal ready to review'); paintMeta(); }
      }
      paintView(force || (prevVersion !== next.version && (lab.view !== 'code' || !lab.dirty)));
    } catch (e) {
      if (e.status === 403) { lab.alive = false; return; }
      console.warn('build lab refresh failed', e);
    }
    if (lab.alive) {
      const busy = lab.state?.runs.some((r) => r.status === 'running');
      lab.timer = setTimeout(() => refresh(false), busy ? 1500 : document.hidden ? 20000 : 6000);
    }
  }

  // The agent works inside its own long request (so it also runs on serverless hosts). Whoever started the task
  // kicks it off; if they left before it began, the next teammate whose lab sees it picks it up.
  function startRun(id) {
    lab.kicked = lab.kicked || new Set();
    if (lab.kicked.has(id)) return;
    lab.kicked.add(id);
    api(`/teams/${team.id}/agent/${id}/run`, {})
      .then(() => { if (lab.alive) { clearTimeout(lab.timer); refresh(false); } })
      .catch((e) => console.warn('agent run failed', e));
  }

  async function sendPrompt(text) {
    const prompt = text.trim();
    if (!prompt) return;
    try {
      const { run } = await api(`/teams/${team.id}/agent`, { prompt });
      document.getElementById('lab-input').value = '';
      lab.pendingFocus = true;
      clearTimeout(lab.timer);
      startRun(run.id);
      await refresh(true);
    } catch (e) { toast(e.message, true); }
  }

  function download() {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([filesNow()[lab.file]], { type: 'text/plain' }));
    a.download = lab.file;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  shell();
  el.addEventListener('click', async (e) => {
    const t = e.target.closest('button');
    if (!t || t.disabled) return;
    try {
      if (t.dataset.labView) { lab.view = t.dataset.labView; paintMeta(); paintView(true); }
      else if (t.dataset.labPrompt) sendPrompt(t.dataset.labPrompt);
      else if (t.dataset.labFile) { lab.file = t.dataset.labFile; paintView(true); }
      else if (t.hasAttribute('data-lab-reload')) paintView(true);
      else if (t.hasAttribute('data-lab-download')) download();
      else if (t.hasAttribute('data-lab-revert')) { lab.drafts = {}; lab.dirty = false; paintView(true); }
      else if (t.hasAttribute('data-lab-save')) {
        const changed = Object.fromEntries(LAB_FILES.filter((f) => lab.drafts[f] !== undefined && lab.drafts[f] !== lab.state.files[f]).map((f) => [f, lab.drafts[f]]));
        const r = await api(`/teams/${team.id}/build/files`, { files: changed, note: `Edited ${Object.keys(changed).join(', ')} by hand` });
        lab.drafts = {}; lab.dirty = false;
        toast(`Saved v${r.version} for the team`);
        clearTimeout(lab.timer); await refresh(true);
      } else if (t.dataset.labApply) {
        const force = !!t.dataset.stale;
        if (force && !confirm('The files changed since the agent started. Apply anyway? It replaces the files it touches.')) return;
        if (lab.dirty && !confirm('You have unsaved edits in the editor. Applying keeps them as unsaved drafts on top. Continue?')) return;
        const r = await api(`/teams/${team.id}/agent/${t.dataset.labApply}/apply`, { force });
        toast(`Applied — the team's project is now v${r.version}`);
        lab.view = 'preview';
        clearTimeout(lab.timer); await refresh(true);
      } else if (t.dataset.labDiscard) {
        await api(`/teams/${team.id}/agent/${t.dataset.labDiscard}/discard`, {});
        toast('Proposal discarded — files unchanged');
        clearTimeout(lab.timer); await refresh(true);
      } else if (t.dataset.labRestore) {
        if (!confirm(`Restore v${t.dataset.labRestore}? It's saved as a new version, so nothing is lost.`)) return;
        const r = await api(`/teams/${team.id}/build/restore`, { version_id: +t.dataset.labRestore });
        toast(`Restored — now v${r.version}`);
        clearTimeout(lab.timer); await refresh(true);
      }
    } catch (err) { toast(err.message, true); }
  });
  const form = el.querySelector('#lab-form');
  form.addEventListener('submit', (e) => { e.preventDefault(); sendPrompt(form.prompt.value); });
  form.prompt.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendPrompt(form.prompt.value); }
  });
  refresh(true);
  return () => { lab.alive = false; clearTimeout(lab.timer); };
}
