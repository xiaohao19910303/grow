// 课程总结页面
(() => {
  'use strict';

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    .cp-summary-header h2 { margin: 0 0 8px; font-size: 24px; }
    .cp-summary-header .desc { margin: 0 0 20px; color: var(--muted, #666); font-size: 14px; }
    .cp-summary-stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .cp-summary-stats .stat-card {
      flex: 1; min-width: 120px; padding: 16px; background: var(--bg-soft, #f8f9fa);
      border: 1px solid var(--border, #e0e0e0); border-radius: 8px; text-align: center;
    }
    .cp-summary-stats .stat-value { display: block; font-size: 28px; font-weight: 600; color: var(--primary, #2563eb); }
    .cp-summary-stats .stat-label { display: block; font-size: 13px; color: var(--muted, #666); margin-top: 4px; }
    .cp-summary-actions { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
    .cp-summary-output {
      margin: 20px 0; padding: 20px; background: #fff; border: 2px solid var(--primary, #2563eb);
      border-radius: 12px; min-height: 200px; max-height: 600px; overflow-y: auto;
    }
    .cp-summary-streaming { white-space: pre-wrap; line-height: 1.7; font-size: 15px; }
    .cp-summary-result { white-space: pre-wrap; line-height: 1.7; font-size: 15px; }
    .cp-summary-error { color: #dc2626; padding: 12px; background: #fee2e2; border-radius: 8px; }
    .cp-summary-list { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .cp-summary-card {
      padding: 16px; background: #fff; border: 1px solid var(--border, #e0e0e0);
      border-radius: 8px; transition: box-shadow 0.2s;
    }
    .cp-summary-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    .cp-summary-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .cp-summary-scope {
      display: inline-block; padding: 2px 8px; background: var(--primary, #2563eb);
      color: #fff; border-radius: 4px; font-size: 12px; font-weight: 500;
    }
    .cp-summary-date { font-size: 13px; color: var(--muted, #666); }
    .cp-summary-preview { font-size: 14px; line-height: 1.6; color: #333; margin: 8px 0; max-height: 120px; overflow: hidden; }
  `;
  document.head.append(style);

  async function request(path, method, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json', 'x-copilot-request': '1' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json()).message || '请求失败');
    return r.json();
  }

  const masteryLabels = {
    fully_understood: '😎 完全掌握',
    basically_understood: '🙂 基本懂了',
    partially_understood: '😐 一知半解',
    not_understood: '😟 没学明白'
  };

  let currentSummaryContent = '';

  async function loadSummaryPage() {
    const root = document.getElementById('summaryRoot');
    if (!root) return;
    root.replaceChildren();

    // Header with stats
    const header = document.createElement('div');
    header.className = 'cp-summary-header';
    header.innerHTML = `
      <h2>课程总结</h2>
      <p class="desc">基于已完成课程和用户反馈，生成整门课程的复盘总结。</p>
      <div id="summaryStats" class="cp-summary-stats"></div>
    `;
    root.append(header);

    // Load stats
    try {
      const [lessons, feedback, summaries] = await Promise.all([
        request('/api/copilot/lessons?state=completed', 'GET'),
        request('/api/copilot/lessons/1/feedback', 'GET').catch(() => null),
        request('/api/copilot/summaries', 'GET')
      ]);
      const completedCount = (lessons.items || []).length;
      // Count feedback across all lessons
      let feedbackCount = 0;
      for (const lesson of (lessons.items || [])) {
        try {
          const fb = await request(`/api/copilot/lessons/${lesson.lesson_no}/feedback`, 'GET');
          if (fb && fb.mastery_level) feedbackCount++;
        } catch (e) { /* no feedback */ }
      }
      const statsEl = header.querySelector('#summaryStats');
      statsEl.innerHTML = `
        <div class="stat-card"><span class="stat-value">${completedCount}</span><span class="stat-label">已完成课程</span></div>
        <div class="stat-card"><span class="stat-value">${feedbackCount}</span><span class="stat-label">已提交反馈</span></div>
        <div class="stat-card"><span class="stat-value">${(summaries.items || []).length}</span><span class="stat-label">已有总结</span></div>
      `;
    } catch (e) {
      // Stats optional
    }

    // Generate button
    const actions = document.createElement('div');
    actions.className = 'cp-summary-actions';
    actions.innerHTML = `
      <button class="btn primary" id="btnGenerateSummary">生成整课总结</button>
    `;
    root.append(actions);

    // Streaming output area
    const output = document.createElement('div');
    output.id = 'summaryOutput';
    output.className = 'cp-summary-output';
    output.style.display = 'none';
    root.append(output);

    // After output: save + advanced buttons
    const postActions = document.createElement('div');
    postActions.id = 'summaryPostActions';
    postActions.className = 'cp-summary-actions';
    postActions.style.display = 'none';
    postActions.innerHTML = `
      <button class="btn primary" id="btnSaveSummary">保存总结</button>
      <button class="btn" id="btnGenerateAdvanced" style="display:none">基于总结生成进阶课程</button>
    `;
    root.append(postActions);

    // Previous summaries list
    const listHeader = document.createElement('h3');
    listHeader.textContent = '历史总结';
    listHeader.style.marginTop = '32px';
    root.append(listHeader);

    const list = document.createElement('div');
    list.id = 'summaryList';
    list.className = 'cp-summary-list';
    root.append(list);

    // Load existing summaries
    loadSummaryList();

    // Bind generate button
    document.getElementById('btnGenerateSummary').onclick = generateSummary;
  }

  async function loadSummaryList() {
    const list = document.getElementById('summaryList');
    if (!list) return;
    list.replaceChildren();

    try {
      const data = await request('/api/copilot/summaries', 'GET');
      const items = data.items || [];

      if (!items.length) {
        list.append(Object.assign(document.createElement('p'), {
          textContent: '暂无历史总结。点击上方按钮生成第一份总结。',
          className: 'desc'
        }));
        return;
      }

      for (const item of items) {
        const card = document.createElement('div');
        card.className = 'cp-summary-card';
        const createdAt = item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-';
        const preview = item.content ? (item.content.length > 200 ? item.content.slice(0, 200) + '...' : item.content) : '';
        card.innerHTML = `
          <div class="cp-summary-card-header">
            <span class="cp-summary-scope">${item.scope === 'full_course' ? '整课总结' : '单课总结'}</span>
            <span class="cp-summary-date">${createdAt}</span>
          </div>
          <div class="cp-summary-preview">${preview.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>
          <button class="btn" data-action="view" data-id="${item.id}">查看完整总结</button>
        `;
        list.append(card);
      }

      list.querySelectorAll('button[data-action="view"]').forEach(btn => {
        btn.onclick = () => viewSummary(parseInt(btn.dataset.id));
      });
    } catch (e) {
      list.append(Object.assign(document.createElement('p'), { textContent: '加载失败：' + e.message }));
    }
  }

  async function generateSummary() {
    const btn = document.getElementById('btnGenerateSummary');
    const output = document.getElementById('summaryOutput');
    const postActions = document.getElementById('summaryPostActions');

    btn.disabled = true;
    btn.textContent = '生成中...';
    output.style.display = '';
    output.innerHTML = '<div class="cp-summary-streaming">正在生成总结...</div>';
    postActions.style.display = 'none';
    currentSummaryContent = '';

    try {
      const response = await fetch('/api/copilot/summaries/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-copilot-request': '1' },
        body: JSON.stringify({ module: 'renzhi', scope: 'full_course', key: crypto.randomUUID() })
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '生成失败');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      output.innerHTML = '<div class="cp-summary-streaming" id="streamingContent"></div>';
      const streamingEl = document.getElementById('streamingContent');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE
        const lines = buffer.split('\n');
        buffer = lines.pop(); // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.text) {
                currentSummaryContent += data.text;
                streamingEl.textContent = currentSummaryContent;
              }
              if (data.content) {
                currentSummaryContent = data.content;
                streamingEl.textContent = currentSummaryContent;
              }
              if (data.error) {
                throw new Error(data.error);
              }
            } catch (e) {
              if (e.message !== '生成失败') console.error('SSE parse error:', e);
            }
          }
        }
      }

      // Generation complete
      output.innerHTML = `<div class="cp-summary-result">${currentSummaryContent.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>`;
      postActions.style.display = '';
      document.getElementById('btnSaveSummary').onclick = saveSummary;
      document.getElementById('btnGenerateAdvanced').onclick = generateAdvanced;

    } catch (e) {
      output.innerHTML = `<div class="cp-summary-error">生成失败：${e.message}</div>`;
    } finally {
      btn.disabled = false;
      btn.textContent = '生成整课总结';
    }
  }

  async function saveSummary() {
    if (!currentSummaryContent) return;
    const btn = document.getElementById('btnSaveSummary');
    btn.disabled = true;
    btn.textContent = '保存中...';

    try {
      // The summary is already saved by the backend after generation completes
      // Just refresh the list
      await loadSummaryList();
      document.getElementById('summaryPostActions').style.display = 'none';
      document.getElementById('btnGenerateAdvanced').style.display = '';
      // Toast
      showToast('总结已保存');
    } catch (e) {
      alert('保存失败：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = '保存总结';
    }
  }

  async function viewSummary(summaryId) {
    try {
      const data = await request(`/api/copilot/summaries/${summaryId}`, 'GET');
      const output = document.getElementById('summaryOutput');
      output.style.display = '';
      output.innerHTML = `<div class="cp-summary-result">${data.content.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>`;
      currentSummaryContent = data.content;
      document.getElementById('summaryPostActions').style.display = '';
      document.getElementById('btnGenerateAdvanced').style.display = '';
    } catch (e) {
      alert('加载失败：' + e.message);
    }
  }

  async function generateAdvanced() {
    if (!currentSummaryContent) return;
    const btn = document.getElementById('btnGenerateAdvanced');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '生成中...';

    try {
      const response = await fetch('/api/copilot/summaries/generate-advanced', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-copilot-request': '1' },
        body: JSON.stringify({
          module: 'renzhi',
          key: crypto.randomUUID(),
          summary_content: currentSummaryContent
        })
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '生成失败');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let advancedContent = '';
      let draftId = null;

      // Show output area
      const output = document.getElementById('summaryOutput');
      output.style.display = '';
      output.innerHTML = '<div class="cp-summary-streaming" id="advancedStreaming">正在生成进阶课程...</div>';
      const streamingEl = document.getElementById('advancedStreaming');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.text) {
                advancedContent += data.text;
                streamingEl.textContent = advancedContent;
              }
              if (data.content) {
                advancedContent = data.content;
                streamingEl.textContent = advancedContent;
                if (data.draft_id) draftId = data.draft_id;
              }
              if (data.error) {
                throw new Error(data.error);
              }
            } catch (e) {
              if (e.message !== '生成失败') console.error('SSE parse error:', e);
            }
          }
        }
      }

      // Done
      showToast('进阶课程已生成为草稿，请在"课程管理"页面查看和编辑');
      document.getElementById('summaryPostActions').style.display = 'none';

    } catch (e) {
      showToast('生成失败：' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }

  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.append(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
  }

  // Auto-load when tab is shown
  const observer = new MutationObserver(() => {
    const view = document.getElementById('view-summary');
    if (view && view.style.display !== 'none' && !view.dataset.loaded) {
      view.dataset.loaded = '1';
      loadSummaryPage();
    }
    if (view && view.style.display === 'none') {
      delete view.dataset.loaded;
    }
  });

  if (document.getElementById('view-summary')) {
    observer.observe(document.getElementById('view-summary'), { attributes: true, attributeFilter: ['style'] });
  }

  window.loadSummaryPage = loadSummaryPage;
})();
