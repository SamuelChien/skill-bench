const API = '/api/v1';
let _tasks = [], _skills = [], _jobs = [];

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: {'Content-Type':'application/json'}, ...opts });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

function esc(s) { return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
function scoreColor(s) { return s >= .9 ? 'score-high' : s >= .5 ? 'score-mid' : 'score-low'; }
function scoreFillColor(s) { return s >= .9 ? 'var(--green)' : s >= .5 ? 'var(--yellow)' : 'var(--red)'; }
function badge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}
function fmtTime(iso) {
  try { return new Date(iso + (iso.includes('T') ? '' : 'Z')).toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
  catch { return iso || '—'; }
}
function el(id) { return document.getElementById(id); }
function $(sel) { return document.querySelector(sel); }

// ─── Navigation ───
function nav(view, ...args) {
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  const btn = [...document.querySelectorAll('.sidebar-item')].find(b => b.textContent.includes(
    {jobs:'Jobs',tests:'Test Cases',actors:'Actors',hillclimb:'Hill Climb','new-job':'New Job'}[view] || ''));
  if (btn) btn.classList.add('active');

  const main = el('main');
  const views = {jobs: viewJobs, tests: viewTests, actors: viewActors, 'new-job': viewNewJob,
    'job-detail': viewJobDetail, 'result-detail': viewResultDetail, hillclimb: viewHillClimb,
    'hc-detail': viewHCDetail};
  const fn = views[view];
  if (fn) fn(main, ...args);
}

// ─── Data loading ───
async function reload() {
  [_tasks, _skills, _jobs] = await Promise.all([api('/tasks'), api('/skills'), api('/jobs')]);
  el('cnt-jobs').textContent = _jobs.length;
  el('cnt-tests').textContent = _tasks.length;
  el('cnt-actors').textContent = _skills.length;
}

// ─── JOBS VIEW ───
function viewJobs(m) {
  const benchJobs = _jobs.filter(j => j.type === 'benchmark');
  m.innerHTML = `
    <div class="page-hdr">
      <div><h2>Benchmark Jobs</h2><div class="sub">${benchJobs.length} jobs</div></div>
      <button class="btn btn-primary" onclick="nav('new-job')">New Job</button>
    </div>
    <div id="job-log" class="live-log" style="display:none"></div>
    <div class="card"><div class="card-body flush">
      <table><thead><tr><th>Job</th><th>Status</th><th>Skill</th><th>Model</th><th>Score</th><th>Time</th></tr></thead>
      <tbody>${benchJobs.length ? benchJobs.map(j => {
        const summary = j.completed_at ? `<span class="score-pill">${j.status === 'completed' ? '—' : ''}</span>` : '';
        return `<tr class="clickable" onclick="nav('job-detail','${j.id}')">
          <td><code class="mono">${j.id.slice(0,10)}</code></td>
          <td>${badge(j.status)}</td>
          <td>${j.skill_id || '<span class="meta">none</span>'}</td>
          <td class="meta">${j.model.replace('claude-','').replace('-20251001','')}</td>
          <td>${summary}</td>
          <td class="meta">${fmtTime(j.created_at)}</td></tr>`;
      }).join('') : '<tr><td colspan="6" class="empty">No benchmark jobs yet</td></tr>'}</tbody></table>
    </div></div>`;
  // Load scores for completed jobs
  benchJobs.filter(j => j.status === 'completed').forEach(async j => {
    const full = await api(`/jobs/${j.id}`);
    const avg = full.summary?.avg_score;
    if (avg !== undefined) {
      const cell = m.querySelector(`tr[onclick*="${j.id}"] td:nth-child(5)`);
      if (cell) cell.innerHTML = `<span class="score-pill ${scoreColor(avg)}">${(avg*100).toFixed(1)}%</span>`;
    }
  });
}

// ─── JOB DETAIL VIEW ───
async function viewJobDetail(m, jobId) {
  const [job, results] = await Promise.all([api(`/jobs/${jobId}`), api(`/jobs/${jobId}/results`)]);
  const avg = job.summary?.avg_score ?? 0;
  const config = job.config || {};

  m.innerHTML = `
    <div class="breadcrumb"><a onclick="nav('jobs')">Jobs</a> / <span>${jobId.slice(0,10)}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body">
        <div class="meta mb-12">SCORE</div>
        <div class="score-big ${scoreColor(avg)}">${job.status === 'completed' ? (avg*100).toFixed(1)+'%' : '—'}</div>
        <div class="meta mt-8">${results.length} test cases</div>
      </div></div>
      <div class="card"><div class="card-body gap-12" style="display:flex;flex-direction:column;gap:8px">
        <div class="flex-between"><span class="meta">STATUS</span>${badge(job.status)}</div>
        <div class="flex-between"><span class="meta">MODEL</span><span class="mono" style="font-size:12px">${job.model}</span></div>
        <div class="flex-between"><span class="meta">ACTOR</span><span>${job.skill_id || 'none'}</span></div>
        <div class="flex-between"><span class="meta">SAMPLER</span><span class="mono" style="font-size:12px">${config.enable_thinking ? 'thinking:'+config.thinking_budget : 'no-thinking'}</span></div>
        <div class="flex-between"><span class="meta">JUDGE</span><span class="mono" style="font-size:12px">${config.judge_model || job.model}</span></div>
        <div class="flex-between"><span class="meta">CREATED</span><span class="meta">${fmtTime(job.created_at)}</span></div>
        ${job.status === 'running' || job.status === 'pending' ?
          `<button class="btn btn-ghost btn-sm" style="color:var(--red)" onclick="cancelAndRefresh('${jobId}')">Cancel</button>` : ''}
      </div></div>
    </div>
    <div class="card"><div class="card-hdr">Test Results</div><div class="card-body flush">
      <table><thead><tr><th>Test Case</th><th>Score</th><th>Rubric</th><th>Judge</th></tr></thead>
      <tbody>${results.length ? results.map(r => {
        const pct = r.overall_score * 100;
        return `<tr class="clickable" onclick="nav('result-detail','${jobId}','${r.task_id}')">
          <td><strong>${r.task_id}</strong></td>
          <td style="width:200px"><div class="score-bar">
            <div class="score-track"><div class="score-fill" style="width:${pct}%;background:${scoreFillColor(r.overall_score)}"></div></div>
            <span class="score-label ${scoreColor(r.overall_score)}">${pct.toFixed(1)}%</span>
          </div></td>
          <td>${r.assertions_passed}/${r.assertions_total} pass</td>
          <td>—</td></tr>`;
      }).join('') : '<tr><td colspan="4" class="empty">No results yet</td></tr>'}</tbody></table>
    </div></div>`;
}

async function cancelAndRefresh(id) { await api(`/jobs/${id}`, {method:'DELETE'}); await reload(); nav('jobs'); }

// ─── RESULT DETAIL VIEW ───
async function viewResultDetail(m, jobId, taskId) {
  const [detail, taskDef] = await Promise.all([
    api(`/jobs/${jobId}/results/${taskId}`),
    api(`/tasks/${taskId}`).catch(() => null),
  ]);

  let html = `
    <div class="breadcrumb"><a onclick="nav('jobs')">Jobs</a> / <a onclick="nav('job-detail','${jobId}')">${jobId.slice(0,10)}</a> / <span>${taskId}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body">
        <div class="meta mb-12">SCORE</div>
        <div class="score-big ${scoreColor(detail.overall_score)}">${(detail.overall_score*100).toFixed(1)}%</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="meta mb-12">TEST CASE</div>
        <div style="font-weight:600;margin-bottom:4px">${taskId}</div>
        ${taskDef ? `<div class="meta">${esc(taskDef.description)}</div>
          <div class="mt-8">${(taskDef.tags||[]).map(t => `<span class="tag">${t}</span>`).join(' ')}</div>` : ''}
      </div></div>
    </div>`;

  // Rubric (assertions)
  html += `<div class="card"><div class="card-hdr">Rubric</div><div class="card-body"><div class="rubric-list">`;
  for (const a of detail.assertion_results) {
    const icon = a.passed ? '<span class="rubric-icon rubric-pass">&#10003;</span>' : '<span class="rubric-icon rubric-fail">&#10007;</span>';
    html += `<div class="rubric-row">${icon}<span class="rubric-type">${a.type}</span>
      <span class="rubric-detail">${esc(a.details)}</span></div>`;
  }
  html += `</div></div></div>`;

  // Judge
  if (detail.judge_results.length) {
    html += `<div class="card"><div class="card-hdr">LLM Judge</div><div class="card-body">`;
    for (const j of detail.judge_results) {
      html += `<div class="judge-block mb-12">
        <div class="flex-between">
          <span class="judge-score ${scoreColor(j.score)}">${(j.score*100).toFixed(0)}%</span>
          <span class="meta">criteria</span>
        </div>
        <div class="judge-reasoning">${esc(j.reasoning)}</div>
        <details class="mt-8"><summary style="font-size:11px;color:var(--text3);cursor:pointer">Evaluation criteria</summary>
          <div class="meta mt-8" style="white-space:pre-wrap">${esc(j.prompt)}</div>
        </details>
      </div>`;
    }
    html += `</div></div>`;
  }

  // Turn-by-turn trace
  html += `<div class="card"><div class="card-hdr">Turn-by-Turn Trace <span class="meta">${detail.turns.length} turns</span></div><div class="card-body">`;
  for (const t of detail.turns) {
    html += `<div class="turn-card">
      <div class="turn-hdr">
        <span><span class="turn-num">Turn ${t.turn_index}</span></span>
        <span>${t.duration_ms}ms &middot; ${t.input_tokens}in / ${t.output_tokens}out tokens${t.tool_calls.length ? ` &middot; ${t.tool_calls.length} tools` : ''}</span>
      </div>
      <div class="turn-body">
        <div class="msg"><div class="msg-role user">User</div><div class="msg-text">${esc(t.user_input)}</div></div>
        <div class="msg"><div class="msg-role assistant">Assistant</div><div class="msg-text">${esc(t.assistant_response)}</div></div>
        ${t.thinking_trace ? `<details class="thinking-toggle"><summary>Thinking (${t.thinking_trace.length} chars)</summary>
          <div class="thinking-text">${esc(t.thinking_trace)}</div></details>` : ''}
        ${t.tool_calls.length ? `<div class="tool-calls">${t.tool_calls.map(tc =>
          `<code>${tc.tool_name}</code>(${JSON.stringify(tc.input).slice(0,60)}) → ${tc.duration_ms}ms`
        ).join('<br>')}</div>` : ''}
      </div></div>`;
  }
  html += `</div></div>`;

  m.innerHTML = html;
}

// ─── TEST CASES VIEW ───
function viewTests(m) {
  m.innerHTML = `
    <div class="page-hdr">
      <div><h2>Test Cases</h2><div class="sub">${_tasks.length} cases loaded</div></div>
      <button class="btn btn-primary btn-sm" onclick="doImport()">Import YAML</button>
    </div>
    <div class="card"><div class="card-body flush">
      <table><thead><tr><th>ID</th><th>Name</th><th>Turns</th><th>Rubric</th><th>Tags</th></tr></thead>
      <tbody>${_tasks.map(t => `<tr class="clickable" onclick="showTestDetail('${t.id}')">
        <td><code class="mono">${t.id}</code></td>
        <td>${esc(t.name)}</td>
        <td>${t.turns.length}</td>
        <td>${t.assertions.length} checks</td>
        <td>${(t.tags||[]).map(tg => `<span class="tag">${tg}</span>`).join(' ')}</td>
      </tr>`).join('') || '<tr><td colspan="5" class="empty">No test cases</td></tr>'}</tbody></table>
    </div></div>
    <div id="test-detail"></div>`;
}

function showTestDetail(id) {
  const t = _tasks.find(x => x.id === id);
  if (!t) return;
  el('test-detail').innerHTML = `<div class="card mt-16"><div class="card-hdr">${t.id} <span class="meta">${t.name}</span></div><div class="card-body">
    <div class="meta mb-12">${esc(t.description)}</div>
    <div class="mb-12"><strong style="font-size:12px;color:var(--text3)">TURNS</strong>
      ${t.turns.map((turn, i) => `<div class="turn-card mt-8"><div class="turn-hdr"><span class="turn-num">Turn ${i}</span><span>${turn.role}</span></div>
        <div class="turn-body"><div class="msg-text">${esc(turn.content)}</div></div></div>`).join('')}
    </div>
    <div><strong style="font-size:12px;color:var(--text3)">RUBRIC (${t.assertions.length} assertions)</strong>
      <div class="rubric-list mt-8">${t.assertions.map(a =>
        `<div class="rubric-row"><span class="rubric-type">${a.type}</span>
          <span class="rubric-detail">target: ${esc(a.target)} ${a.expected ? '| expected: '+esc(String(a.expected)) : ''} | weight: ${a.weight}</span></div>`
      ).join('')}</div>
    </div>
  </div></div>`;
}

async function doImport() {
  await api('/tasks/import', {method:'POST'});
  await reload(); nav('tests');
}

// ─── ACTORS VIEW ───
function viewActors(m) {
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Actors (Skills)</h2><div class="sub">System prompts that drive the model</div></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">All Actors</div><div class="card-body flush">
        <table><thead><tr><th>ID</th><th>Name</th><th>Version</th><th>Created</th></tr></thead>
        <tbody>${_skills.map(s => `<tr class="clickable" onclick="showActorDetail('${s.id}')">
          <td><code class="mono">${s.id}</code></td><td>${s.name}</td><td>v${s.version}</td>
          <td class="meta">${fmtTime(s.created_at)}</td></tr>`).join('') ||
          '<tr><td colspan="4" class="empty">No actors yet</td></tr>'}</tbody></table>
      </div></div>
      <div class="card"><div class="card-hdr">Create Actor</div><div class="card-body">
        <div class="form-group mb-12"><label>ID</label><input id="actor-id" placeholder="e.g. coding_v1"></div>
        <div class="form-group mb-12"><label>System Prompt</label>
          <textarea id="actor-content" rows="8" placeholder="You are a senior software engineer..."></textarea></div>
        <button class="btn btn-primary" onclick="createActor()">Create</button>
      </div></div>
    </div>
    <div id="actor-detail"></div>`;
}

function showActorDetail(id) {
  const s = _skills.find(x => x.id === id);
  if (!s) return;
  el('actor-detail').innerHTML = `<div class="card mt-16"><div class="card-hdr">${s.id} <span class="meta">v${s.version}</span></div>
    <div class="card-body"><div class="meta mb-12">SYSTEM PROMPT</div>
      <div style="font-family:var(--mono);font-size:12px;white-space:pre-wrap;background:var(--bg);padding:12px;border-radius:6px;max-height:400px;overflow-y:auto">${esc(s.content)}</div>
      ${s.parent_id ? `<div class="meta mt-8">Parent: ${s.parent_id}</div>` : ''}
    </div></div>`;
}

async function createActor() {
  const id = el('actor-id').value.trim(), content = el('actor-content').value.trim();
  if (!id || !content) return alert('ID and content required');
  await api('/skills', {method:'POST', body: JSON.stringify({id, name:id, content})});
  await reload(); nav('actors');
}

// ─── NEW JOB VIEW ───
function viewNewJob(m) {
  const taskChecks = _tasks.map(t =>
    `<label><input type="checkbox" name="task" value="${t.id}" checked> ${t.id} <span class="meta">(${t.turns.length}t/${t.assertions.length}a)</span></label>`
  ).join('');
  const skillOpts = _skills.map(s => `<option value="${s.id}">${s.name} v${s.version}</option>`).join('');

  m.innerHTML = `
    <div class="page-hdr"><div><h2>New Benchmark Job</h2><div class="sub">Configure and run an evaluation</div></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">Configuration</div><div class="card-body">
        <div class="form-grid">
          <div class="form-group"><label>Actor (Skill)</label>
            <select id="nj-skill"><option value="">— none —</option>${skillOpts}</select></div>
          <div class="form-group"><label>Sampler (Model)</label>
            <select id="nj-model">
              <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-6" selected>Sonnet 4.6</option>
              <option value="claude-opus-4-6">Opus 4.6</option>
            </select></div>
          <div class="form-group"><label>Thinking</label>
            <select id="nj-thinking"><option value="on">On (5000 budget)</option><option value="off">Off</option></select></div>
          <div class="form-group"><label>Judge Model</label>
            <select id="nj-judge">
              <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-6" selected>Sonnet 4.6</option>
            </select></div>
        </div>
        <div class="mt-16"><button class="btn btn-primary" id="nj-submit" onclick="submitNewJob()">Run Benchmark</button></div>
      </div></div>
      <div class="card"><div class="card-hdr">Test Cases</div><div class="card-body">
        <div class="checklist">${taskChecks || '<span class="empty">No tests — import first</span>'}</div>
      </div></div>
    </div>
    <div id="nj-log" class="live-log mt-16" style="display:none"></div>`;
}

async function submitNewJob() {
  const taskIds = [...document.querySelectorAll('input[name="task"]:checked')].map(c => c.value);
  if (!taskIds.length) return alert('Select at least one test case');
  const thinking = el('nj-thinking').value === 'on';
  const body = {
    type: 'benchmark', task_ids: taskIds,
    skill_id: el('nj-skill').value || null,
    model: el('nj-model').value,
    config: { enable_thinking: thinking, thinking_budget: thinking ? 5000 : 0, judge_model: el('nj-judge').value }
  };
  el('nj-submit').disabled = true;
  try {
    const job = await api('/jobs', {method:'POST', body: JSON.stringify(body)});
    await reload();
    streamJobLog(job.id, el('nj-log'));
  } catch (e) { alert(e.message); el('nj-submit').disabled = false; }
}

function streamJobLog(jobId, logEl) {
  logEl.style.display = 'block'; logEl.innerHTML = '';
  const es = new EventSource(`${API}/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const {event: evt, data: d} = JSON.parse(e.data);
    let line = '';
    if (evt === 'task_started') line = `<span class="ev">&#9654; ${d.task_id}</span> (${d.index+1}/${d.total})`;
    else if (evt === 'task_scored') line = `<span class="ev">&#10003; ${d.task_id}</span> &rarr; <span class="sc">${(d.score*100).toFixed(1)}%</span>`;
    else if (evt === 'job_completed') { line = '<span class="sc">&#10003; Complete</span>'; es.close(); reload().then(() => nav('job-detail', jobId)); return; }
    else if (evt === 'job_failed') { line = `<span class="err">&#10007; ${d.error||'failed'}</span>`; es.close(); reload(); return; }
    else if (evt === 'done') { es.close(); reload().then(() => nav('job-detail', jobId)); return; }
    else if (evt === 'iteration_complete') line = `<span class="ev">Iter ${d.iteration}</span> avg=<span class="sc">${(d.avg_score*100).toFixed(1)}%</span> ${d.accepted?'&#10003;':'&#10007;'} ${d.summary||''}`;
    else return;
    logEl.innerHTML += `<div class="log-line">${new Date().toLocaleTimeString()} ${line}</div>`;
    logEl.scrollTop = logEl.scrollHeight;
  };
  es.onerror = () => { es.close(); reload(); };
}

