const API = '/api/v1';
let _tasks = [], _skills = [], _jobs = [], _episodes = [];

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: {'Content-Type':'application/json'}, ...opts });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
function scoreClass(s) { return s >= .9 ? 'score-high' : s >= .5 ? 'score-mid' : 'score-low'; }
function scoreFill(s) { return s >= .9 ? 'var(--green)' : s >= .5 ? 'var(--yellow)' : 'var(--red)'; }
function badge(s) { return `<span class="badge badge-${s}">${s}</span>`; }
function shortModel(m) { return (m||'').replace('claude-','').replace('-20251001',''); }
function fmtTime(t) { try { return new Date(t+(t.includes('T')?'':'Z')).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); } catch{return t||'';} }
function el(id) { return document.getElementById(id); }

// ─── Nav ───
function nav(view, ...args) {
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`.sidebar-item[data-view="${view}"]`);
  if (btn) btn.classList.add('active');
  ({runs:viewRuns, 'new-run':viewNewRun, tests:viewTests, actors:viewActors,
    sessions:viewSessions, hillclimb:viewHillClimb, 'run-detail':viewRunDetail,
    'result-detail':viewResultDetail, 'episode-detail':viewEpisodeDetail,
    'hc-detail':viewHCDetail}[view] || (()=>{}))(el('main'), ...args);
}

async function reload() {
  [_tasks, _skills, _jobs, _episodes] = await Promise.all([
    api('/tasks'), api('/skills'), api('/jobs'),
    api('/mining/episodes?limit=200').catch(()=>[]),
  ]);
  const r = el('cnt-runs'); if(r) r.textContent = _jobs.filter(j=>j.type==='benchmark').length;
  const t = el('cnt-tests'); if(t) t.textContent = _tasks.length;
  const a = el('cnt-actors'); if(a) a.textContent = _skills.length;
}

