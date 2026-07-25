/** Dashboard application logic. */
(function () {
  const STAGES = [
    { key: 'supervisor', label: 'Supervisor', icon: 'compass' },
    { key: 'research', label: 'Research', icon: 'search' },
    { key: 'analyst', label: 'Analyst', icon: 'bar-chart-3' },
    { key: 'critic', label: 'Critic', icon: 'shield-check' },
    { key: 'writer', label: 'Writer', icon: 'file-text' },
  ];

  let selectedRunId = null;
  let monitorPollHandle = null;

  // -------------------------------------------------------------------
  // Navigation
  // -------------------------------------------------------------------
  function initNav() {
    document.querySelectorAll('.sidebar-item[data-page]').forEach((item) => {
      item.addEventListener('click', () => showPage(item.dataset.page));
    });
    document.getElementById('collapseBtn').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('collapsed');
    });
  }

  function showPage(pageKey) {
    document.querySelectorAll('.sidebar-item[data-page]').forEach((i) => i.classList.toggle('active', i.dataset.page === pageKey));
    document.querySelectorAll('.page').forEach((p) => p.classList.remove('active'));
    const target = document.getElementById(`page-${pageKey}`);
    if (target) target.classList.add('active');
    if (pageKey === 'overview') refreshOverview();
    if (pageKey === 'runs') refreshAllRuns();
  }

  // -------------------------------------------------------------------
  // Toasts
  // -------------------------------------------------------------------
  function toast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast glass toast-${type}`;
    const icons = { success: 'check-circle', warning: 'alert-triangle', danger: 'x-circle', info: 'info' };
    el.innerHTML = `<i data-lucide="${icons[type] || 'info'}" style="width:16px;height:16px"></i><span>${message}</span>`;
    container.appendChild(el);
    window.lucide && lucide.createIcons();
    setTimeout(() => {
      el.style.transition = 'opacity 300ms ease, transform 300ms ease';
      el.style.opacity = '0';
      el.style.transform = 'translateX(20px)';
      setTimeout(() => el.remove(), 320);
    }, 3800);
  }

  // -------------------------------------------------------------------
  // Overview: stats + workflow graph preview + recent runs
  // -------------------------------------------------------------------
  function statusBadge(status) {
    const map = {
      queued: ['badge-muted', 'queued'],
      running: ['badge-info', 'running'],
      awaiting_clarification: ['badge-warning', 'needs input'],
      completed: ['badge-success', 'completed'],
      failed: ['badge-danger', 'failed'],
    };
    const [cls, label] = map[status] || ['badge-muted', status];
    return `<span class="badge ${cls}"><span class="badge-dot"></span>${label}</span>`;
  }

  function renderWorkflowGraph(containerId, currentStage, status) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
    container.innerHTML = STAGES.map((stage, idx) => {
      let nodeStatus = 'idle';
      if (status === 'failed' && idx === currentIdx) nodeStatus = 'failed';
      else if (idx < currentIdx || (status === 'completed')) nodeStatus = 'completed';
      else if (idx === currentIdx && status === 'running') nodeStatus = 'running';
      else if (idx === currentIdx) nodeStatus = 'waiting';

      const node = `
        <div class="wf-node animate-in" data-status="${nodeStatus}">
          <div class="wf-icon"><i data-lucide="${stage.icon}" style="width:18px;height:18px"></i></div>
          <div class="wf-label">${stage.label}</div>
          <div class="wf-status">${nodeStatus}</div>
        </div>`;
      if (idx === STAGES.length - 1) return node;
      const flowing = nodeStatus === 'completed' || (idx === currentIdx && status === 'running');
      return node + `<div class="wf-connector ${flowing ? 'flowing' : ''}"></div>`;
    }).join('');
    window.lucide && lucide.createIcons();
  }

  function renderStatsGrid(stats) {
    const items = [
      { icon: 'workflow', label: 'Total Workflows', value: stats.total_workflows },
      { icon: 'cpu', label: 'Active Agents', value: stats.active_agents },
      { icon: 'loader', label: 'Running Tasks', value: stats.running_tasks },
      { icon: 'database', label: 'Evidence Collected', value: stats.evidence_count },
      { icon: 'file-text', label: 'Reports Generated', value: stats.reports_generated },
      { icon: 'check-circle-2', label: 'Success Rate', value: `${stats.success_rate}%` },
      { icon: 'timer', label: 'Avg Workflow Time', value: `${stats.avg_workflow_seconds}s` },
    ];
    document.getElementById('statsGrid').innerHTML = items.map((item) => `
      <div class="widget-card glass glass-glow animate-in">
        <div class="widget-top">
          <div class="widget-icon"><i data-lucide="${item.icon}" style="width:16px;height:16px"></i></div>
        </div>
        <div class="widget-value">${item.value}</div>
        <div class="widget-label">${item.label}</div>
      </div>
    `).join('');
    window.lucide && lucide.createIcons();
  }

  function renderRunsTable(tbodySelector, runs, { limit } = {}) {
    const rows = limit ? runs.slice(0, limit) : runs;
    const tbody = document.querySelector(tbodySelector);
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">No workflow runs yet. Start one from "New Research".</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-run-id="${r.id}">
        <td>${escapeHtml(r.objective)}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="text-secondary">${r.current_stage}</td>
        <td class="text-secondary">${r.revision_count}</td>
        <td class="text-tertiary">${new Date(r.created_at).toLocaleString()}</td>
      </tr>
    `).join('');
    tbody.querySelectorAll('tr[data-run-id]').forEach((row) => {
      row.addEventListener('click', () => {
        selectedRunId = row.dataset.runId;
        showPage('monitor');
        startMonitorPolling();
      });
    });
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  async function refreshOverview() {
    try {
      const [stats, runs] = await Promise.all([API.stats(), API.listWorkflows()]);
      renderStatsGrid(stats);
      const latest = runs[0];
      renderWorkflowGraph('workflowGraph', latest ? latest.current_stage : 'supervisor', latest ? latest.status : 'idle');
      renderRunsTable('#recentRunsTable tbody', runs, { limit: 6 });
    } catch (err) {
      console.error(err);
    }
  }

  async function refreshAllRuns() {
    try {
      const runs = await API.listWorkflows();
      renderRunsTable('#allRunsTable tbody', runs);
    } catch (err) {
      console.error(err);
    }
  }

  // -------------------------------------------------------------------
  // New run form
  // -------------------------------------------------------------------
  function initNewRunForm() {
    const textarea = document.getElementById('objectiveInput');
    const charCount = document.getElementById('charCount');
    const label = document.getElementById('objectiveLabel');

    textarea.addEventListener('input', () => {
      charCount.textContent = textarea.value.length;
      label.style.opacity = textarea.value ? '0' : '1';
    });

    document.getElementById('clearObjectiveBtn').addEventListener('click', () => {
      textarea.value = '';
      charCount.textContent = '0';
    });

    document.getElementById('submitObjectiveBtn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const objective = textarea.value.trim();
      if (objective.length < 5) {
        toast('Please describe your research objective in a bit more detail.', 'warning');
        return;
      }
      btn.classList.add('btn-loading');
      try {
        const run = await API.createWorkflow(objective);
        toast('Workflow launched — watch it live in the Monitor tab.', 'success');
        textarea.value = '';
        charCount.textContent = '0';
        selectedRunId = run.id;
        showPage('monitor');
        startMonitorPolling();
      } catch (err) {
        console.error(err);
        toast('Failed to launch workflow. Check the backend logs.', 'danger');
      } finally {
        btn.classList.remove('btn-loading');
      }
    });
  }

  // -------------------------------------------------------------------
  // Live monitor
  // -------------------------------------------------------------------
  const AGENT_META = {
    supervisor: { icon: 'compass', color: 'var(--color-primary)' },
    research: { icon: 'search', color: 'var(--color-accent)' },
    analyst: { icon: 'bar-chart-3', color: 'var(--color-success)' },
    critic: { icon: 'shield-check', color: 'var(--color-warning)' },
    writer: { icon: 'file-text', color: 'var(--color-danger)' },
  };

  function renderAgentGrid(detail) {
    const currentStage = detail.run.current_stage;
    const status = detail.run.status;
    const grid = document.getElementById('agentGrid');
    grid.innerHTML = Object.entries(AGENT_META).map(([key, meta]) => {
      const idx = STAGES.findIndex((s) => s.key === key);
      const currentIdx = STAGES.findIndex((s) => s.key === currentStage);
      let state = 'idle';
      if (status === 'completed' || idx < currentIdx) state = 'completed';
      else if (idx === currentIdx && status === 'running') state = 'running';
      else if (idx === currentIdx && status === 'failed') state = 'failed';
      else if (idx === currentIdx) state = 'waiting';

      const lastLog = [...detail.logs].reverse().find((l) => l.agent === key);
      const taskText = lastLog ? lastLog.detail || lastLog.event : 'Idle';

      return `
        <div class="agent-card glass animate-in">
          <div class="agent-head">
            <div class="agent-avatar ${state === 'running' ? 'running' : ''}" style="color:${meta.color}">
              <i data-lucide="${meta.icon}" style="width:18px;height:18px"></i>
            </div>
            <div>
              <div class="agent-name">${key.charAt(0).toUpperCase() + key.slice(1)}</div>
              <div class="agent-role">${state}</div>
            </div>
          </div>
          <div class="agent-body">
            <div class="agent-row"><span>Current task</span><span class="text-tertiary" style="max-width:130px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(taskText)}</span></div>
            <div class="agent-row"><span>Status</span>${statusBadge(state === 'idle' ? 'queued' : state === 'waiting' ? 'queued' : state)}</div>
          </div>
        </div>`;
    }).join('');
    window.lucide && lucide.createIcons();
  }

  function renderTimeline(logs) {
    const list = document.getElementById('timelineList');
    if (!logs.length) {
      list.innerHTML = `<div class="empty-state">No events yet.</div>`;
      return;
    }
    list.innerHTML = [...logs].reverse().map((log) => `
      <div class="timeline-item animate-in">
        <div style="flex:1;">
          <div class="timeline-agent">${log.agent}</div>
          <div class="timeline-event">${log.event.replace(/_/g, ' ')}</div>
          ${log.detail ? `<div class="timeline-detail">${escapeHtml(log.detail)}</div>` : ''}
        </div>
        <div class="timeline-time">${new Date(log.created_at).toLocaleTimeString()}</div>
      </div>
    `).join('');
  }

  function renderClarificationCard(detail) {
    const container = document.getElementById('clarificationContainer');
    if (detail.run.status !== 'awaiting_clarification') {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `
      <div class="glass clarification-card animate-in">
        <div class="clarification-label"><i data-lucide="help-circle" style="width:14px;height:14px"></i>Clarification needed</div>
        <div class="clarification-question">${escapeHtml(detail.run.clarification_question || 'The Supervisor needs more detail before planning research.')}</div>
        <textarea id="clarificationInput" placeholder="Type your answer..."></textarea>
        <button class="btn btn-primary" id="submitClarificationBtn">
          <i data-lucide="send" style="width:14px;height:14px"></i>
          <span class="btn-label">Submit &amp; Resume</span>
        </button>
      </div>`;
    window.lucide && lucide.createIcons();

    document.getElementById('submitClarificationBtn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      const input = document.getElementById('clarificationInput');
      const answer = input.value.trim();
      if (!answer) {
        toast('Please type an answer before submitting.', 'warning');
        return;
      }
      btn.classList.add('btn-loading');
      try {
        await API.submitClarification(detail.run.id, answer);
        toast('Clarification submitted — resuming workflow.', 'success');
        container.innerHTML = '';
        startMonitorPolling();
      } catch (err) {
        console.error(err);
        toast('Failed to submit clarification.', 'danger');
      } finally {
        btn.classList.remove('btn-loading');
      }
    });
  }

  async function pollMonitor() {
    if (!selectedRunId) return;
    try {
      const detail = await API.getWorkflow(selectedRunId);
      document.getElementById('monitorTitle').textContent = detail.run.objective;
      document.getElementById('monitorSubtitle').textContent = `Run ID: ${detail.run.id}`;
      document.getElementById('monitorStatusBadge').outerHTML = statusBadge(detail.run.status).replace('badge', 'badge').replace('<span class="badge', '<span id="monitorStatusBadge" class="badge');
      renderWorkflowGraph('monitorWorkflowGraph', detail.run.current_stage, detail.run.status);
      renderAgentGrid(detail);
      renderTimeline(detail.logs);
      renderClarificationCard(detail);

      if (detail.reports.length) {
        loadReportIntoViewer(detail);
      }

      if (detail.run.status === 'awaiting_clarification') {
        stopMonitorPolling();
        toast('The Supervisor needs clarification to proceed.', 'warning');
      } else if (detail.run.status === 'completed' || detail.run.status === 'failed') {
        stopMonitorPolling();
        if (detail.run.status === 'completed') {
          toast('Workflow completed — report is ready.', 'success');
        } else {
          toast('Workflow failed. See timeline for details.', 'danger');
        }
      }
    } catch (err) {
      console.error(err);
    }
  }

  function startMonitorPolling() {
    stopMonitorPolling();
    pollMonitor();
    monitorPollHandle = setInterval(pollMonitor, 1500);
  }

  function stopMonitorPolling() {
    if (monitorPollHandle) clearInterval(monitorPollHandle);
    monitorPollHandle = null;
  }

  // -------------------------------------------------------------------
  // Report viewer
  // -------------------------------------------------------------------
  function loadReportIntoViewer(detail) {
    const latest = [...detail.reports].sort((a, b) => b.version - a.version)[0];
    const bodyEl = document.getElementById('reportBody');
    const html = window.marked ? marked.parse(latest.content_markdown) : `<pre>${escapeHtml(latest.content_markdown)}</pre>`;
    bodyEl.innerHTML = html;

    // Build TOC from h2 headings
    const toc = document.getElementById('reportToc');
    const headings = bodyEl.querySelectorAll('h2');
    toc.innerHTML = '<strong style="font-size:12px;color:var(--text-tertiary);">ON THIS PAGE</strong>' +
      Array.from(headings).map((h, i) => {
        const id = `section-${i}`;
        h.id = id;
        return `<a href="#${id}">${h.textContent}</a>`;
      }).join('');

    document.getElementById('downloadReportBtn').href = API.reportDownloadUrl(detail.run.id);
    document.getElementById('copyReportBtn').onclick = async () => {
      try {
        await navigator.clipboard.writeText(latest.content_markdown);
        toast('Report markdown copied to clipboard.', 'success');
      } catch {
        toast('Could not copy to clipboard.', 'warning');
      }
    };
  }

  // -------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    initNav();
    initNewRunForm();
    refreshOverview();
    window.lucide && lucide.createIcons();
    setInterval(() => { if (document.getElementById('page-overview').classList.contains('active')) refreshOverview(); }, 6000);
  });
  window.addEventListener('load', () => window.lucide && lucide.createIcons());
})();
