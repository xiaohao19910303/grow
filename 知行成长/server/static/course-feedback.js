// 课程反馈弹窗功能
(() => {
  'use strict';

  const MASTERY_OPTIONS = [
    { value: 'fully_understood', label: '😎 完全掌握' },
    { value: 'basically_understood', label: '🙂 基本懂了' },
    { value: 'partially_understood', label: '😐 一知半解' },
    { value: 'not_understood', label: '😟 没学明白' }
  ];

  const VALUE_OPTIONS = [
    { value: 3, label: '⭐⭐⭐ 很有收获' },
    { value: 2, label: '⭐⭐ 还行' },
    { value: 1, label: '⭐ 一般' },
    { value: 0, label: '没收获' }
  ];

  const FEELING_TAGS = [
    '太抽象了', '例子很好', '想多练练', '节奏太快',
    '可以复习再看', '概念很清晰', '需要更多案例'
  ];

  async function request(path, method, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json', 'x-copilot-request': '1' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json()).message || '请求失败');
    return r.json();
  }

  async function checkLessonFeedback(lessonNo) {
    try {
      const data = await request(`/api/copilot/lessons/${lessonNo}/feedback`, 'GET');
      return data;
    } catch { return null; }
  }

  function getMasteryEmoji(level) {
    const map = { fully_understood: '😎', basically_understood: '🙂', partially_understood: '😐', not_understood: '😟' };
    return map[level] || '';
  }

  async function showCourseFeedback(lessonNo) {
    const existing = await checkLessonFeedback(lessonNo);

    const dialog = document.createElement('dialog');
    dialog.className = 'cp-feedback-dialog';

    const content = document.createElement('div');
    content.className = 'cp-feedback-content';

    const title = document.createElement('h2');
    title.textContent = `第${lessonNo}课完成反馈`;
    content.append(title);

    const desc = document.createElement('p');
    desc.className = 'desc';
    desc.textContent = '课程学习完成后，记录你的掌握情况和感受。这有助于AI生成更精准的总结和进阶课程。';
    content.append(desc);

    // 掌握程度
    const masteryField = document.createElement('div');
    masteryField.className = 'fb-field';
    const masteryLabel = document.createElement('label');
    masteryLabel.textContent = '掌握程度：';
    masteryField.append(masteryLabel);
    const masteryGroup = document.createElement('div');
    masteryGroup.className = 'fb-radio-group';
    MASTERY_OPTIONS.forEach(opt => {
      const rb = document.createElement('label');
      rb.className = 'fb-radio';
      const input = document.createElement('input');
      input.type = 'radio'; input.name = 'mastery'; input.value = opt.value;
      if (existing && existing.mastery_level === opt.value) input.checked = true;
      rb.append(input, document.createTextNode(' ' + opt.label));
      masteryGroup.append(rb);
    });
    masteryField.append(masteryGroup);
    content.append(masteryField);

    // 收获评价
    const valueField = document.createElement('div');
    valueField.className = 'fb-field';
    const valueLabel = document.createElement('label');
    valueLabel.textContent = '收获评价：';
    valueField.append(valueLabel);
    const valueGroup = document.createElement('div');
    valueGroup.className = 'fb-radio-group';
    VALUE_OPTIONS.forEach(opt => {
      const rb = document.createElement('label');
      rb.className = 'fb-radio';
      const input = document.createElement('input');
      input.type = 'radio'; input.name = 'value'; input.value = opt.value;
      if (existing && existing.value_rating === opt.value) input.checked = true;
      rb.append(input, document.createTextNode(' ' + opt.label));
      valueGroup.append(rb);
    });
    valueField.append(valueGroup);
    content.append(valueField);

    // 学习感受
    const feelingField = document.createElement('div');
    feelingField.className = 'fb-field';
    const feelingLabel = document.createElement('label');
    feelingLabel.textContent = '学习感受（可多选）：';
    feelingField.append(feelingLabel);
    const feelingGroup = document.createElement('div');
    feelingGroup.className = 'fb-checkbox-group';
    const existingTags = existing ? (existing.feeling_tags || []) : [];
    FEELING_TAGS.forEach(tag => {
      const cb = document.createElement('label');
      cb.className = 'fb-checkbox';
      const input = document.createElement('input');
      input.type = 'checkbox'; input.name = 'feeling'; input.value = tag;
      if (existingTags.includes(tag)) input.checked = true;
      cb.append(input, document.createTextNode(' ' + tag));
      feelingGroup.append(cb);
    });
    // 自定义标签
    const customWrap = document.createElement('label');
    customWrap.className = 'fb-checkbox';
    const customCb = document.createElement('input');
    customCb.type = 'checkbox'; customCb.name = 'feeling_custom_toggle';
    customWrap.append(customCb, document.createTextNode(' 其他'));
    const customInput = document.createElement('input');
    customInput.type = 'text'; customInput.name = 'feeling_custom';
    customInput.placeholder = '输入自定义感受';
    customInput.style.cssText = 'margin-left:8px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;font-size:13px;width:140px';
    customCb.onchange = () => { customInput.disabled = !customCb.checked; if (customCb.checked) customInput.focus(); };
    customInput.disabled = true;
    feelingGroup.append(customWrap, customInput);
    feelingField.append(feelingGroup);
    content.append(feelingField);

    // 核心收获
    const learningsField = document.createElement('div');
    learningsField.className = 'fb-field';
    learningsField.append(Object.assign(document.createElement('label'), { textContent: '核心收获（可选）：' }));
    const learningsInput = document.createElement('textarea');
    learningsInput.rows = 3;
    learningsInput.placeholder = '这节课我学到了什么？哪些观点改变了我的想法？';
    learningsInput.value = existing ? (existing.key_learnings || '') : '';
    learningsField.append(learningsInput);
    content.append(learningsField);

    // 疑问/困惑
    const questionsField = document.createElement('div');
    questionsField.className = 'fb-field';
    questionsField.append(Object.assign(document.createElement('label'), { textContent: '疑问/困惑（可选）：' }));
    const questionsInput = document.createElement('textarea');
    questionsInput.rows = 3;
    questionsInput.placeholder = '哪个点还没搞清？想深入探索什么？';
    questionsInput.value = existing ? (existing.questions || '') : '';
    questionsField.append(questionsInput);
    content.append(questionsField);

    // 后续方向
    const directionField = document.createElement('div');
    directionField.className = 'fb-field';
    directionField.append(Object.assign(document.createElement('label'), { textContent: '后续方向（可选）：' }));
    const directionInput = document.createElement('textarea');
    directionInput.rows = 2;
    directionInput.placeholder = '接下来想往哪个方向深入？';
    directionInput.value = existing ? (existing.next_direction || '') : '';
    directionField.append(directionInput);
    content.append(directionField);

    // 按钮
    const actions = document.createElement('div');
    actions.className = 'cp-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = existing ? '关闭' : '取消';
    cancelBtn.className = 'btn';
    cancelBtn.onclick = () => dialog.close();
    actions.append(cancelBtn);

    const saveBtn = document.createElement('button');
    saveBtn.textContent = existing ? '更新反馈' : '保存反馈';
    saveBtn.className = 'btn primary';
    saveBtn.onclick = async () => {
      const masteryEl = masteryGroup.querySelector('input:checked');
      if (!masteryEl) { alert('请选择掌握程度'); return; }
      const valueEl = valueGroup.querySelector('input:checked');
      if (!valueEl) { alert('请选择收获评价'); return; }

      const feelingTags = [];
      feelingGroup.querySelectorAll('input[name="feeling"]:checked').forEach(cb => feelingTags.push(cb.value));
      if (customCb.checked && customInput.value.trim()) feelingTags.push(customInput.value.trim());

      const body = {
        mastery_level: masteryEl.value,
        value_rating: parseInt(valueEl.value),
        feeling_tags: feelingTags,
        key_learnings: learningsInput.value.trim(),
        questions: questionsInput.value.trim(),
        next_direction: directionInput.value.trim()
      };

      try {
        await request(`/api/copilot/lessons/${lessonNo}/feedback`, 'POST', body);
        dialog.close();
        // Show toast
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = '反馈已保存！';
        document.body.append(toast);
        setTimeout(() => toast.classList.add('show'), 10);
        setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
        // Trigger refresh
        if (typeof window.loadCopilotLessons === 'function') window.loadCopilotLessons(false);
        if (typeof window.refreshDailyLearning === 'function') window.refreshDailyLearning();
      } catch (e) {
        alert('保存失败：' + e.message);
      }
    };
    actions.append(saveBtn);

    content.append(actions);
    dialog.append(content);
    document.body.append(dialog);
    dialog.showModal();
  }

  window.showCourseFeedback = showCourseFeedback;
  window.checkLessonFeedback = checkLessonFeedback;
  window.getMasteryEmoji = getMasteryEmoji;

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    .cp-feedback-dialog {
      border: none; border-radius: 12px; padding: 0;
      max-width: 560px; width: 90%; max-height: 85vh; overflow-y: auto;
      box-shadow: 0 10px 40px rgba(0,0,0,0.2);
    }
    .cp-feedback-dialog::backdrop { background: rgba(0,0,0,0.4); backdrop-filter: blur(4px); }
    .cp-feedback-content { padding: 24px; }
    .cp-feedback-content h2 { margin-top: 0; color: var(--text); font-size: 20px; }
    .cp-feedback-content .desc { color: var(--muted); font-size: 14px; margin-bottom: 20px; }
    .fb-field { margin-bottom: 18px; }
    .fb-field label { display: block; font-weight: 600; margin-bottom: 8px; color: var(--text); font-size: 14px; }
    .fb-radio-group, .fb-checkbox-group { display: flex; flex-wrap: wrap; gap: 8px; }
    .fb-radio, .fb-checkbox {
      display: inline-flex; align-items: center; padding: 6px 12px;
      border: 1px solid var(--border); border-radius: 20px; cursor: pointer;
      font-size: 13px; transition: all 0.15s;
    }
    .fb-radio:hover, .fb-checkbox:hover { border-color: var(--primary); background: var(--bg-soft); }
    .fb-radio input:checked + *, .fb-checkbox input:checked + * { color: var(--primary); font-weight: 600; }
    .fb-radio input, .fb-checkbox input { margin-right: 4px; }
    .fb-field textarea {
      width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px;
      font-size: 14px; font-family: inherit; resize: vertical; line-height: 1.6;
      box-sizing: border-box;
    }
    .fb-field textarea:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79,110,247,0.1); }
    .fb-badge {
      display: inline-flex; align-items: center; gap: 4px;
      background: #e8f5e9; color: #2e7d32; padding: 3px 10px; border-radius: 12px;
      font-size: 12px; font-weight: 500;
    }
    .fb-pending {
      display: inline-flex; align-items: center; gap: 4px;
      background: #fff3e0; color: #e65100; padding: 3px 10px; border-radius: 12px;
      font-size: 12px; font-weight: 500;
    }
  `;
  document.head.append(style);
})();