// ═══ RUNS ═══
function viewRuns(m) {
  const runs = _jobs.filter(j => j.type === 'benchmark');
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Eval Runs</h2><div class="sub">${runs.length} runs</div></div>
      <button class="btn btn-primary" onclick="nav('new-run')">+ New Run</button></div>
    <div class="card"><div class="card-body flush">
    <table><thead><tr><th>Run</th><th>Status</th><th>Actor</th><th>Sampler</th><th>Score</th><th>Time</th></tr></thead>
    <tbody id="runs-tbody">${runs.length ? runs.map(j => `<tr class="clickable" onclick="nav('run-detail','${j.id}')">
      <td><code class="mono">${j.id.slice(0,8)}</code></td>
      <td>${badge(j.status)}</td>
      <td>${j.skill_id || '<span class="meta">none</span>'}</td>
      <td class="meta">${shortModel(j.model)}</td>
      <td id="score-${j.id}"><span class="meta">—</span></td>
      <td class="meta">${fmtTime(j.created_at)}</td></tr>`).join('') :
      '<tr><td colspan="6" class="empty">No eval runs yet. Click New Run to start.</td></tr>'}</tbody>
    </table></div></div>`;
  runs.filter(j => j.status === 'completed').forEach(async j => {
    const d = await api(`/jobs/${j.id}`);
    const avg = d.summary?.avg_score;
    if (avg !== undefined) {
      const cell = el(`score-${j.id}`);
      if (cell) cell.innerHTML = `<span class="score-pill ${scoreClass(avg)}">${(avg*100).toFixed(1)}%</span>`;
    }
  });
}

// ═══ NEW RUN ═══
function viewNewRun(m) {
  const taskChecks = _tasks.map(t =>
    `<label><input type="checkbox" name="task" value="${t.id}" checked>
     <strong>${t.id}</strong> <span class="meta">${t.turns.length}t · ${t.assertions.length} rubrics</span></label>`).join('');
  const skillOpts = _skills.map(s => `<option value="${s.id}">${s.name} v${s.version}</option>`).join('');

  m.innerHTML = `
    <div class="page-hdr"><div><h2>New Eval Run</h2><div class="sub">Configure actor, sampler, test cases, and run</div></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">Actor <span class="meta">(what's being tested)</span></div><div class="card-body">
        <div class="form-group mb-12"><label>Skill / System Prompt</label>
          <select id="nr-skill"><option value="">— no skill (baseline) —</option>${skillOpts}</select></div>
        <div class="form-group"><label>Or paste a system prompt</label>
          <textarea id="nr-sysprompt" rows="4" placeholder="You are a senior engineer..."></textarea></div>
      </div></div>
      <div class="card"><div class="card-hdr">Sampler <span class="meta">(model config)</span></div><div class="card-body">
        <div class="form-grid">
          <div class="form-group"><label>Model</label>
            <select id="nr-model">
              <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-6" selected>Sonnet 4.6</option>
              <option value="claude-opus-4-6">Opus 4.6</option></select></div>
          <div class="form-group"><label>Thinking</label>
            <select id="nr-thinking"><option value="on">On</option><option value="off">Off</option></select></div>
          <div class="form-group"><label>Judge Model</label>
            <select id="nr-judge">
              <option value="claude-haiku-4-5-20251001">Haiku 4.5</option>
              <option value="claude-sonnet-4-6" selected>Sonnet 4.6</option></select></div>
        </div>
      </div></div>
    </div>
    <div class="card mt-16"><div class="card-hdr">Test Cases <span class="meta">${_tasks.length} available</span>
      <button class="btn btn-ghost btn-sm" onclick="nav('tests')">Manage</button></div>
      <div class="card-body"><div class="checklist">${taskChecks || '<div class="empty">No test cases. <a onclick="nav(\'tests\')">Create some</a> or <a onclick="nav(\'sessions\')">mine from sessions</a>.</div>'}</div></div></div>
    <div style="margin-top:16px;display:flex;gap:12px">
      <button class="btn btn-primary" id="nr-go" onclick="submitRun()">Run Eval</button>
    </div>
    <div id="nr-log" class="live-log mt-16" style="display:none"></div>`;
}

async function submitRun() {
  const taskIds = [...document.querySelectorAll('input[name="task"]:checked')].map(c => c.value);
  if (!taskIds.length) return alert('Select at least one test case');
  const thinking = el('nr-thinking').value === 'on';
  const skillId = el('nr-skill').value;
  const sysprompt = el('nr-sysprompt').value.trim();

  let actorId = skillId || null;
  if (!actorId && sysprompt) {
    const id = 'inline_' + Date.now().toString(36);
    await api('/skills', {method:'POST', body: JSON.stringify({id, name: id, content: sysprompt})});
    actorId = id;
    await reload();
  }

  const body = { type: 'benchmark', task_ids: taskIds, skill_id: actorId,
    model: el('nr-model').value,
    config: { enable_thinking: thinking, thinking_budget: thinking ? 5000 : 0,
      judge_model: el('nr-judge').value, use_cli_sandbox: true }};

  el('nr-go').disabled = true;
  try {
    const job = await api('/jobs', {method:'POST', body: JSON.stringify(body)});
    await reload();
    streamLog(job.id, el('nr-log'), () => { reload().then(() => nav('run-detail', job.id)); });
  } catch(e) { alert(e.message); el('nr-go').disabled = false; }
}

function streamLog(jobId, logEl, onDone) {
  logEl.style.display = 'block'; logEl.innerHTML = '';
  const es = new EventSource(`${API}/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const {event:evt, data:d} = JSON.parse(e.data);
    let line = '';
    if (evt === 'task_started') line = `<span class="ev">▶ ${d.task_id}</span> (${d.index+1}/${d.total})`;
    else if (evt === 'task_scored') line = `<span class="ev">✓ ${d.task_id}</span> → <span class="sc">${(d.score*100).toFixed(1)}%</span>`;
    else if (evt === 'job_completed') { line = '<span class="sc">✓ Complete</span>'; es.close(); if(onDone) onDone(); return; }
    else if (evt === 'job_failed') { line = `<span class="err">✗ ${d.error||'failed'}</span>`; es.close(); reload(); return; }
    else if (evt === 'done') { es.close(); if(onDone) onDone(); return; }
    else if (evt === 'iteration_complete') line = `<span class="ev">Iter ${d.iteration}</span> avg=<span class="sc">${(d.avg_score*100).toFixed(1)}%</span> ${d.accepted?'✓':'✗'} ${(d.summary||'').slice(0,60)}`;
    else if (evt === 'episode_mined') line = `<span class="ev">Mined</span> ${(d.intent||'').slice(0,60)}`;
    else return;
    logEl.innerHTML += `<div class="log-line">${new Date().toLocaleTimeString()} ${line}</div>`;
    logEl.scrollTop = logEl.scrollHeight;
  };
  es.onerror = () => { es.close(); reload(); };
}

