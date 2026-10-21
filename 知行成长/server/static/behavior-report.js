/* Explicit browser-configured report generation, shared with the task center. */
(() => {
  'use strict';
  let current = null;
  const controllers = new Map(), panels = new Map();
  const active = job => job?.state === 'running';
  const period = job => Number(job?.ref) || 30;
  const fallback = {
    cancelled: '生成已取消。可在报告历史核对已有结果，或主动重新生成。',
    interrupted: '原连接已中断。请先核对报告历史；需要时可主动重新生成。',
    failed: '报告生成失败，请检查 AI 配置后重试。',
    ready: '报告已生成，可在报告历史查看。',
  };
  function action(panel, text, run) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn'; button.textContent = text;
    button.onclick = run; panel.append(button); return button;
  }
  function display(job, message, needsSettings = false) {
    const buttons = document.querySelectorAll('[onclick^="generateNewReport"]');
    for (const button of buttons) {
      button.disabled = active(current);
      button.textContent = active(current) ? '正在生成…' : '生成新报告';
      if (!panels.has(button)) {
        const panel = document.createElement('div');
        panel.className = 'reading-task-notice'; panel.setAttribute('role', 'status');
        panel.setAttribute('aria-live', 'polite'); button.parentNode.insertBefore(panel, button.nextSibling);
        panels.set(button, panel);
      }
      const panel = panels.get(button); panel.replaceChildren();
      const text = document.createElement('p');
      text.textContent = message || job?.error || (active(job) ? `正在分析最近 ${period(job)} 天的数据，可切换页面或取消。` : fallback[job?.state]) || '';
      panel.append(text);
      if (active(job)) action(panel, '取消生成', () => cancel(job));
      if (needsSettings || job?.state === 'failed') action(panel, '前往设置', () => window.goTab('settings'));
      if (job && ['failed', 'cancelled', 'interrupted'].includes(job.state)) {
        action(panel, '重新生成', () => generateNewReport(button, period(job)));
      }
    }
  }
  function track(job) { window.GenerationTasks?.track(job); if (job === current) display(job); }
  async function cancel(job) {
    if (current?.id !== job.id || !active(current)) return current?.id === job.id ? current : {...job, state: 'interrupted', error: fallback.interrupted};
    current.state = 'cancelled';
    controllers.get(job.id)?.abort(); track(current);
    return current;
  }
  async function generateNewReport(button, periodDays = 30) {
    if (active(current)) { display(current); return; }
    let config;
    try { config = window.AIConfig.require(); }
    catch (error) { display(null, error.message, true); return; }
    const job = {id: 'behavior-report:' + crypto.randomUUID(), source: 'behavior-report', ref: String(periodDays),
      kind: 'behavior-report', state: 'running', label: '行为分析报告生成', title: `最近 ${periodDays} 天行为分析`};
    current = job;
    const controller = new AbortController(); controllers.set(job.id, controller); track(job);
    try {
      const response = await fetch('/api/behavior-report/generate?period_days=' + periodDays, {
        method: 'POST', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'},
        body: JSON.stringify({ai_config: config}),
      });
      const report = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(report.message || report.detail || '报告生成失败，请稍后重试。');
      if (!report.id || typeof report.content !== 'string' || !report.content.trim()) throw new Error('未收到完整报告，请核对历史后重试。');
      if (job.state === 'cancelled') return;
      Object.assign(job, {state: 'ready', result_id: report.id}); track(job);
      window.toast?.('报告已生成');
      window.renderAIReportLatest?.(); window.renderAIReports?.();
    } catch (error) {
      if (job.state !== 'cancelled') {
        Object.assign(job, {state: error.name === 'AbortError' ? 'cancelled' : 'failed', error: error.name === 'AbortError' ? '' : error.message});
        track(job);
      }
    } finally {
      controllers.delete(job.id);
      if (current === job) display(job);
    }
  }
  window.generateNewReport = generateNewReport;
  window.GenerationTasks?.register('behavior-report', {
    read: async job => current?.id === job.id ? current : {...job, state: 'interrupted', error: fallback.interrupted},
    cancel,
    open: async job => {
      if (window.goTab('ai-report') === false) return false;
      if (job.result_id) return window.viewAIReport(job.result_id);
      display(job);
    },
  });
})();
