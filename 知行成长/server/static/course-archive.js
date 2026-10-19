// 课程归档页面
(() => {
  'use strict';

  // 注入样式
  const style = document.createElement('style');
  style.textContent = `
    .archive-header {
      margin-bottom: 24px;
    }
    .archive-header h2 {
      margin: 0 0 8px; font-size: 24px;
    }
    .archive-header .desc {
      margin: 0; color: var(--muted, #666); font-size: 14px;
    }
    .archive-stats {
      display: flex; gap: 16px; margin: 20px 0; flex-wrap: wrap;
    }
    .archive-stat {
      padding: 16px 24px; background: var(--bg-soft, #f8f9fa);
      border: 1px solid var(--border, #e0e0e0); border-radius: 10px;
      display: flex; align-items: center; gap: 12px;
    }
    .archive-stat-icon {
      font-size: 28px;
    }
    .archive-stat-value {
      font-size: 24px; font-weight: 600; color: var(--primary, #2563eb);
    }
    .archive-stat-label {
      font-size: 13px; color: var(--muted, #666);
    }
    .archive-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 20px; margin-top: 24px;
    }
    .archive-card {
      background: white; border: 1px solid var(--border, #e0e0e0);
      border-radius: 12px; padding: 20px; transition: all 0.2s;
      display: flex; flex-direction: column;
    }
    .archive-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
      border-color: var(--primary, #2563eb);
    }
    .archive-card-header {
      display: flex; justify-content: space-between; align-items: flex-start;
      margin-bottom: 16px; padding-bottom: 12px;
      border-bottom: 1px solid var(--border, #e0e0e0);
    }
    .archive-card-no {
      font-size: 18px; font-weight: 600; color: var(--primary, #2563eb);
    }
    .archive-card-date {
      font-size: 13px; color: var(--muted, #666);
    }
    .archive-mastery {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 12px; border-radius: 8px;
      font-size: 14px; font-weight: 500;
      background: var(--primary-soft, #e0e7ff);
      color: var(--primary, #2563eb);
      margin-bottom: 12px;
    }
    .archive-learnings {
      flex: 1; margin-bottom: 16px;
    }
    .archive-learnings-label {
      font-size: 13px; color: var(--muted, #666);
      margin-bottom: 6px; display: block;
    }
    .archive-learnings-text {
      font-size: 14px; line-height: 1.6; color: var(--text, #333);
      max-height: 80px; overflow: hidden;
      position: relative;
    }
    .archive-learnings-text::after {
      content: ''; position: absolute; bottom: 0; left: 0; right: 0;
      height: 30px; background: linear-gradient(transparent, white);
    }
    .archive-card-actions {
      display: flex; gap: 8px; margin-top: auto;
    }
    .archive-card-actions button {
      flex: 1; padding: 8px 12px; font-size: 13px;
      border-radius: 6px; cursor: pointer; transition: all 0.2s;
      border: 1px solid var(--border, #e0e0e0);
      background: var(--bg-soft, #f8f9fa);
    }
    .archive-card-actions button:hover {
      background: var(--primary, #2563eb); color: white;
      border-color: var(--primary, #2563eb);
    }
    .archive-empty {
      text-align: center; padding: 80px 20px;
      color: var(--muted, #666);
    }
    .archive-empty-icon {
      font-size: 72px; margin-bottom: 20px; opacity: 0.3;
    }
    .archive-empty-text {
      font-size: 16px; line-height: 1.6;
    }
    .archive-toast {
      position: fixed; bottom: 20px; left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: #333; color: white; padding: 12px 24px;
      border-radius: 8px; font-size: 14px; z-index: 10000;
      transition: transform 0.3s ease;
    }
    .archive-toast.show {
      transform: translateX(-50%) translateY(0);
    }
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

  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'archive-toast';
    toast.textContent = message;
    document.body.append(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
  }

  async function loadArchived() {
    const root = document.getElementById('archiveRoot');
    if (!root) return;
    root.replaceChildren();

    try {
      const data = await request('/api/copilot/lessons/archived', 'GET');
      const items = data.items || [];

      // Header
      const header = document.createElement('div');
      header.className = 'archive-header';
      header.innerHTML = `
        <h2>课程归档</h2>
        <p class="desc">已完成并归档的课程，可随时查阅复习。</p>
      `;
      root.append(header);

      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'archive-empty';
        empty.innerHTML = `
          <div class="archive-empty-icon">📚</div>
          <div class="archive-empty-text">
            暂无归档课程<br>
            完成课程并提交反馈后，可以将其归档
          </div>
        `;
        root.append(empty);
        return;
      }

      // Stats
      const stats = document.createElement('div');
      stats.className = 'archive-stats';
      const masteredCount = items.filter(i => i.mastery_level === 'fully_understood').length;
      const withFeedback = items.filter(i => i.key_learnings).length;
      stats.innerHTML = `
        <div class="archive-stat">
          <div class="archive-stat-icon">📚</div>
          <div>
            <div class="archive-stat-value">${items.length}</div>
            <div class="archive-stat-label">归档课程</div>
          </div>
        </div>
        <div class="archive-stat">
          <div class="archive-stat-icon">😎</div>
          <div>
            <div class="archive-stat-value">${masteredCount}</div>
            <div class="archive-stat-label">完全掌握</div>
          </div>
        </div>
        <div class="archive-stat">
          <div class="archive-stat-icon">💬</div>
          <div>
            <div class="archive-stat-value">${withFeedback}</div>
            <div class="archive-stat-label">有反馈</div>
          </div>
        </div>
      `;
      root.append(stats);

      // Cards grid
      const grid = document.createElement('div');
      grid.className = 'archive-grid';

      for (const item of items) {
        const card = document.createElement('div');
        card.className = 'archive-card';
        const completedAt = item.completed_at ? new Date(item.completed_at).toLocaleDateString('zh-CN') : '-';
        const mastery = item.mastery_level ? (masteryLabels[item.mastery_level] || item.mastery_level) : '未评估';
        const learnings = item.key_learnings || '暂无核心收获记录';

        card.innerHTML = `
          <div class="archive-card-header">
            <div class="archive-card-no">第${String(item.lesson_no).padStart(3, '0')}课</div>
            <div class="archive-card-date">${completedAt}</div>
          </div>
          <div class="archive-mastery">${mastery}</div>
          <div class="archive-learnings">
            <span class="archive-learnings-label">💡 核心收获</span>
            <div class="archive-learnings-text">${learnings.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>
          </div>
          <div class="archive-card-actions">
            <button data-action="feedback" data-no="${item.lesson_no}">📝 查看反馈</button>
            <button data-action="unarchive" data-no="${item.lesson_no}">↩️ 取消归档</button>
          </div>
        `;
        grid.append(card);
      }

      root.append(grid);

      // Bind buttons
      root.querySelectorAll('button[data-action="feedback"]').forEach(btn => {
        btn.onclick = () => { if (window.showCourseFeedback) window.showCourseFeedback(parseInt(btn.dataset.no)); };
      });
      root.querySelectorAll('button[data-action="unarchive"]').forEach(btn => {
        btn.onclick = async () => {
          const no = parseInt(btn.dataset.no);
          try {
            await request(`/api/copilot/lessons/${no}/unarchive`, 'POST', { key: crypto.randomUUID() });
            showToast('已取消归档');
            loadArchived();
          } catch (e) { alert('操作失败：' + e.message); }
        };
      });
    } catch (e) {
      root.append(Object.assign(document.createElement('p'), { textContent: '加载失败：' + e.message }));
    }
  }

  // Auto-load when tab is shown
  const observer = new MutationObserver(() => {
    const view = document.getElementById('view-archive');
    if (view && view.style.display !== 'none' && !view.dataset.loaded) {
      view.dataset.loaded = '1';
      loadArchived();
    }
    if (view && view.style.display === 'none') {
      delete view.dataset.loaded;
    }
  });

  if (document.getElementById('view-archive')) {
    observer.observe(document.getElementById('view-archive'), { attributes: true, attributeFilter: ['style'] });
  }

  window.loadArchivedLessons = loadArchived;
})();