// ═══ RUN DETAIL ═══
async function viewRunDetail(m, jobId) {
  const [job, results] = await Promise.all([api(`/jobs/${jobId}`), api(`/jobs/${jobId}/results`)]);
  const avg = job.summary?.avg_score ?? 0;
  const cfg = job.config || {};

  m.innerHTML = `
    <div class="breadcrumb"><a onclick="nav('runs')">Runs</a> / <span>${jobId.slice(0,8)}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body">
        <div class="meta mb-12">OVERALL SCORE</div>
        <div class="score-big ${scoreClass(avg)}">${job.status==='completed'?(avg*100).toFixed(1)+'%':'—'}</div>
        <div class="meta mt-8">${results.length} test cases · ${job.status}</div>
      </div></div>
      <div class="card"><div class="card-body gap-12" style="display:flex;flex-direction:column;gap:6px">
        <div class="flex-between"><span class="meta">ACTOR</span><span>${job.skill_id||'none'}</span></div>
        <div class="flex-between"><span class="meta">SAMPLER</span><span class="mono" style="font-size:12px">${shortModel(job.model)} ${cfg.enable_thinking?'· thinking':'· no-think'}</span></div>
        <div class="flex-between"><span class="meta">JUDGE</span><span class="mono" style="font-size:12px">${shortModel(cfg.judge_model||job.model)}</span></div>
        <div class="flex-between"><span class="meta">CREATED</span><span class="meta">${fmtTime(job.created_at)}</span></div>
        <div style="margin-top:4px"><button class="btn btn-ghost btn-sm" onclick="cloneRun('${jobId}')">Re-run</button>
        ${job.status==='running'?`<button class="btn btn-ghost btn-sm" style="color:var(--red)" onclick="cancelRun('${jobId}')">Cancel</button>`:''}</div>
      </div></div>
    </div>
    <div class="card"><div class="card-hdr">Results</div><div class="card-body flush">
    <table><thead><tr><th>Test Case</th><th>Score</th><th>Rubric</th><th></th></tr></thead>
    <tbody>${results.map(r => {
      const pct = r.overall_score * 100;
      return `<tr class="clickable" onclick="nav('result-detail','${jobId}','${r.task_id}')">
        <td><strong>${r.task_id}</strong></td>
        <td style="width:220px"><div class="score-bar">
          <div class="score-track"><div class="score-fill" style="width:${pct}%;background:${scoreFill(r.overall_score)}"></div></div>
          <span class="score-label ${scoreClass(r.overall_score)}">${pct.toFixed(1)}%</span></div></td>
        <td>${r.assertions_passed}/${r.assertions_total}</td>
        <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();nav('result-detail','${jobId}','${r.task_id}')">Details</button></td></tr>`;
    }).join('')||'<tr><td colspan="4" class="empty">No results</td></tr>'}</tbody></table></div></div>`;
}

async function cloneRun(id) { await api(`/jobs/${id}/clone`,{method:'POST'}); await reload(); nav('runs'); }
async function cancelRun(id) { await api(`/jobs/${id}`,{method:'DELETE'}); await reload(); nav('runs'); }

// ═══ RESULT DETAIL ═══
async function viewResultDetail(m, jobId, taskId) {
  const [d, taskDef] = await Promise.all([
    api(`/jobs/${jobId}/results/${taskId}`),
    api(`/tasks/${taskId}`).catch(()=>null),
  ]);

  let html = `
    <div class="breadcrumb"><a onclick="nav('runs')">Runs</a> / <a onclick="nav('run-detail','${jobId}')">${jobId.slice(0,8)}</a> / <span>${taskId}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body">
        <div class="meta mb-12">SCORE</div>
        <div class="score-big ${scoreClass(d.overall_score)}">${(d.overall_score*100).toFixed(1)}%</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="meta mb-12">TEST CASE</div>
        <div style="font-weight:600">${taskId}</div>
        ${taskDef?`<div class="meta mt-8">${esc(taskDef.description||taskDef.name)}</div>`:''}
      </div></div>
    </div>`;

  // Rubric
  html += `<div class="card"><div class="card-hdr">Rubric <span class="meta">${d.assertion_results.length} checks</span></div><div class="card-body"><div class="rubric-list">`;
  for (const a of d.assertion_results) {
    const icon = a.passed ? '<span class="rubric-icon rubric-pass">✓</span>' : '<span class="rubric-icon rubric-fail">✗</span>';
    html += `<div class="rubric-row">${icon}<span class="rubric-type">${a.type}</span><span class="rubric-detail">${esc(a.details)}</span></div>`;
  }
  html += '</div></div></div>';

  // Judge
  if (d.judge_results.length) {
    html += `<div class="card"><div class="card-hdr">LLM Judge</div><div class="card-body">`;
    for (const j of d.judge_results) {
      html += `<div class="judge-block mb-12">
        <div class="judge-score ${scoreClass(j.score)}">${(j.score*100).toFixed(0)}%</div>
        <div class="judge-reasoning">${esc(j.reasoning)}</div>
        <details class="mt-8"><summary style="font-size:11px;color:var(--text3);cursor:pointer">Criteria</summary>
        <div class="meta mt-8" style="white-space:pre-wrap">${esc(j.prompt)}</div></details></div>`;
    }
    html += '</div></div>';
  }

  // Turns
  html += `<div class="card"><div class="card-hdr">Turn-by-Turn Trace <span class="meta">${d.turns.length} turns</span></div><div class="card-body">`;
  for (const t of d.turns) {
    html += `<div class="turn-card">
      <div class="turn-hdr">
        <span><span class="turn-num">Turn ${t.turn_index}</span></span>
        <span>${t.duration_ms}ms · ${t.input_tokens}in/${t.output_tokens}out${t.tool_calls.length?` · ${t.tool_calls.length} tools`:''}</span>
      </div><div class="turn-body">
        <div class="msg"><div class="msg-role user">User</div><div class="msg-text">${esc(t.user_input)}</div></div>
        <div class="msg"><div class="msg-role assistant">Assistant</div><div class="msg-text">${esc(t.assistant_response)}</div></div>
        ${t.thinking_trace?`<details class="thinking-toggle"><summary>Thinking (${t.thinking_trace.length} chars)</summary><div class="thinking-text">${esc(t.thinking_trace)}</div></details>`:''}
        ${t.tool_calls.length?`<div class="tool-calls">${t.tool_calls.map(tc=>`<div style="margin:4px 0"><code>${tc.tool_name}</code> <span class="meta">${tc.duration_ms}ms</span><details><summary class="meta" style="cursor:pointer">input/output</summary><pre class="msg-text" style="margin-top:4px">${esc(JSON.stringify(tc.input,null,2).slice(0,500))}</pre><pre class="msg-text" style="margin-top:4px">${esc((tc.output||'').slice(0,500))}</pre></details></div>`).join('')}</div>`:''}
      </div></div>`;
  }
  html += '</div></div>';
  m.innerHTML = html;
}

// ═══ TEST CASES ═══
function viewTests(m) {
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Test Cases</h2><div class="sub">${_tasks.length} cases</div></div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary btn-sm" onclick="showCreateTest()">+ Create</button>
        <button class="btn btn-ghost btn-sm" onclick="importYaml()">Import YAML</button>
      </div></div>
    <div id="create-test-form" style="display:none"></div>
    <div class="card"><div class="card-body flush">
    <table><thead><tr><th>ID</th><th>Name</th><th>Turns</th><th>Rubric</th><th>Tags</th></tr></thead>
    <tbody>${_tasks.map(t => `<tr class="clickable" onclick="showTest('${t.id}')">
      <td><code class="mono">${t.id}</code></td><td>${esc(t.name).slice(0,50)}</td>
      <td>${t.turns.length}</td><td>${t.assertions.length}</td>
      <td>${(t.tags||[]).map(tg=>`<span class="tag">${tg}</span>`).join(' ')}</td></tr>`).join('')||
      '<tr><td colspan="5" class="empty">No test cases yet</td></tr>'}</tbody></table></div></div>
    <div id="test-detail-panel"></div>`;
}

