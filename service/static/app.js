const API = '/api/v1';

// State
let currentTab = 'benchmark';
let pollingInterval = null;

// --- Tabs ---
function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === `panel-${tab}`));
  if (tab === 'benchmark') loadJobs();
  if (tab === 'hillclimb') loadHillClimbJobs();
}

// --- API helpers ---
async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok && res.status !== 204) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.detail || err.error || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

// --- Init ---
async function init() {
  try {
    const health = await fetch('/health').then(r => r.json());
    document.getElementById('api-status').textContent = health.api_key_set ? 'SDK mode' : 'CLI mode';
    document.querySelector('.status-dot').classList.toggle('disconnected', false);
  } catch {
    document.getElementById('api-status').textContent = 'Disconnected';
    document.querySelector('.status-dot').classList.add('disconnected');
  }

  await Promise.all([loadTasks(), loadSkills()]);
  loadJobs();
}

// --- Tasks & Skills ---
async function loadTasks() {
  const tasks = await api('/tasks');
  // Populate selects
  const checks = tasks.map(t =>
    `<label style="display:flex;gap:6px;align-items:center;font-size:13px;padding:2px 0">
      <input type="checkbox" name="task" value="${t.id}" checked> ${t.id}
      <span style="color:var(--text2);font-size:11px">(${t.turns.length}t, ${t.assertions.length}a)</span>
    </label>`
  ).join('');
  document.getElementById('task-checklist').innerHTML = checks || '<span class="empty-state">No tasks — import from YAML first</span>';
  document.getElementById('hc-task-checklist').innerHTML = checks || '';
}

async function loadSkills() {
  const skills = await api('/skills');
  const opts = skills.map(s => `<option value="${s.id}">${s.name} v${s.version}</option>`).join('');
  const empty = '<option value="">— no skills —</option>';
  document.getElementById('skill-select').innerHTML = opts || empty;
  document.getElementById('hc-skill-select').innerHTML = opts || empty;
}

async function importTasks() {
  const btn = document.getElementById('btn-import');
  btn.disabled = true; btn.textContent = 'Importing...';
  try {
    const result = await api('/tasks/import', { method: 'POST' });
    await loadTasks();
    btn.textContent = `Imported ${result.length} tasks`;
    setTimeout(() => { btn.textContent = 'Import YAML'; btn.disabled = false; }, 2000);
  } catch (e) {
    btn.textContent = 'Error'; btn.disabled = false;
    alert(e.message);
  }
}

async function createSkill() {
  const id = document.getElementById('new-skill-id').value.trim();
  const content = document.getElementById('new-skill-content').value.trim();
  if (!id || !content) return alert('Skill ID and content required');
  try {
    await api('/skills', { method: 'POST', body: JSON.stringify({ id, name: id, content }) });
    await loadSkills();
    document.getElementById('new-skill-id').value = '';
    document.getElementById('new-skill-content').value = '';
  } catch (e) { alert(e.message); }
}

// --- Benchmark Jobs ---
async function submitBenchmark() {
  const taskIds = [...document.querySelectorAll('#task-checklist input:checked')].map(c => c.value);
  const skillId = document.getElementById('skill-select').value;
  const model = document.getElementById('model-select').value;
  const thinking = document.getElementById('thinking-toggle').checked;

  if (!taskIds.length) return alert('Select at least one task');

  const body = {
    type: 'benchmark',
    task_ids: taskIds,
    skill_id: skillId || null,
    model,
    config: { enable_thinking: thinking, thinking_budget: thinking ? 5000 : 0, judge_model: model }
  };

  try {
    const job = await api('/jobs', { method: 'POST', body: JSON.stringify(body) });
    loadJobs();
    watchJob(job.id);
  } catch (e) { alert(e.message); }
}

async function loadJobs() {
  const jobs = await api('/jobs?type=benchmark');
  const tbody = document.getElementById('jobs-table');
  if (!jobs.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No benchmark jobs yet</td></tr>';
    return;
  }
  tbody.innerHTML = jobs.slice(0, 20).map(j => {
    const badge = statusBadge(j.status);
    const time = new Date(j.created_at + 'Z').toLocaleTimeString();
    return `<tr style="cursor:pointer" onclick="showJobResults('${j.id}')">
      <td><code>${j.id.slice(0, 10)}</code></td>
      <td>${badge}</td>
      <td>${j.model}</td>
      <td>${time}</td>
      <td>
        ${j.status === 'pending' || j.status === 'running'
          ? `<button class="btn btn-secondary" onclick="event.stopPropagation();cancelJob('${j.id}')" style="padding:4px 8px;font-size:11px">Cancel</button>`
          : ''}
      </td>
    </tr>`;
  }).join('');
}

