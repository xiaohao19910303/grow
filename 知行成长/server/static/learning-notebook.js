/* Find saved course notes without requiring a course completion. */
(() => {
  'use strict';
  const root = document.getElementById('view-learning-notes');
  if (!root) return;
  let page = 1, query = '', kind = '', request = 0, controller, active = false;
  const pageSize = 20;
  const node = (tag, text, className) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  };
  const panel = node('section', undefined, 'section learning-notebook');
  panel.append(node('h2', '学习笔记'), node('p', '查看已保存到当前账号的笔记与练习答案。保存笔记不代表学完；仅在本机尚未同步的内容，请回原课程恢复。', 'desc'));
  const form = node('form', undefined, 'notebook-filters');
  const searchLabel = node('label', '搜索笔记与答案');
  const search = node('input'); search.type = 'search'; search.maxLength = 500;
  search.placeholder = '输入记得的笔记或答案'; searchLabel.append(search);
  const kindLabel = node('label', '学习模块');
  const select = node('select');
  for (const [value, label] of [['', '全部模块'], ['yingyu', '英文阅读'], ['biaoda', '结构化表达'], ['renzhi', '认知课程'], ['plan', '课程规划']]) {
    const option = node('option', label); option.value = value; select.append(option);
  }
  kindLabel.append(select);
  const submit = node('button', '搜索', 'btn primary'); submit.type = 'submit';
  const refresh = node('button', '刷新笔记', 'btn'); refresh.type = 'button';
  form.append(searchLabel, kindLabel, submit, refresh);
  const status = node('p', '', 'desc'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const results = node('div', undefined, 'notebook-results');
  const pagination = node('nav', undefined, 'cp-actions'); pagination.setAttribute('aria-label', '学习笔记分页');
  panel.append(form, status, results, pagination); root.append(panel);

  async function load() {
    const turn = ++request;
    controller?.abort(); controller = new AbortController();
    results.replaceChildren(); pagination.replaceChildren(); status.textContent = '正在读取学习笔记…';
    const loading = window.LoadingState?.start(results, '正在读取学习笔记…', '正在查找已保存的笔记和练习答案。');
    try {
      await window.Account?.ready;
      const owner = window.Account?.user?.id;
      if (!active || turn !== request) return;
      const params = new URLSearchParams({q: query, page, page_size: pageSize});
      if (kind) params.set('kind', kind);
      const response = await fetch('/api/study-notes?' + params, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw Error('笔记暂时无法读取，请重试。');
      const data = await response.json();
      if (!active || turn !== request || owner !== window.Account?.user?.id) return;
      if (!data.items.length && page > 1 && data.total > 0) { page = Math.ceil(data.total / pageSize); return load(); }
      results.replaceChildren();
      status.textContent = `找到 ${data.total} 篇有笔记或作答的课程`;
      if (!data.items.length) {
        results.append(node('p', query || kind ? '没有找到匹配的笔记，可调整关键词或模块。' : '还没有已保存的学习笔记。打开课程写下笔记或答案后，即可在这里找回。', 'desc'));
        const courses = node('button', '进入我的课程', 'btn'); courses.type = 'button'; courses.onclick = () => goTab('library'); results.append(courses);
      }
      for (const item of data.items) {
        const card = node('article', undefined, 'notebook-card');
        const title = node('h3'); const open = node('button', item.title, 'btn notebook-open'); open.type = 'button';
        open.onclick = () => window.RecordDiscovery.open(item); title.append(open);
        const date = new Date(item.updated_at);
        card.append(title, node('p', `${item.module_label} · ${Number(item.answer_count)} 项作答 · ${Number.isNaN(date.getTime()) ? '更新时间未知' : date.toLocaleString('zh-CN')}`, 'desc'), node('p', item.preview, 'notebook-preview'));
        results.append(card);
      }
      const pages = Math.max(1, Math.ceil(data.total / pageSize));
      for (const [label, offset] of [['上一页', -1], ['下一页', 1]]) {
        const button = node('button', label, 'btn'); button.type = 'button';
        button.disabled = offset < 0 ? page <= 1 : page >= pages;
        button.onclick = () => { page += offset; load(); }; pagination.append(button);
        if (offset < 0) pagination.append(node('span', `第 ${page} / ${pages} 页`));
      }
    } catch (error) {
      if (error.name === 'AbortError' || turn !== request || !active) return;
      results.replaceChildren(); status.textContent = '笔记暂时无法读取，已保存内容不会因此删除。';
      const retry = node('button', '重试读取笔记', 'btn'); retry.type = 'button'; retry.onclick = load; results.append(retry);
    } finally { loading?.finish(); }
  }
  form.onsubmit = event => { event.preventDefault(); query = search.value.trim(); kind = select.value; page = 1; load(); };
  select.onchange = () => { kind = select.value; query = search.value.trim(); page = 1; load(); };
  refresh.onclick = load;
  window.LearningNotebook = {
    enter() { active = true; return load(); },
    leave() { active = false; ++request; controller?.abort(); },
  };
})();