function showCreateTest() {
  el('create-test-form').style.display = 'block';
  el('create-test-form').innerHTML = `
    <div class="card mb-12"><div class="card-hdr">Create Test Case</div><div class="card-body">
      <div class="form-grid">
        <div class="form-group"><label>ID</label><input id="ct-id" placeholder="my_test_1"></div>
        <div class="form-group"><label>Name</label><input id="ct-name" placeholder="Test description"></div>
        <div class="form-group full"><label>User Prompt (one per line for multi-turn)</label>
          <textarea id="ct-turns" rows="4" placeholder="Write a fibonacci function in Python"></textarea></div>
        <div class="form-group full"><label>Judge Criteria (what 'good' looks like)</label>
          <textarea id="ct-judge" rows="3" placeholder="The function should use iteration, handle edge cases, include type hints"></textarea></div>
        <div class="form-group"><label>Expected in response</label>
          <input id="ct-contains" placeholder="def fibonacci (optional)"></div>
        <div class="form-group"><label>Tags</label><input id="ct-tags" placeholder="python, code-gen"></div>
      </div>
      <div class="mt-16"><button class="btn btn-primary" onclick="createTest()">Create</button>
        <button class="btn btn-ghost" onclick="el('create-test-form').style.display='none'">Cancel</button></div>
    </div></div>`;
}