function statusBadge(status) {
  const cls = { completed: 'pass', failed: 'fail', running: 'running', pending: 'pending', cancelled: 'partial' };
  return `<span class="badge badge-${cls[status] || 'pending'}">${status}</span>`;
}

async function cancelJob(id) {
  await api(`/jobs/${id}`, { method: 'DELETE' });
  loadJobs();
}

function watchJob(jobId) {
  const log = document.getElementById('job-log');
  log.innerHTML = '';
  log.style.display = 'block';

  const es = new EventSource(`${API}/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    const evt = data.event;
    const d = data.data || {};
    let line = '';

    if (evt === 'task_started') line = `<span class="event">▶ Task ${d.task_id}</span> (${d.index + 1}/${d.total})`;
    else if (evt === 'task_scored') line = `<span class="event">✓ Scored ${d.task_id}</span> → <span class="score">${(d.score * 100).toFixed(1)}%</span>`;
    else if (evt === 'job_completed') { line = '<span class="score">✓ Job completed</span>'; es.close(); loadJobs(); }
    else if (evt === 'job_failed') { line = `<span style="color:var(--red)">✗ Failed: ${d.error || ''}</span>`; es.close(); loadJobs(); }
    else if (evt === 'done') { es.close(); loadJobs(); return; }
    else line = `<span class="event">${evt}</span> ${JSON.stringify(d).slice(0, 80)}`;

    log.innerHTML += `<div class="log-entry"><span class="time">${new Date().toLocaleTimeString()}</span> ${line}</div>`;
    log.scrollTop = log.scrollHeight;
  };
  es.onerror = () => { es.close(); loadJobs(); };
}

async function showJobResults(jobId) {
  const [job, results] = await Promise.all([
    api(`/jobs/${jobId}`),
    api(`/jobs/${jobId}/results`),
  ]);

  const panel = document.getElementById('results-panel');
  const avgScore = job.summary?.avg_score ?? 0;
  const scoreColor = avgScore >= 0.9 ? 'var(--green)' : avgScore >= 0.5 ? 'var(--yellow)' : 'var(--red)';

  let html = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div>
        <h3 style="font-size:16px;margin-bottom:4px">Job ${jobId.slice(0, 10)} ${statusBadge(job.status)}</h3>
        <span style="color:var(--text2);font-size:12px">${job.model} | ${job.skill_id || 'no skill'}</span>
      </div>
      <div style="text-align:right">
        <div style="font-size:28px;font-weight:700;color:${scoreColor};font-family:var(--mono)">${(avgScore * 100).toFixed(1)}%</div>
        <div style="color:var(--text2);font-size:12px">average score</div>
      </div>
    </div>
    <table><thead><tr><th>Task</th><th>Score</th><th>Assertions</th><th>Details</th></tr></thead><tbody>`;

  for (const r of results) {
    const pct = (r.overall_score * 100).toFixed(1);
    const color = r.overall_score >= 0.9 ? 'var(--green)' : r.overall_score >= 0.5 ? 'var(--yellow)' : 'var(--red)';
    html += `<tr onclick="showResultDetail('${jobId}','${r.task_id}')" style="cursor:pointer">
      <td><strong>${r.task_id}</strong></td>
      <td>
        <div class="score-bar">
          <div class="score-bar-track"><div class="score-bar-fill" style="width:${pct}%;background:${color}"></div></div>
          <span class="score-bar-label" style="color:${color}">${pct}%</span>
        </div>
      </td>
      <td>${r.assertions_passed}/${r.assertions_total}</td>
      <td><button class="btn btn-secondary" style="padding:3px 8px;font-size:11px" onclick="event.stopPropagation();showResultDetail('${jobId}','${r.task_id}')">View</button></td>
    </tr>`;
  }
  html += '</tbody></table>';
  panel.innerHTML = html;
  panel.style.display = 'block';
}

async function showResultDetail(jobId, taskId) {
  const detail = await api(`/jobs/${jobId}/results/${taskId}`);
  const panel = document.getElementById('results-panel');

  let html = `<div style="margin-bottom:12px">
    <button class="btn btn-secondary" onclick="showJobResults('${jobId}')" style="margin-bottom:12px">← Back to results</button>
    <h3>${taskId} — ${(detail.overall_score * 100).toFixed(1)}%</h3>
  </div>`;

  // Assertions
  html += '<div style="margin-bottom:16px"><strong style="font-size:12px;color:var(--text2)">ASSERTIONS</strong>';
  for (const a of detail.assertion_results) {
    const icon = a.passed ? '<span class="assertion-icon pass">✓</span>' : '<span class="assertion-icon fail">✗</span>';
    html += `<div class="assertion-row">${icon} <code>${a.type}</code> <span style="color:var(--text2)">${a.details}</span></div>`;
  }
  html += '</div>';

  // Judge
  for (const j of detail.judge_results) {
    const color = j.score >= 0.8 ? 'var(--green)' : j.score >= 0.5 ? 'var(--yellow)' : 'var(--red)';
    html += `<div style="margin-bottom:16px"><strong style="font-size:12px;color:var(--text2)">LLM JUDGE</strong>
      <div style="margin-top:4px"><span style="font-family:var(--mono);font-weight:700;color:${color}">${(j.score * 100).toFixed(0)}%</span>
      <span style="color:var(--text2);font-size:13px;margin-left:8px">${j.reasoning}</span></div></div>`;
  }

  // Turns
  html += '<div><strong style="font-size:12px;color:var(--text2)">TURN-BY-TURN TRACE</strong>';
  for (const t of detail.turns) {
    html += `<div class="turn-block">
      <div class="turn-header">
        <span>Turn ${t.turn_index} — ${t.duration_ms}ms — ${t.input_tokens}in/${t.output_tokens}out tokens</span>
        ${t.tool_calls.length ? `<span>${t.tool_calls.length} tool calls</span>` : ''}
      </div>
      <div style="margin-bottom:6px;color:var(--accent);font-size:12px;font-weight:500">USER</div>
      <div class="turn-content">${escapeHtml(t.user_input)}</div>
      <div style="margin-top:8px;color:var(--green);font-size:12px;font-weight:500">ASSISTANT</div>
      <div class="turn-content">${escapeHtml(t.assistant_response)}</div>`;

    if (t.thinking_trace) {
      html += `<details class="thinking-block"><summary>Thinking (${t.thinking_trace.length} chars)</summary>
        <div class="turn-content" style="margin-top:6px">${escapeHtml(t.thinking_trace)}</div></details>`;
    }
    html += '</div>';
  }
  html += '</div>';

  panel.innerHTML = html;
}

// --- Hill Climb ---
async function submitHillClimb() {
  const skillId = document.getElementById('hc-skill-select').value;
  if (!skillId) return alert('Select a skill to optimize');

  const taskIds = [...document.querySelectorAll('#hc-task-checklist input:checked')].map(c => c.value);
  const model = document.getElementById('hc-model-select').value;
  const strategy = document.getElementById('hc-strategy').value;
  const iterations = parseInt(document.getElementById('hc-iterations').value) || 5;

  const body = {
    type: 'hill_climb',
    skill_id: skillId,
    task_ids: taskIds.length ? taskIds : null,
    model,
    config: {
      max_iterations: iterations,
      strategy,
      beam_width: 3,
      improvement_threshold: 0.02,
      enable_thinking: false,
      judge_model: model,
    }
  };

  try {
    const job = await api('/jobs', { method: 'POST', body: JSON.stringify(body) });
    loadHillClimbJobs();
    watchHillClimb(job.id);
  } catch (e) { alert(e.message); }
}

async function loadHillClimbJobs() {
  const jobs = await api('/jobs?type=hill_climb');
  const tbody = document.getElementById('hc-jobs-table');
  if (!jobs.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No hill-climb jobs yet</td></tr>';
    return;
  }
  tbody.innerHTML = jobs.slice(0, 15).map(j => {
    const time = new Date(j.created_at + 'Z').toLocaleTimeString();
    return `<tr style="cursor:pointer" onclick="showIterations('${j.id}')">
      <td><code>${j.id.slice(0, 10)}</code></td>
      <td>${statusBadge(j.status)}</td>
      <td>${j.model}</td>
      <td>${time}</td>
    </tr>`;
  }).join('');
}

function watchHillClimb(jobId) {
  const log = document.getElementById('hc-log');
  log.innerHTML = '';
  log.style.display = 'block';

  const es = new EventSource(`${API}/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    const evt = data.event;
    const d = data.data || {};
    let line = '';

    if (evt === 'iteration_complete') {
      const icon = d.accepted ? '✓' : '✗';
      const color = d.accepted ? 'var(--green)' : 'var(--red)';
      line = `<span style="color:${color}">${icon} Iteration ${d.iteration}</span> avg=<span class="score">${(d.avg_score * 100).toFixed(1)}%</span> ${d.summary || ''}`;
    } else if (evt === 'task_scored') {
      line = `<span class="event">  scored ${d.task_id}</span> → <span class="score">${(d.score * 100).toFixed(1)}%</span>`;
    } else if (evt === 'job_completed') {
      line = '<span class="score">✓ Optimization complete</span>';
      es.close(); loadHillClimbJobs(); loadSkills();
    } else if (evt === 'job_failed') {
      line = `<span style="color:var(--red)">✗ Failed: ${d.error || ''}</span>`;
      es.close(); loadHillClimbJobs();
    } else if (evt === 'done') { es.close(); loadHillClimbJobs(); loadSkills(); return; }
    else return;

    log.innerHTML += `<div class="log-entry"><span class="time">${new Date().toLocaleTimeString()}</span> ${line}</div>`;
    log.scrollTop = log.scrollHeight;
  };
  es.onerror = () => { es.close(); loadHillClimbJobs(); };
}

async function showIterations(jobId) {
  const [job, iterations] = await Promise.all([
    api(`/jobs/${jobId}`),
    api(`/jobs/${jobId}/iterations`),
  ]);

  const panel = document.getElementById('hc-results');
  const summary = job.summary || {};

  let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
    <h3 style="font-size:16px">Optimization ${jobId.slice(0, 10)} ${statusBadge(job.status)}</h3>
    <div style="text-align:right;font-family:var(--mono)">
      ${summary.initial_avg !== undefined ? `<span style="color:var(--text2)">${(summary.initial_avg * 100).toFixed(1)}%</span> → ` : ''}
      <span style="color:var(--green);font-size:20px;font-weight:700">${summary.final_avg !== undefined ? (summary.final_avg * 100).toFixed(1) + '%' : '—'}</span>
      ${summary.improvement > 0 ? `<span style="color:var(--green);font-size:12px"> (+${(summary.improvement * 100).toFixed(1)})</span>` : ''}
    </div>
  </div>`;

  if (summary.new_skill_id) {
    html += `<div style="margin-bottom:16px;padding:8px 12px;background:rgba(74,222,128,0.1);border-radius:6px;font-size:13px">
      New skill created: <code>${summary.new_skill_id}</code></div>`;
  }

  for (const it of iterations) {
    const cls = it.accepted ? 'accepted' : it.iteration_number === 0 ? '' : 'rejected';
    html += `<div class="iteration-card ${cls}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <strong>Iteration ${it.iteration_number}</strong>
        <span style="font-family:var(--mono);font-weight:600">${(it.avg_score * 100).toFixed(1)}%</span>
      </div>`;

    if (it.change_summary) html += `<div style="font-size:13px;color:var(--text2);margin-bottom:8px">${escapeHtml(it.change_summary)}</div>`;

    // Per-task scores
    const taskScores = it.per_task_scores || {};
    for (const [tid, score] of Object.entries(taskScores)) {
      const pct = (score * 100).toFixed(0);
      const color = score >= 0.9 ? 'var(--green)' : score >= 0.5 ? 'var(--yellow)' : 'var(--red)';
      html += `<div style="display:flex;align-items:center;gap:8px;font-size:12px;padding:2px 0">
        <span style="min-width:140px">${tid}</span>
        <div class="score-bar" style="flex:1"><div class="score-bar-track"><div class="score-bar-fill" style="width:${pct}%;background:${color}"></div></div>
        <span class="score-bar-label" style="color:${color};font-size:11px">${pct}%</span></div></div>`;
    }

    // Skill content toggle
    if (it.skill_content && it.iteration_number > 0) {
      html += `<details style="margin-top:8px"><summary style="font-size:12px;color:var(--accent);cursor:pointer">View skill prompt</summary>
        <div class="skill-diff">${escapeHtml(it.skill_content)}</div></details>`;
    }

    html += '</div>';
  }

  panel.innerHTML = html;
  panel.style.display = 'block';
}

// --- Helpers ---
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Boot
document.addEventListener('DOMContentLoaded', init);