// ─── HILL CLIMB VIEW ───
function viewHillClimb(m) {
  const hcJobs = _jobs.filter(j => j.type === 'hill_climb');
  const skillOpts = _skills.map(s => `<option value="${s.id}">${s.name} v${s.version}</option>`).join('');
  const taskChecks = _tasks.map(t =>
    `<label><input type="checkbox" name="hc-task" value="${t.id}" checked> ${t.id}</label>`).join('');

  m.innerHTML = `
    <div class="page-hdr"><div><h2>Hill Climb</h2><div class="sub">Optimize skills via iterative evaluation</div></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">Configure Optimization</div><div class="card-body">
        <div class="form-grid">
          <div class="form-group"><label>Skill to Optimize</label>
            <select id="hc-skill"><option value="">— select —</option>${skillOpts}</select></div>
          <div class="form-group"><label>Model</label>
            <select id="hc-model"><option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-6" selected>Sonnet 4.6</option></select></div>
          <div class="form-group"><label>Strategy</label>
            <select id="hc-strat"><option value="greedy">Greedy</option><option value="beam">Beam (K=3)</option>
              <option value="gradient" selected>Gradient</option></select></div>
          <div class="form-group"><label>Iterations</label>
            <input type="number" id="hc-iters" value="3" min="1" max="20"></div>
        </div>
        <div class="form-group mt-16"><label>Tasks</label><div class="checklist">${taskChecks}</div></div>
        <div class="mt-16"><button class="btn btn-primary" id="hc-submit" onclick="submitHC()">Start Optimization</button></div>
      </div></div>
      <div class="card"><div class="card-hdr">Runs</div><div class="card-body flush">
        <table><thead><tr><th>ID</th><th>Status</th><th>Model</th></tr></thead>
        <tbody>${hcJobs.map(j => `<tr class="clickable" onclick="nav('hc-detail','${j.id}')">
          <td><code class="mono">${j.id.slice(0,10)}</code></td><td>${badge(j.status)}</td>
          <td class="meta">${j.model.replace('claude-','')}</td></tr>`).join('') ||
          '<tr><td colspan="3" class="empty">No runs</td></tr>'}</tbody></table>
      </div></div>
    </div>
    <div id="hc-log" class="live-log mt-16" style="display:none"></div>
    <div id="hc-detail-panel"></div>`;
}