async function createTest() {
  const id = el('ct-id').value.trim();
  const name = el('ct-name').value.trim();
  const turnsRaw = el('ct-turns').value.trim();
  const judge = el('ct-judge').value.trim();
  const contains = el('ct-contains').value.trim();
  const tags = el('ct-tags').value.split(',').map(s=>s.trim()).filter(Boolean);
  if (!id || !turnsRaw) return alert('ID and prompt required');

  const turns = turnsRaw.split('\n').filter(s=>s.trim()).map(s=>({role:'user',content:s.trim(),wait_for_completion:true}));
  const assertions = [];
  if (judge) assertions.push({type:'llm_judge',target:judge,expected:null,weight:3.0});
  if (contains) assertions.push({type:'response_contains',target:'response',expected:contains,weight:1.0});

  await api('/tasks',{method:'POST',body:JSON.stringify({id,name:name||id,turns,assertions,tags})});
  await reload(); nav('tests');
}

async function importYaml() {
  await api('/tasks/import',{method:'POST'});
  await reload(); nav('tests');
}

function showTest(id) {
  const t = _tasks.find(x=>x.id===id); if(!t) return;
  el('test-detail-panel').innerHTML = `<div class="card mt-16"><div class="card-hdr">${esc(t.id)}</div><div class="card-body">
    <div class="meta mb-12">${esc(t.name)}</div>
    <div class="mb-12"><strong style="font-size:11px;color:var(--text3)">TURNS</strong>
    ${t.turns.map((turn,i)=>`<div class="turn-card mt-8"><div class="turn-hdr"><span class="turn-num">Turn ${i}</span></div>
      <div class="turn-body"><div class="msg-text">${esc(turn.content)}</div></div></div>`).join('')}</div>
    <div><strong style="font-size:11px;color:var(--text3)">RUBRIC</strong>
    <div class="rubric-list mt-8">${t.assertions.map(a=>`<div class="rubric-row"><span class="rubric-type">${a.type}</span>
      <span class="rubric-detail">${esc(a.target)} ${a.expected?'| expect: '+esc(String(a.expected)):''} | w=${a.weight}</span></div>`).join('')}</div></div>
  </div></div>`;
}

