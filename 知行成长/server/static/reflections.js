/* 日常记录：低门槛自由记录 + 按需 AI 追问/整理。
   独立于旧 /api/data 全量同步，走专用 /api/reflections 接口。 */
(function () {
  'use strict';

  const PROMPTS = {
    '自由记录': { lead: '今天有什么让你想多停一下？', questions: ['最值得保留的发现是什么？', '还有哪里没想明白？'] },
    '学习收获': { lead: '今天哪个内容让你有了新理解，或仍有疑问？', questions: ['能用自己的话说一遍吗？', '准备在什么情境试用？'] },
    '遇到困难': { lead: '当时具体卡在哪一步？', questions: ['已经尝试过什么？', '下次愿意先试哪个小变化？'] },
    '决策回顾': { lead: '今天做了什么选择？', questions: ['当时依据是什么？', '后来观察到什么？'] },
  };

  let entries = [];
  let entryMap = {};   // id -> entry
  let viewDate = null; // 当前查看日期（今日卡片用）
  let generationUnavailable = '';
  let showArchived = false;

  const h = () => ({ 'Content-Type': 'application/json', 'X-Copilot-Request': '1' });

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function today() { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function fmtDateCN(s) { if (!s) return ''; const p = s.split('-').map(Number); return (p[1]) + '月' + (p[2]) + '日'; }
  function uid() { return (crypto.randomUUID ? crypto.randomUUID() : 'k' + Date.now() + Math.random().toString(16).slice(2)); }

  function statusLabel(e) {
    if (e.archived_at) return '已归档';
    if (e.status === 'organized') return '已整理';
    if (e.status === 'basis_updated') return '整理依据已更新';
    if (e.status === 'suggested') return 'AI 建议待确认';
    return '已记录';
  }

  function statusBadge(e) {
    const label = statusLabel(e);
    const map = { '已记录': 'on', '已整理': 'on', '已归档': 'warn', '整理依据已更新': 'warn', 'AI 建议待确认': 'warn' };
    return '<span class="badge ' + (map[label] || '') + '">' + label + '</span>';
  }

  /* ---------- 数据加载 ---------- */
  async function load(includeArchived) {
    try {
      const r = await fetch('/api/reflections' + (includeArchived ? '?include_archived=true' : ''));
      if (!r.ok) return false;
      const d = await r.json();
      entries = d.entries || [];
      generationUnavailable = d.generation_unavailable || AIConfig.status();
      entryMap = {};
      entries.forEach(e => { entryMap[e.id] = e; });
      return true;
    } catch (e) { return false; }
  }

  /* ---------- 编辑器 ---------- */
  let editor = null; // { entryId, baseVersion, date, kind, raw, guided, answers }

  const draftKey = e => 'grow.reflections.draft.' + (window.Account?.user?.id || 'local') + '.' + (e.entryId || e.date);
  function preserveDraft() {
    if (editor?.saving) { const status=document.getElementById('refDraftStatus'); if(status)status.textContent='正在保存记录，请稍候。'; return false; }
    if (!editor || !document.getElementById('refRaw')) return true;
    const previousKey=draftKey(editor);
    editor.raw = document.getElementById('refRaw').value;
    editor.date = document.getElementById('refDate').value || editor.date;
    try {
      if (!window.Account?.user?.id) throw Error('account unavailable');
      localStorage.setItem(draftKey(editor), JSON.stringify(editor));
      if(previousKey!==draftKey(editor))localStorage.removeItem(previousKey);
      const status=document.getElementById('refDraftStatus');
      if(status)status.textContent='草稿已保存在当前浏览器，尚未同步到账号。';
      return true;
    } catch (_) {
      const status=document.getElementById('refDraftStatus');
      if(status)status.textContent='本机草稿未能保存，请先保存记录或复制原文后再离开。';
      return false;
    }
  }
  function openEditor(date, entryId, options = {}) {
    if(editor?.saving){window.toast('正在保存记录，请稍候。');return;}
    if (entryId && !entryMap[entryId]) {
      window.toast('这条记录暂未读取，请刷新记录后重试。');
      return;
    }
    editor = entryId ? {
      entryId, baseVersion: entryMap[entryId].version,
      date: entryMap[entryId].record_date, kind: entryMap[entryId].prompt_kind || '自由记录',
      raw: entryMap[entryId].raw_text || '', guided: {...(entryMap[entryId].guided_answers || {})},
    } : { entryId: null, baseVersion: 0, date: date || today(), kind: '自由记录', raw: '', guided: {} };

    try {
      const saved = !options.ignoreDraft && window.Account?.user?.id && JSON.parse(localStorage.getItem(draftKey(editor)) || 'null');
      if (saved && saved.entryId === editor.entryId && typeof saved.raw === 'string') editor = {
        ...editor, raw:saved.raw, guided:saved.guided || {}, kind:PROMPTS[saved.kind]?saved.kind:editor.kind,
        date:saved.date || editor.date, four:!!saved.four, restored:true,
        stale:saved.baseVersion !== editor.baseVersion, baseVersion:saved.baseVersion
      };
    } catch (_) {}
    editor.four = options.four || editor.four;
    renderEditor();
  }

  function renderEditor() {
    const e = editor;
    const isEdit = !!e.entryId;
    const kindPrompts = PROMPTS[e.kind] || PROMPTS['自由记录'];
    const chips = Object.keys(PROMPTS).map(k => {
      const on = k === e.kind;
      return '<button type="button" class="chip' + (on ? ' on' : '') + '" onclick="Reflections.setKind(\'' + k + '\')">' + esc(k) + '</button>';
    }).join('');
    const fourOpen = e.four || e.guided && (e.guided.expected || e.guided.observed || e.guided.causes || e.guided.adjustment);

    const html = `
      <h3>${isEdit ? '编辑记录' : '记下今天的一点收获'}</h3>
      <div class="ref-label">${fmtDateCN(e.date)} · 可修改日期</div>
      <p class="desc">${e.stale ? '云端记录已更新，本机草稿仍保留。请先下载草稿并重新读取核对，保存不会覆盖较新记录。' : e.restored ? '已恢复当前账号在此浏览器暂存的草稿。' : '输入会在当前浏览器保留草稿，点击保存记录后同步到账号。'}</p>
      <div class="ref-field">
        <label for="refDate">记录日期</label><input type="date" id="refDate" value="${esc(e.date)}">
      </div>
      <div class="ref-field">
        <div class="ref-lead" id="refLead">${esc(kindPrompts.lead)}</div>
        <label for="refRaw">我的记录</label><textarea id="refRaw" rows="6" maxlength="10000" placeholder="一件做成的事、一个卡点、一次意外，或学习后冒出的疑问。写几句就好。">${esc(e.raw)}</textarea>
        <div class="ref-limit" id="refLimit">${e.raw.length} / 10000</div>
      </div>
      <div class="ref-sec-label">找个切入点（可选）</div>
      <div class="chips" style="margin-bottom:14px">${chips}</div>
      <details class="ref-details" id="refQDetails" ${(e.guided && Object.keys(e.guided).length) ? 'open' : ''}>
        <summary>想再想一步（可选）</summary>
        <div class="ref-guide-questions" id="refGuideQuestions"></div>
      </details>
      <details class="ref-details" id="refFourDetails" ${fourOpen ? 'open' : ''}>
        <summary>用四问深入复盘</summary>
        <div class="ref-four" id="refFour"></div>
      </details>
      <div class="ref-err" id="refErr" role="alert"></div>
      <p id="refDraftStatus" class="desc" role="status"></p>
      <div id="refConflict"></div>
      <div class="modal actions">
        ${isEdit ? '<button class="btn" onclick="Reflections.reloadEditor()">下载当前草稿并重新读取</button>' : ''}
        <button class="btn" onclick="Reflections.copyEditorText()">复制当前原文</button>
        <button class="btn" onclick="Reflections.closeEditor()">稍后继续</button>
        <button class="btn primary" id="refSaveBtn" onclick="Reflections.saveEntry()">保存记录</button>
      </div>`;

    openModal(html);
    const rawEl = document.getElementById('refRaw');
    rawEl.addEventListener('input', () => {
      document.getElementById('refLimit').textContent = rawEl.value.length + ' / 10000';
      preserveDraft();
    });
    document.getElementById('refDate').addEventListener('change', preserveDraft);
    renderGuideQuestions();
    renderFourQuestions();
  }

  function renderGuideQuestions() {
    const e = editor;
    const qs = PROMPTS[e.kind] ? PROMPTS[e.kind].questions : [];
    const box = document.getElementById('refGuideQuestions');
    if (!box) return;
    box.innerHTML = qs.map((q, i) => {
      const val = e.guided ? (e.guided[q] || '') : '';
      return '<div class="ref-q"><div class="ref-q-text">' + esc(q) + '</div><textarea rows="2" aria-label="' + esc(q) + '" data-guide="' + i + '" placeholder="可不填">' + esc(val) + '</textarea></div>';
    }).join('') || '<div class="ref-empty">暂无引导问题，直接写就好。</div>';
    box.querySelectorAll('textarea[data-guide]').forEach(t => {
      const qi = parseInt(t.dataset.guide, 10);
      const q = qs[qi];
      t.addEventListener('input', () => { if (!editor.guided) editor.guided = {}; editor.guided[q] = t.value; preserveDraft(); });
    });
  }

  function renderFourQuestions() {
    const e = editor;
    const box = document.getElementById('refFour');
    if (!box) return;
    const fields = [
      ['expected', '当时的预期'], ['observed', '实际观察'],
      ['causes', '可能原因与待核实处（可不填）'], ['adjustment', '下次想试的调整'],
    ];
    if (!e.guided) e.guided = {};
    box.innerHTML = fields.map(([k, label]) => {
      const val = e.guided[k] || '';
      return '<div class="ref-q"><div class="ref-q-text">' + label + '</div><textarea rows="2" aria-label="' + esc(label) + '" data-four="' + k + '" placeholder="可不填">' + esc(val) + '</textarea></div>';
    }).join('');
    box.querySelectorAll('textarea[data-four]').forEach(t => {
      t.addEventListener('input', () => { editor.guided[t.dataset.four] = t.value; preserveDraft(); });
    });
  }

  window.Reflections = window.Reflections || {};
  Object.assign(window.Reflections, {
    openEditor,
    setKind(kind) {
      if(!editor || editor.saving)return;
      editor.kind = kind;
      const lead = document.getElementById('refLead');
      if (lead) lead.textContent = PROMPTS[kind].lead;
      // 切换提示只改问题，不清空已填正文与回答
      renderGuideQuestions();
      preserveDraft();
    },
    closeEditor() { if(!preserveDraft())return;editor = null; closeModal(); },
    preserveDraft,

    async saveEntry() {
      if(!editor || editor.saving)return;
      let raw = document.getElementById('refRaw').value;
      const date = document.getElementById('refDate').value;
      const errEl = document.getElementById('refErr');
      if (!raw.trim()) {
        const labels={expected:'当时的预期',observed:'实际观察',causes:'可能原因',adjustment:'下次想试的调整'};
        raw=Object.entries(editor.guided || {}).filter(([,answer])=>String(answer).trim()).map(([key,answer])=>(labels[key] || key)+'：'+answer).join('\n');
      }
      if (!raw.trim()) { errEl.textContent = '写几句正文，或至少回答一个复盘问题后保存。'; return; }
      if (!date) { errEl.textContent = '请选择日期。'; return; }
      if (raw.length > 10000) { errEl.textContent = '正文过长，请精简。'; return; }

      preserveDraft();
      editor.saving=true;
      const controls=[...document.querySelectorAll('#modalBox input,#modalBox textarea,#modalBox select,#modalBox button')];
      const disabled=controls.map(control=>!!control.disabled);
      controls.forEach(control=>{control.disabled=true;});
      const unlock=()=>{editor.saving=false;controls.forEach((control,index)=>{control.disabled=disabled[index];});};
      const btn = document.getElementById('refSaveBtn');
      btn.disabled = true; btn.textContent = '保存中…';
      const payload = {
        record_date: date, prompt_kind: editor.kind,
        raw_text: raw.trim(), guided_answers: editor.guided || {},
        key: uid(),
      };
      try {
        let r;
        if (editor.entryId) {
          payload.base_version = editor.baseVersion;
          r = await fetch('/api/reflections/' + editor.entryId, { method: 'PUT', headers: h(), body: JSON.stringify(payload) });
        } else {
          r = await fetch('/api/reflections', { method: 'POST', headers: h(), body: JSON.stringify(payload) });
        }
        if (r.ok) {
          const res = await r.json();
          try { localStorage.removeItem(draftKey(editor)); } catch (_) {}
          await load();
          editor = null;
          closeModal();
          window.toast('已保存记录');
          renderAll();
          return;
        }
        const d = await r.json().catch(() => ({}));
        const msg = d.message || (r.status === 409 ? '记录已被更新，请重新查看。' : '保存失败，请重试。');
        errEl.textContent = msg;
        unlock();
        btn.disabled = false; btn.textContent = '保存记录';
        if (r.status === 409 && d.error === 'external_change') {
          await showFileConflict(editor.entryId);
        }
      } catch (e) {
        errEl.textContent = '保存失败 · 服务未连接，内容已保留。';
        unlock();
        btn.disabled = false; btn.textContent = '保存记录';
      }
    },
  });

  /* ---------- 今日卡片渲染 ---------- */
  function renderDay(container, date) {
    if (!container) return;
    const list = entries.filter(e => e.record_date === date && !e.archived_at);
    container.innerHTML = list.map(e => {
      const preview = (e.raw_text || '').slice(0, 120) + ((e.raw_text && e.raw_text.length > 120) ? '…' : '');
      return '<article class="ref-card">'
        + '<div class="ref-card-meta">' + statusBadge(e) + '<span>' + esc(e.prompt_kind || '自由记录') + '</span></div>'
        + '<div class="ref-card-body">' + esc(preview) + '</div>'
        + '<div class="ref-card-actions"><button class="icon-btn" onclick="Reflections.viewEntry(\'' + e.id + '\')">查看</button>'
        + '<button class="icon-btn" onclick="Reflections.openEditor(null, \'' + e.id + '\')">编辑</button></div>'
        + '</article>';
    }).join('') || '<div class="ref-empty">记下一件值得留下的小事，也可以晚些再写。</div>';
  }

  /* ---------- 记录列表渲染（按日期聚合） ---------- */
  function renderList(container, includeArchived) {
    if (!container) return;
    const items = includeArchived ? entries : entries.filter(e => !e.archived_at);
    const groups = {};
    items.forEach(e => { (groups[e.record_date] = groups[e.record_date] || []).push(e); });
    const dates = Object.keys(groups).sort().reverse();
    if (!dates.length) { container.innerHTML = '<div class="empty">还没有记录。今天记下一件小事吧。</div>'; return; }
    container.innerHTML = dates.map(d => {
      const rows = groups[d].map(e => {
        const preview = (e.raw_text || '').slice(0, 80) + ((e.raw_text && e.raw_text.length > 80) ? '…' : '');
        return '<div class="ref-row"><div class="ref-row-body">'
          + statusBadge(e) + '<span class="ref-row-kind">' + esc(e.prompt_kind || '') + '</span>'
          + '<div class="ref-row-preview">' + esc(preview) + '</div></div>'
          + '<div class="ref-row-actions"><button class="icon-btn" onclick="Reflections.viewEntry(\'' + e.id + '\')">查看</button>'
          + '<button class="icon-btn" onclick="Reflections.openEditor(null, \'' + e.id + '\')">编辑</button>'
          + (e.archived_at
            ? '<button class="icon-btn" onclick="Reflections.restoreEntry(\'' + e.id + '\')">恢复</button>'
            : '<button class="icon-btn del" onclick="Reflections.archiveEntry(\'' + e.id + '\')">归档</button>')
          + '</div></div>';
      }).join('');
      return '<h3 class="ref-day">' + fmtDateCN(d) + ' <span class="ref-day-count">' + groups[d].length + ' 条</span></h3>' + rows;
    }).join('');
  }

  /* ---------- 查看详情 + AI ---------- */
  function viewEntry(id) {
    const e = entryMap[id];
    if (!e) return;
    const sections = e.adopted_summary && e.adopted_summary.sections ? e.adopted_summary.sections.map(s => {
      const label = { event: '发生的事情', understanding: '我目前的认识', next_step: '下一步想试什么' }[s.kind] || '补充';
      return '<div class="ref-sect"><div class="ref-sect-label">' + label + '</div><div class="ref-sect-body">' + esc(s.text) + '</div></div>';
    }).join('') : '';

    const aiControls = (e.archived_at) ? '' : `
      <div class="ref-ai-section">
        <div class="ref-ai-desc">保存后可选让 AI 帮你想深一点或整理。${generationUnavailable ? '<br><span style="color:var(--muted)">' + esc(generationUnavailable) + '</span>' : ''}</div>
        <div class="ref-ai-actions">
          <button class="btn" onclick="Reflections.assistOpen('${e.id}', 'clarify')">帮我想深一点</button>
          <button class="btn" onclick="Reflections.assistOpen('${e.id}', 'organize')">帮我整理</button>
        </div>
        <div id="refAssistBox"></div>
      </div>`;

    const html = `
      <h3>记录详情</h3>
      <div class="ref-detail-meta">${statusBadge(e)} <span>${esc(fmtDateCN(e.record_date))} · ${esc(e.prompt_kind || '自由记录')} · 版本 ${e.version}</span></div>
      <div class="ref-detail-raw">${esc(e.raw_text || '')}</div>
      ${sections ? '<h4 style="margin:16px 0 8px">本人采用的整理</h4>' + sections : ''}
      ${aiControls}
      <div id="refConflict"></div>
      <div class="modal actions">
        <button class="btn" onclick="Reflections.showFileConflict('${e.id}')">核对本地文件</button>
        <button class="btn" onclick="Reflections.exportOne('${e.id}')">导出</button>
        <button class="btn" onclick="closeModal()">关闭</button>
      </div>`;
    openModal(html);
  }

  /* ---------- AI 辅助流程 ---------- */
  const assistState = {}; // id -> { kind, key, snapshot }

  function assistOpen(id, kind) {
    const e = entryMap[id];
    assistState[id] = { kind, key: uid(), snapshot: { text: e.raw_text, answers: [] }, answers: [] };
    renderAssistPreview(id);
  }

  function renderAssistPreview(id) {
    const box = document.getElementById('refAssistBox');
    const st = assistState[id];
    const label = st.kind === 'clarify' ? '帮我想深一点' : '帮我整理';
    box.innerHTML = `
      <div class="ref-preview">
        <div class="ref-preview-title">${label} · 以下内容将发送至模型服务，可能产生费用</div>
        <textarea id="refSendText" rows="5">${esc(st.snapshot.text)}</textarea>
        <div class="ref-preview-desc">可删去人名等细节。配置：${esc(window.Reflections.modelLabel || '')}</div>
        <div class="ref-ai-actions">
          <button class="btn" onclick="Reflections.assistSend('${id}')">发送并生成</button>
          <button class="btn" onclick="document.getElementById('refAssistBox').innerHTML=''">返回</button>
        </div>
      </div>`;
    const ta = document.getElementById('refSendText');
    ta.addEventListener('input', () => { st.snapshot.text = ta.value; });
  }

  window.addEventListener('ai-config-changed', () => { generationUnavailable = AIConfig.status(); });

  async function assistSend(id) {
    const st = assistState[id];
    const box = document.getElementById('refAssistBox');
    box.innerHTML = '<div class="ref-empty">正在生成…（可关闭本窗口，稍后重新打开查看）</div>';
    try {
      const r = await fetch('/api/reflections/' + id + '/assist', {
        method: 'POST', headers: h(),
        body: JSON.stringify({ kind: st.kind, snapshot: st.snapshot, key: st.key, ai_config: AIConfig.require() }),
      });
      const d = await r.json();
      if (!r.ok) {
        box.innerHTML = '<div class="ref-err">' + esc(d.message || '生成失败') + '</div>';
        return;
      }
      assistState[id].attemptKey = d.id || st.key;
      trackAssist(d,id);
      // 轮询等待完成
      await pollAttempt(id, d.id || st.key, st.kind, box);
    } catch (e) {
      box.innerHTML = '<div class="ref-err">' + esc(e.message || '生成失败，请检查网络。') + '</div>';
    }
  }

  async function pollAttempt(id, attemptKey, kind, box) {
    for (let i = 0; i < 120; i++) {
      await new Promise(res => setTimeout(res, 1500));
      try {
        const r = await fetch('/api/reflections/attempts/' + attemptKey);
        if (!r.ok) continue;
        const a = await r.json();
        trackAssist(a,id);
        if (a.status === 'ready') { renderAssistResult(id, a); return; }
        if (a.status === 'failed' || a.status === 'cancelled') {
          box.innerHTML = '<div class="ref-err">' + esc(a.error || '生成未完成。') + '</div>';
          return;
        }
      } catch (e) { /* keep polling */ }
    }
    box.innerHTML = '<div class="ref-err">生成超时，请稍后重新打开查看。</div>';
  }

  function renderAssistResult(id, a) {
    const box = document.getElementById('refAssistBox');
    if (a.kind === 'clarify') {
      const qs = (a.questions || []).map((q, i) => {
        const ans = (a.answers || [])[i] || {};
        return '<div class="ref-q"><div class="ref-q-text">' + esc(q.text) + '</div><textarea rows="2" data-ans="' + i + '" placeholder="可不答">' + esc(ans.answer || '') + '</textarea></div>';
      }).join('');
      box.innerHTML = '<div class="ref-ai-result"><div class="ref-ai-result-title">想得更深的问题</div>'
        + (qs || '<div class="ref-empty">已写的内容足够清楚，没有额外问题。</div>')
        + '<div class="ref-ai-actions">'
        + '<button class="btn" onclick="Reflections.saveAnswers(\'' + id + '\', \'' + esc(a.id) + '\')">保存我的回答</button>'
        + '<button class="btn" onclick="Reflections.organizeFromAnswered(\'' + id + '\')">整理这份记录</button>'
        + '</div></div>';
      box.querySelectorAll('textarea[data-ans]').forEach(t => {
        const idx = parseInt(t.dataset.ans, 10);
        t.addEventListener('input', () => { const arr = a.answers || []; arr[idx] = { id: a.questions[idx].id, answer: t.value }; a.answers = arr; });
      });
      return;
    }
    // organize 结果
    const secs = (a.sections || []).map(s => {
      const label = { event: '发生的事情', understanding: '我目前的认识', next_step: '下一步想试什么' }[s.kind] || '补充';
      const basis = s.basis === 'suggestion' ? '（AI 建议，待确认）' : '';
      return '<div class="ref-sect"><div class="ref-sect-label">' + label + ' ' + basis + '</div><textarea rows="2" data-sec="' + s.kind + '">' + esc(s.text) + '</textarea></div>';
    }).join('');
    box.innerHTML = '<div class="ref-ai-result"><div class="ref-ai-result-title">整理草稿（仅保存你确认的版本）</div>' + secs
      + '<div class="ref-ai-actions">'
      + '<button class="btn primary" onclick="Reflections.adoptSummary(\'' + id + '\', \'' + esc(a.id) + '\')">保存这份整理</button>'
      + '<button class="btn" onclick="document.getElementById(\'refAssistBox\').innerHTML=\'\'">放弃</button>'
      + '</div></div>';
    box.querySelectorAll('textarea[data-sec]').forEach(t => {
      t.addEventListener('input', () => {
        const kind = t.dataset.sec;
        const s = (a.sections || []).find(x => x.kind === kind);
        if (s) s.text = t.value;
      });
    });
  }

  async function saveAnswers(id, attemptKey) {
    const a = await fetch('/api/reflections/attempts/' + attemptKey).then(r => r.json()).catch(() => null);
    if (!a) return window.toast('读取回答失败');
    const answers = (a.answers || []).filter(x => x.answer);
    try {
      const r = await fetch('/api/reflections/attempts/' + attemptKey + '/answers', {
        method: 'POST', headers: h(), body: JSON.stringify({ data: { answers } }),
      });
      if (r.ok) window.toast('回答已保存');
    } catch (e) { window.toast('保存回答失败'); }
  }

  async function organizeFromAnswered(id) {
    const st = assistState[id];
    const attemptKey = st.attemptKey || st.key;
    let a = await fetch('/api/reflections/attempts/' + attemptKey).then(r => r.json()).catch(() => null);
    if (!a) return;
    const answered = (a.answers || []).filter(x => x.answer).map(x => ({ question: (a.questions.find(q => q.id === x.id) || {}).text || '', answer: x.answer }));
    st.kind = 'organize';
    st.snapshot = { text: entryMap[id].raw_text, answers: answered };
    st.key = uid();
    await assistSend(id);
  }

  function downloadDraft(text, date) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url;
    link.download = '未保存记录-' + date + '.txt'; link.click(); URL.revokeObjectURL(url);
  }

  async function copyEditorText() {
    const text = document.getElementById('refRaw').value;
    try { await navigator.clipboard.writeText(text); window.toast('已复制当前原文'); }
    catch (e) { downloadDraft(text, editor.date); window.toast('已触发草稿下载，请确认浏览器保存结果'); }
  }

  async function reloadEditor() {
    if(editor?.saving)return;
    const id = editor && editor.entryId;
    if (!id) return;
    const raw = document.getElementById('refRaw').value;
    downloadDraft(raw, editor.date);
    const loaded = await load();
    if (!editor || editor.entryId !== id || !document.getElementById('refRaw')) return;
    if (document.getElementById('refRaw').value !== raw) {
      window.toast('读取期间有新编辑，已保留；请先复制当前原文'); return;
    }
    if (loaded) {
      // The explicit reload already downloaded the draft; do not restore it over the latest record.
      try { localStorage.removeItem(draftKey(editor)); } catch (_) {}
      openEditor(null, id, {ignoreDraft:true});
    }
    else window.toast('读取失败，当前编辑内容仍保留');
  }

  async function showFileConflict(id) {
    if (!id) return;
    try {
      const r = await fetch('/api/reflections/' + id + '/file-status');
      const d = await r.json();
      if (!r.ok) { window.toast(d.message || '文件核对失败'); return; }
      let box = document.getElementById('refConflict');
      if (!box) {
        openModal('<h3>核对记录内容</h3><div id="refConflict"></div><button class="btn" onclick="closeModal()">关闭</button>');
        box = document.getElementById('refConflict');
      }
      box.innerHTML = '<p role="status">' + (d.conflict ? '文件存在外部修改或已移走，系统不会自动覆盖。请先保留需要的内容，再人工核对。' : '文件与原保存内容一致。') + '</p>'
        + '<label>原保存内容<textarea readonly rows="5">' + esc(d.saved_markdown) + '</textarea></label>'
        + '<label>文件当前内容<textarea readonly rows="5">' + esc(d.file_markdown === null ? '文件不存在' : d.file_markdown) + '</textarea></label>';
    } catch (e) { window.toast('无法读取文件，当前编辑内容仍保留'); }
  }

  async function mutationFailure(r, id, fallback) {
    const d = await r.json().catch(() => ({}));
    window.toast(d.message || fallback);
    if (r.status === 409 && d.error === 'external_change') await showFileConflict(id);
  }

  async function adoptSummary(id, attemptKey) {
    try {
      const r = await fetch('/api/reflections/' + id + '/adopt', {
        method: 'POST', headers: h(), body: JSON.stringify({ attempt_key: attemptKey, key: uid() }),
      });
      const d = await r.json();
      if (r.ok) { await load(); window.toast('已保存整理'); viewEntry(id); }
      else { window.toast(d.message || '采用失败'); if (r.status === 409 && d.error === 'external_change') await showFileConflict(id); }
    } catch (e) { window.toast('采用失败'); }
  }

  async function archiveEntry(id) {
    try {
      const r = await fetch('/api/reflections/' + id + '/archive', { method: 'POST', headers: h(), body: JSON.stringify({ data: { key: uid() } }) });
      if (r.ok) { await load(); renderAll(); window.toast('已归档'); }
      else await mutationFailure(r, id, '归档失败');
    } catch (e) { window.toast('归档失败'); }
  }

  async function restoreEntry(id) {
    try {
      const r = await fetch('/api/reflections/' + id + '/restore', { method: 'POST', headers: h(), body: JSON.stringify({ data: { key: uid() } }) });
      if (r.ok) { await load(); renderAll(); window.toast('已恢复'); }
      else await mutationFailure(r, id, '恢复失败');
    } catch (e) { window.toast('恢复失败'); }
  }

  async function exportOne(id) {
    const e = entryMap[id];
    if (!e) return;
    const blob = new Blob([JSON.stringify(e, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'reflection-' + e.record_date + '-' + e.id + '.json';
    a.click(); URL.revokeObjectURL(a.href);
  }

  function renderAll() {
    // 供 index.html 的 renderPersonal / renderReviews 调用
    if (window.renderPersonal) window.renderPersonal();
    if (window.renderReviews) window.renderReviews();
    if (window.renderOverview) window.renderOverview();
  }

  /* 暴露给 index.html 内联调用 */
  Object.assign(window.Reflections, {
    load, renderDay, renderList, viewEntry, showFileConflict, copyEditorText, reloadEditor,
    assistOpen, assistSend, saveAnswers, organizeFromAnswered, adoptSummary,
    archiveEntry, restoreEntry, exportOne, renderAll,
    async toggleArchived() {
      showArchived = !showArchived;
      const btn = document.getElementById('btnShowArchived');
      if (btn) btn.textContent = showArchived ? '返回未归档' : '查看已归档';
      await load(showArchived);
      if (window.renderReviews) window.renderReviews();
    },
    fmtDateCN,
  });
  Object.defineProperties(window.Reflections, {
    entries: {get: () => entries}, entryMap: {get: () => entryMap},
    today: {get: today}, showArchived: {get: () => showArchived}, modelLabel: {get: () => ''}
  });

  /* 首次进入即加载，加载后刷新今日与列表 */
  load().then(() => {
    if (window.renderPersonal) window.renderPersonal();
    if (window.renderReviews) window.renderReviews();
    if (window.renderOverview) window.renderOverview();
  }).catch(() => {});

  window.ReflectionsLoaded = true;
  function assistTask(a,id){return window.GenerationTasks?.external('reflection',a,{entry_id:a.entry_id||id,kind:'reflection-assist',label:a.kind==='clarify'?'复盘追问生成':'复盘整理生成',title:'日常记录 AI 辅助'});}
  function trackAssist(a,id){if(window.GenerationTasks)window.GenerationTasks.track(assistTask(a,id));}
  async function readAssist(job){const response=await fetch('/api/reflections/attempts/'+job.ref,{cache:'no-store'});if(!response.ok)throw new Error('暂时无法读取复盘生成结果。');return response.json();}
  window.GenerationTasks?.register('reflection',{
    read:async job=>assistTask(await readAssist(job),job.entry_id),
    cancel:async job=>{const response=await fetch('/api/reflections/attempts/'+job.ref+'/cancel',{method:'POST',headers:h(),body:'{}'});if(!response.ok)throw new Error('取消未完成，请重试。');return assistTask(await response.json(),job.entry_id);},
    open:async job=>{const a=await readAssist(job);if(!(await load(true)))throw new Error('暂时无法读取日常记录。');viewEntry(job.entry_id);assistState[job.entry_id]={kind:a.kind,key:job.ref,attemptKey:job.ref,snapshot:a.snapshot||{},answers:a.answers||[]};if(a.status==='ready')renderAssistResult(job.entry_id,a);else document.getElementById('refAssistBox').textContent=a.error||'任务仍在生成，进度保留在生成任务中心。';}
  });
})();
