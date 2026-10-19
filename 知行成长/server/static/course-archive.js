// 课程归档页面
(() => {
  'use strict';

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

  async function loadArchived() {
    const root = document.getElementById('archiveRoot');
    if (!root) return;
    root.replaceChildren();

    try {
      const data = await request('/api/copilot/lessons/archived', 'GET');
      const items = data.items || [];

      if (!items.length) {
        root.append(Object.assign(document.createElement('p'), {
          textContent: '暂无归档课程。完成课程并提交反馈后，可以将其归档。',
          className: 'desc'
        }));
        return;
      }

      const table = document.createElement('table');
      table.className = 'record-table';
      table.innerHTML = `<thead><tr>
        <th>课次</th><th>主题</th><th>完成时间</th><th>掌握程度</th><th>核心收获</th><th>操作</th>
      </tr></thead>`;
      const tbody = document.createElement('tbody');

      for (const item of items) {
        const tr = document.createElement('tr');
        const completedAt = item.completed_at ? new Date(item.completed_at).toLocaleDateString('zh-CN') : '-';
        const mastery = item.mastery_level ? (masteryLabels[item.mastery_level] || item.mastery_level) : '-';
        const learnings = item.key_learnings ? (item.key_learnings.length > 50 ? item.key_learnings.slice(0, 50) + '...' : item.key_learnings) : '-';

        tr.innerHTML = `
          <td>第${String(item.lesson_no).padStart(3, '0')}课</td>
          <td>-</td>
          <td>${completedAt}</td>
          <td>${mastery}</td>
          <td>${learnings}</td>
          <td>
            <button class="btn" data-action="feedback" data-no="${item.lesson_no}">查看反馈</button>
            <button class="btn" data-action="unarchive" data-no="${item.lesson_no}">取消归档</button>
          </td>
        `;
        tbody.append(tr);
      }
      table.append(tbody);
      root.append(table);

      // Bind buttons
      root.querySelectorAll('button[data-action="feedback"]').forEach(btn => {
        btn.onclick = () => { if (window.showCourseFeedback) window.showCourseFeedback(parseInt(btn.dataset.no)); };
      });
      root.querySelectorAll('button[data-action="unarchive"]').forEach(btn => {
        btn.onclick = async () => {
          const no = parseInt(btn.dataset.no);
          try {
            await request(`/api/copilot/lessons/${no}/unarchive`, 'POST', { key: crypto.randomUUID() });
            // Toast
            const toast = document.createElement('div');
            toast.className = 'toast';
            toast.textContent = '已取消归档';
            document.body.append(toast);
            setTimeout(() => toast.classList.add('show'), 10);
            setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
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