async function submitHC() {
  const skill = el('hc-skill').value;
  if (!skill) return alert('Select a skill');
  const taskIds = [...document.querySelectorAll('input[name="hc-task"]:checked')].map(c => c.value);
  el('hc-submit').disabled = true;
  const body = {
    type: 'hill_climb', skill_id: skill,
    task_ids: taskIds.length ? taskIds : null,
    model: el('hc-model').value,
    config: { max_iterations: parseInt(el('hc-iters').value)||3, strategy: el('hc-strat').value,
      beam_width: 3, improvement_threshold: 0.005, enable_thinking: false, judge_model: el('hc-model').value }
  };
  const job = await api('/jobs', {method:'POST', body: JSON.stringify(body)});
  await reload();
  streamJobLog(job.id, el('hc-log'));
}

async function viewHCDetail(m, jobId) {
  const [job, iters] = await Promise.all([api(`/jobs/${jobId}`), api(`/jobs/${jobId}/iterations`)]);
  const s = job.summary || {};

  let html = `
    <div class="breadcrumb"><a onclick="nav('hillclimb')">Hill Climb</a> / <span>${jobId.slice(0,10)}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body">
        <div class="meta mb-12">IMPROVEMENT</div>
        <div style="display:flex;align-items:baseline;gap:12px">
          ${s.initial_avg !== undefined ? `<span class="score-big" style="color:var(--text3)">${(s.initial_avg*100).toFixed(0)}%</span>
            <span style="font-size:24px;color:var(--text3)">&rarr;</span>` : ''}
          <span class="score-big ${scoreColor(s.final_avg||0)}">${s.final_avg !== undefined ? (s.final_avg*100).toFixed(1)+'%' : '—'}</span>
          ${s.improvement > 0 ? `<span class="badge badge-completed">+${(s.improvement*100).toFixed(1)}%</span>` : ''}
        </div>
        ${s.new_skill_id ? `<div class="meta mt-8">New actor: <code>${s.new_skill_id}</code></div>` : ''}
      </div></div>
      <div class="card"><div class="card-body gap-12" style="display:flex;flex-direction:column;gap:8px">
        <div class="flex-between"><span class="meta">STATUS</span>${badge(job.status)}</div>
        <div class="flex-between"><span class="meta">STRATEGY</span><span>${(job.config||{}).strategy||'greedy'}</span></div>
        <div class="flex-between"><span class="meta">ITERATIONS</span><span>${iters.length}</span></div>
        <div class="flex-between"><span class="meta">SKILL</span><span>${job.skill_id}</span></div>
      </div></div>
    </div>`;

  html += `<div class="card"><div class="card-hdr">Iterations</div><div class="card-body">`;
  for (const it of iters) {
    const border = it.iteration_number === 0 ? 'var(--border)' : it.accepted ? 'var(--green)' : 'var(--red)';
    html += `<div style="border-left:3px solid ${border};padding-left:14px;margin-bottom:18px">
      <div class="flex-between mb-12">
        <span><strong>Iteration ${it.iteration_number}</strong>
          ${it.iteration_number > 0 ? (it.accepted ? '<span class="badge badge-completed">accepted</span>' : '<span class="badge badge-failed">rejected</span>') : '<span class="badge badge-pending">baseline</span>'}</span>
        <span class="score-pill ${scoreColor(it.avg_score)}">${(it.avg_score*100).toFixed(1)}%</span>
      </div>`;
    if (it.change_summary && it.iteration_number > 0)
      html += `<div class="meta mb-12">${esc(it.change_summary)}</div>`;
    const scores = it.per_task_scores || {};
    for (const [tid, sc] of Object.entries(scores).sort((a,b) => a[1]-b[1])) {
      const pct = sc * 100;
      html += `<div style="display:flex;align-items:center;gap:8px;padding:2px 0;font-size:12px">
        <span style="min-width:140px" class="mono">${tid}</span>
        <div class="score-bar" style="flex:1"><div class="score-track"><div class="score-fill" style="width:${pct}%;background:${scoreFillColor(sc)}"></div></div>
        <span class="score-label ${scoreColor(sc)}" style="font-size:11px">${pct.toFixed(0)}%</span></div></div>`;
    }
    if (it.skill_content && it.iteration_number > 0)
      html += `<details class="mt-8"><summary style="font-size:11px;color:var(--accent);cursor:pointer">View skill prompt</summary>
        <div style="font-family:var(--mono);font-size:11px;white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:5px;margin-top:6px;max-height:250px;overflow-y:auto">${esc(it.skill_content)}</div></details>`;
    html += `</div>`;
  }
  html += `</div></div>`;
  m.innerHTML = html;
}

// ─── Boot ───
async function boot() {
  try {
    const h = await fetch('/health').then(r => r.json());
    el('mode').textContent = h.api_key_set ? 'SDK' : 'CLI';
    el('dot').classList.toggle('off', false);
  } catch {
    el('mode').textContent = 'offline';
    el('dot').classList.add('off');
  }
  await reload();
  nav('jobs');
}
document.addEventListener('DOMContentLoaded', boot);