// ═══ ACTORS ═══
function viewActors(m) {
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Actors</h2><div class="sub">Skills and system prompts being tested</div></div>
      <button class="btn btn-ghost btn-sm" onclick="importSkills()">Import from disk</button></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">All Actors</div><div class="card-body flush">
        <table><thead><tr><th>ID</th><th>Name</th><th>v</th></tr></thead>
        <tbody>${_skills.map(s=>`<tr class="clickable" onclick="showActor('${s.id}')">
          <td><code class="mono">${s.id}</code></td><td>${s.name}</td><td>v${s.version}</td></tr>`).join('')||
          '<tr><td colspan="3" class="empty">No actors</td></tr>'}</tbody></table></div></div>
      <div class="card"><div class="card-hdr">Create Actor</div><div class="card-body">
        <div class="form-group mb-12"><label>ID</label><input id="ac-id" placeholder="my_skill_v1"></div>
        <div class="form-group mb-12"><label>System Prompt / Skill Content</label>
          <textarea id="ac-content" rows="8" placeholder="You are a senior software engineer..."></textarea></div>
        <button class="btn btn-primary" onclick="createActor()">Create</button>
      </div></div>
    </div><div id="actor-detail-panel"></div>`;
}

function showActor(id) {
  const s = _skills.find(x=>x.id===id); if(!s) return;
  el('actor-detail-panel').innerHTML = `<div class="card mt-16"><div class="card-hdr">${s.id} <span class="meta">v${s.version}</span></div>
    <div class="card-body"><pre class="msg-text" style="max-height:400px">${esc(s.content)}</pre></div></div>`;
}
async function createActor() {
  const id=el('ac-id').value.trim(), c=el('ac-content').value.trim();
  if(!id||!c) return alert('ID and content required');
  await api('/skills',{method:'POST',body:JSON.stringify({id,name:id,content:c})});
  await reload(); nav('actors');
}
async function importSkills() {
  const r = await api('/skills/import-files',{method:'POST'}); alert(`Imported ${r.imported} skills`); await reload(); nav('actors');
}

// ═══ SESSIONS ═══
async function viewSessions(m) {
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Mine Sessions</h2><div class="sub">Extract test cases from real Claude sessions</div></div>
      <button class="btn btn-primary" onclick="mineNow()">Mine Sessions</button></div>
    <div id="mine-log" class="live-log" style="display:none"></div>
    <div class="card mt-16"><div class="card-hdr">Mined Episodes <span class="meta">${_episodes.length}</span></div><div class="card-body flush">
    <table><thead><tr><th>Intent</th><th>Tags</th><th>Status</th></tr></thead>
    <tbody>${_episodes.length?_episodes.map(ep=>{
      const status = ep.promoted_task_id?`<span class="badge badge-completed">promoted</span>`
        :`<button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();promoteEp('${ep.id}')">Promote</button>`;
      return `<tr class="clickable" onclick="nav('episode-detail','${ep.id}')">
        <td style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(ep.user_intent)}</td>
        <td>${(ep.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ')}</td>
        <td>${status}</td></tr>`;}).join(''):'<tr><td colspan="3" class="empty">Click Mine Sessions to extract from your Claude history</td></tr>'}</tbody>
    </table></div></div>`;
}
async function mineNow() {
  const log=el('mine-log'); log.style.display='block'; log.innerHTML='<div class="log-line">Mining...</div>';
  const r = await api('/mining/mine',{method:'POST',body:JSON.stringify({max_sessions:30})});
  log.innerHTML+=`<div class="log-line"><span class="sc">Done: ${r.stored} new episodes</span></div>`;
  await reload(); nav('sessions');
}
async function promoteEp(id) {
  await api(`/mining/episodes/${id}/promote`,{method:'POST',body:JSON.stringify({auto_judge:true})});
  await reload(); nav('sessions');
}

async function viewEpisodeDetail(m, id) {
  const ep = await api(`/mining/episodes/${id}`);
  let html = `<div class="breadcrumb"><a onclick="nav('sessions')">Sessions</a> / <span>${id.slice(0,8)}</span></div>
    <div class="card mb-12"><div class="card-body">
      <div style="font-size:15px;font-weight:500;margin-bottom:8px">${esc(ep.user_intent)}</div>
      <div>${(ep.tags||[]).map(t=>`<span class="tag">${t}</span>`).join(' ')}</div>
      <div class="meta mt-8">Session ${ep.session_id.slice(0,8)} · ${ep.tokens?.input||0}in/${ep.tokens?.output||0}out tokens</div>
      ${!ep.promoted_task_id?`<button class="btn btn-primary btn-sm mt-8" onclick="promoteEp('${ep.id}');nav('sessions')">Promote to Test Case</button>`
        :`<span class="badge badge-completed mt-8">Promoted → ${ep.promoted_task_id}</span>`}
    </div></div>
    <div class="card"><div class="card-hdr">Original Conversation</div><div class="card-body">`;
  for (const t of ep.turns) {
    if (t.role==='user') html+=`<div class="turn-card mt-8"><div class="turn-body"><div class="msg"><div class="msg-role user">User</div><div class="msg-text">${esc(t.content)}</div></div></div></div>`;
    else if (t.role==='assistant') html+=`<div class="turn-card mt-8"><div class="turn-body"><div class="msg"><div class="msg-role assistant">Assistant</div><div class="msg-text">${esc(t.content)}</div></div></div></div>`;
    else if (t.role==='thinking') html+=`<details class="thinking-toggle mt-8"><summary>Thinking</summary><div class="thinking-text">${esc(t.content)}</div></details>`;
    else if (t.role==='tool_use') html+=`<div class="turn-card mt-8" style="border-left:2px solid var(--accent)"><div class="turn-body"><code>${t.tool_name}</code><div class="msg-text" style="max-height:80px">${esc(JSON.stringify(t.input,null,2))}</div></div></div>`;
    else if (t.role==='tool_result') html+=`<div class="turn-card mt-8" style="border-left:2px solid var(--text3)"><div class="turn-body"><div class="meta">Result</div><div class="msg-text" style="max-height:80px">${esc(t.content)}</div></div></div>`;
  }
  html+='</div></div>'; m.innerHTML=html;
}

// ═══ HILL CLIMB ═══
function viewHillClimb(m) {
  const hcJobs = _jobs.filter(j=>j.type==='hill_climb');
  const skillOpts = _skills.map(s=>`<option value="${s.id}">${s.name} v${s.version}</option>`).join('');
  const taskChecks = _tasks.map(t=>`<label><input type="checkbox" name="hc-task" value="${t.id}" checked>${t.id}</label>`).join('');
  m.innerHTML = `
    <div class="page-hdr"><div><h2>Hill Climb</h2><div class="sub">Optimize actors by iterating on test results</div></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-hdr">Configure</div><div class="card-body">
        <div class="form-grid">
          <div class="form-group"><label>Actor to optimize</label><select id="hc-skill"><option value="">select</option>${skillOpts}</select></div>
          <div class="form-group"><label>Model</label><select id="hc-model"><option value="claude-haiku-4-5-20251001">Haiku</option><option value="claude-sonnet-4-6" selected>Sonnet</option></select></div>
          <div class="form-group"><label>Strategy</label><select id="hc-strat"><option value="greedy">Greedy</option><option value="beam">Beam</option><option value="gradient" selected>Gradient</option></select></div>
          <div class="form-group"><label>Iterations</label><input type="number" id="hc-iters" value="3" min="1" max="20"></div>
        </div>
        <div class="form-group mt-16"><label>Test Cases</label><div class="checklist">${taskChecks}</div></div>
        <button class="btn btn-primary mt-16" id="hc-go" onclick="startHC()">Start</button>
      </div></div>
      <div class="card"><div class="card-hdr">Runs</div><div class="card-body flush">
        <table><thead><tr><th>ID</th><th>Status</th></tr></thead>
        <tbody>${hcJobs.map(j=>`<tr class="clickable" onclick="nav('hc-detail','${j.id}')">
          <td><code class="mono">${j.id.slice(0,8)}</code></td><td>${badge(j.status)}</td></tr>`).join('')||
          '<tr><td colspan="2" class="empty">No runs</td></tr>'}</tbody></table></div></div>
    </div><div id="hc-log" class="live-log mt-16" style="display:none"></div>`;
}
async function startHC() {
  const skill=el('hc-skill').value; if(!skill) return alert('Select an actor');
  const taskIds=[...document.querySelectorAll('input[name="hc-task"]:checked')].map(c=>c.value);
  el('hc-go').disabled=true;
  const body={type:'hill_climb',skill_id:skill,task_ids:taskIds.length?taskIds:null,model:el('hc-model').value,
    config:{max_iterations:parseInt(el('hc-iters').value)||3,strategy:el('hc-strat').value,beam_width:3,
      improvement_threshold:0.005,enable_thinking:false,judge_model:el('hc-model').value,use_cli_sandbox:true}};
  const job=await api('/jobs',{method:'POST',body:JSON.stringify(body)});
  await reload();
  streamLog(job.id,el('hc-log'),()=>{reload().then(()=>nav('hc-detail',job.id));});
}

async function viewHCDetail(m, jobId) {
  const [job,iters]=await Promise.all([api(`/jobs/${jobId}`),api(`/jobs/${jobId}/iterations`)]);
  const s=job.summary||{};
  let html=`<div class="breadcrumb"><a onclick="nav('hillclimb')">Hill Climb</a> / <span>${jobId.slice(0,8)}</span></div>
    <div class="grid-2 mb-12">
      <div class="card"><div class="card-body"><div class="meta mb-12">IMPROVEMENT</div>
        <div style="display:flex;align-items:baseline;gap:12px">
          ${s.initial_avg!==undefined?`<span class="score-big" style="color:var(--text3)">${(s.initial_avg*100).toFixed(0)}%</span><span style="font-size:24px;color:var(--text3)">→</span>`:''}
          <span class="score-big ${scoreClass(s.final_avg||0)}">${s.final_avg!==undefined?(s.final_avg*100).toFixed(1)+'%':'—'}</span>
          ${s.improvement>0?`<span class="badge badge-completed">+${(s.improvement*100).toFixed(1)}%</span>`:''}
        </div></div></div>
      <div class="card"><div class="card-body gap-12" style="display:flex;flex-direction:column;gap:6px">
        <div class="flex-between"><span class="meta">STATUS</span>${badge(job.status)}</div>
        <div class="flex-between"><span class="meta">STRATEGY</span><span>${(job.config||{}).strategy||'greedy'}</span></div>
        <div class="flex-between"><span class="meta">ACTOR</span><span>${job.skill_id}</span></div>
        ${s.new_skill_id?`<div class="flex-between"><span class="meta">NEW ACTOR</span><code class="mono" style="font-size:11px">${s.new_skill_id}</code></div>`:''}
      </div></div></div>`;
  html+=`<div class="card"><div class="card-hdr">Iterations</div><div class="card-body">`;
  for (const it of iters) {
    const bdr=it.iteration_number===0?'var(--border)':it.accepted?'var(--green)':'var(--red)';
    html+=`<div style="border-left:3px solid ${bdr};padding-left:14px;margin-bottom:16px">
      <div class="flex-between mb-12"><strong>Iter ${it.iteration_number}</strong>
        <span class="score-pill ${scoreClass(it.avg_score)}">${(it.avg_score*100).toFixed(1)}%</span></div>`;
    if(it.change_summary&&it.iteration_number>0) html+=`<div class="meta mb-12">${esc(it.change_summary)}</div>`;
    for(const[tid,sc] of Object.entries(it.per_task_scores||{}).sort((a,b)=>a[1]-b[1])){
      const pct=sc*100;
      html+=`<div style="display:flex;align-items:center;gap:8px;padding:2px 0;font-size:12px">
        <span style="min-width:140px" class="mono">${tid}</span>
        <div class="score-bar" style="flex:1"><div class="score-track"><div class="score-fill" style="width:${pct}%;background:${scoreFill(sc)}"></div></div>
        <span class="score-label ${scoreClass(sc)}" style="font-size:11px">${pct.toFixed(0)}%</span></div></div>`;}
    if(it.skill_content&&it.iteration_number>0)
      html+=`<details class="mt-8"><summary style="font-size:11px;color:var(--accent);cursor:pointer">View skill</summary>
        <pre class="msg-text" style="margin-top:6px;max-height:200px">${esc(it.skill_content)}</pre></details>`;
    html+=`</div>`;}
  html+='</div></div>'; m.innerHTML=html;
}

// ═══ Boot ═══
async function boot() {
  try { const h=await fetch('/health').then(r=>r.json()); el('mode').textContent=h.api_key_set?'SDK':'CLI'; } catch { el('mode').textContent='offline'; el('dot').classList.add('off'); }
  await reload(); nav('runs');
}
document.addEventListener('DOMContentLoaded', boot);
