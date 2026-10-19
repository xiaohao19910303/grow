// 课程反馈弹窗功能 - 分步式流程
(() => {
  'use strict';

  const MASTERY_OPTIONS = [
    { value: 'fully_understood', label: '😎 完全掌握', desc: '能灵活运用，可以教别人' },
    { value: 'basically_understood', label: '🙂 基本懂了', desc: '核心概念理解了，细节还需巩固' },
    { value: 'partially_understood', label: '😐 一知半解', desc: '有些概念还不太清楚' },
    { value: 'not_understood', label: '😟 没学明白', desc: '需要重新学习或更多练习' }
  ];

  const VALUE_OPTIONS = [
    { value: 3, label: '⭐⭐⭐', desc: '很有收获' },
    { value: 2, label: '⭐⭐', desc: '还行' },
    { value: 1, label: '⭐', desc: '一般' },
    { value: 0, label: '○', desc: '没收获' }
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
    const isEditing = !!existing;

    // State management
    const state = {
      step: 1,
      totalSteps: 3,
      data: {
        mastery_level: existing?.mastery_level || null,
        value_rating: existing?.value_rating ?? null,
        feeling_tags: existing?.feeling_tags || [],
        key_learnings: existing?.key_learnings || '',
        questions: existing?.questions || '',
        next_direction: existing?.next_direction || ''
      }
    };

    const dialog = document.createElement('dialog');
    dialog.className = 'cp-feedback-dialog';

    function render() {
      dialog.innerHTML = '';
      const content = document.createElement('div');
      content.className = 'cp-feedback-content';

      // Header with progress
      const header = document.createElement('div');
      header.className = 'fb-header';

      const title = document.createElement('h2');
      title.textContent = isEditing ? `更新第${lessonNo}课反馈` : `第${lessonNo}课反馈`;
      header.append(title);

      // Progress indicator
      const progress = document.createElement('div');
      progress.className = 'fb-progress';
      for (let i = 1; i <= state.totalSteps; i++) {
        const dot = document.createElement('div');
        dot.className = `fb-progress-dot ${i < state.step ? 'completed' : ''} ${i === state.step ? 'active' : ''}`;
        progress.append(dot);
      }
      header.append(progress);

      const stepInfo = document.createElement('div');
      stepInfo.className = 'fb-step-info';
      stepInfo.textContent = `步骤 ${state.step} / ${state.totalSteps}`;
      header.append(stepInfo);

      content.append(header);

      // Render current step
      if (state.step === 1) {
        renderStep1(content);
      } else if (state.step === 2) {
        renderStep2(content);
      } else if (state.step === 3) {
        renderStep3(content);
      }

      // Navigation buttons
      const actions = document.createElement('div');
      actions.className = 'fb-actions';

      if (state.step > 1) {
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '← 上一步';
        prevBtn.className = 'btn';
        prevBtn.onclick = () => { state.step--; render(); };
        actions.append(prevBtn);
      }

      const spacer = document.createElement('div');
      spacer.style.flex = '1';
      actions.append(spacer);

      if (state.step < state.totalSteps) {
        const nextBtn = document.createElement('button');
        nextBtn.textContent = '下一步 →';
        nextBtn.className = 'btn primary';
        nextBtn.onclick = () => {
          if (validateStep(state.step)) {
            state.step++;
            render();
          }
        };
        actions.append(nextBtn);

        if (!isEditing) {
          const skipBtn = document.createElement('button');
          skipBtn.textContent = '跳过';
          skipBtn.className = 'btn';
          skipBtn.style.marginLeft = '8px';
          skipBtn.onclick = () => {
            state.step = state.totalSteps;
            render();
          };
          actions.append(skipBtn);
        }
      } else {
        const saveBtn = document.createElement('button');
        saveBtn.textContent = isEditing ? '更新反馈' : '完成';
        saveBtn.className = 'btn primary';
        saveBtn.onclick = () => saveFeedback();
        actions.append(saveBtn);
      }

      content.append(actions);
      dialog.append(content);
    }

    function renderStep1(container) {
      const desc = document.createElement('p');
      desc.className = 'fb-description';
      desc.textContent = '首先，你觉得这节课掌握得怎么样？';
      container.append(desc);

      // Mastery selection with cards
      const masteryGroup = document.createElement('div');
      masteryGroup.className = 'fb-mastery-grid';

      MASTERY_OPTIONS.forEach(opt => {
        const card = document.createElement('div');
        card.className = `fb-mastery-card ${state.data.mastery_level === opt.value ? 'selected' : ''}`;
        card.onclick = () => {
          state.data.mastery_level = opt.value;
          render();
        };

        const emoji = document.createElement('div');
        emoji.className = 'fb-mastery-emoji';
        emoji.textContent = opt.label.split(' ')[0];

        const label = document.createElement('div');
        label.className = 'fb-mastery-label';
        label.textContent = opt.label.split(' ').slice(1).join(' ');

        const desc = document.createElement('div');
        desc.className = 'fb-mastery-desc';
        desc.textContent = opt.desc;

        card.append(emoji, label, desc);
        masteryGroup.append(card);
      });

      container.append(masteryGroup);
    }

    function renderStep2(container) {
      const desc = document.createElement('p');
      desc.className = 'fb-description';
      desc.textContent = '这节课的收获如何？有什么感受？';
      container.append(desc);

      // Value rating
      const valueField = document.createElement('div');
      valueField.className = 'fb-field';
      const valueLabel = document.createElement('label');
      valueLabel.textContent = '收获程度';
      valueField.append(valueLabel);

      const valueGroup = document.createElement('div');
      valueGroup.className = 'fb-value-group';

      VALUE_OPTIONS.forEach(opt => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `fb-value-btn ${state.data.value_rating === opt.value ? 'selected' : ''}`;
        btn.innerHTML = `<span class="stars">${opt.label}</span><span class="label">${opt.desc}</span>`;
        btn.onclick = () => {
          state.data.value_rating = opt.value;
          render();
        };
        valueGroup.append(btn);
      });

      valueField.append(valueGroup);
      container.append(valueField);

      // Feeling tags
      const feelingField = document.createElement('div');
      feelingField.className = 'fb-field';
      const feelingLabel = document.createElement('label');
      feelingLabel.textContent = '学习感受（可多选）';
      feelingField.append(feelingLabel);

      const feelingGroup = document.createElement('div');
      feelingGroup.className = 'fb-checkbox-group';

      FEELING_TAGS.forEach(tag => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = `fb-chip ${state.data.feeling_tags.includes(tag) ? 'selected' : ''}`;
        chip.textContent = tag;
        chip.onclick = () => {
          const idx = state.data.feeling_tags.indexOf(tag);
          if (idx >= 0) {
            state.data.feeling_tags.splice(idx, 1);
          } else {
            state.data.feeling_tags.push(tag);
          }
          render();
        };
        feelingGroup.append(chip);
      });

      feelingField.append(feelingGroup);
      container.append(feelingField);
    }

    function renderStep3(container) {
      const desc = document.createElement('p');
      desc.className = 'fb-description';
      desc.textContent = '最后，记录一些具体想法（可选）';
      container.append(desc);

      // Key learnings
      const learningsField = document.createElement('div');
      learningsField.className = 'fb-field';
      learningsField.append(Object.assign(document.createElement('label'), { textContent: '💡 核心收获' }));
      const learningsInput = document.createElement('textarea');
      learningsInput.rows = 2;
      learningsInput.placeholder = '这节课学到了什么？哪些观点改变了你的想法？';
      learningsInput.value = state.data.key_learnings;
      learningsInput.oninput = (e) => { state.data.key_learnings = e.target.value; };
      learningsField.append(learningsInput);
      container.append(learningsField);

      // Questions
      const questionsField = document.createElement('div');
      questionsField.className = 'fb-field';
      questionsField.append(Object.assign(document.createElement('label'), { textContent: '❓ 疑问困惑' }));
      const questionsInput = document.createElement('textarea');
      questionsInput.rows = 2;
      questionsInput.placeholder = '哪个点还没搞清？想深入探索什么？';
      questionsInput.value = state.data.questions;
      questionsInput.oninput = (e) => { state.data.questions = e.target.value; };
      questionsField.append(questionsInput);
      container.append(questionsField);

      // Next direction
      const directionField = document.createElement('div');
      directionField.className = 'fb-field';
      directionField.append(Object.assign(document.createElement('label'), { textContent: '🎯 后续方向' }));
      const directionInput = document.createElement('textarea');
      directionInput.rows = 2;
      directionInput.placeholder = '接下来想往哪个方向深入？';
      directionInput.value = state.data.next_direction;
      directionInput.oninput = (e) => { state.data.next_direction = e.target.value; };
      directionField.append(directionInput);
      container.append(directionField);

      // Skip note
      const note = document.createElement('p');
      note.className = 'fb-note';
      note.textContent = '💡 这些内容都是可选的，可以直接点击"完成"保存';
      container.append(note);
    }

    function validateStep(step) {
      if (step === 1 && !state.data.mastery_level) {
        alert('请选择掌握程度');
        return false;
      }
      if (step === 2 && state.data.value_rating === null) {
        alert('请选择收获程度');
        return false;
      }
      return true;
    }

    async function saveFeedback() {
      try {
        await request(`/api/copilot/lessons/${lessonNo}/feedback`, 'POST', state.data);
        dialog.close();

        // Success animation
        dialog.className = 'cp-feedback-dialog success';
        const successContent = document.createElement('div');
        successContent.className = 'fb-success';
        successContent.innerHTML = `
          <div class="success-icon">✓</div>
          <h3>反馈已保存！</h3>
          <p>这有助于AI为你生成更精准的学习建议</p>
        `;
        dialog.append(successContent);
        dialog.showModal();

        setTimeout(() => {
          dialog.close();
          dialog.remove();
        }, 1500);

        // Trigger refresh
        if (typeof window.loadCopilotLessons === 'function') window.loadCopilotLessons(false);
        if (typeof window.refreshDailyLearning === 'function') window.refreshDailyLearning();
      } catch (e) {
        alert('保存失败：' + e.message);
      }
    }

    // Initial render
    render();
    document.body.append(dialog);
    dialog.showModal();

    // Close on backdrop click
    dialog.onclick = (e) => {
      if (e.target === dialog) dialog.close();
    };
  }

  window.showCourseFeedback = showCourseFeedback;
  window.checkLessonFeedback = checkLessonFeedback;
  window.getMasteryEmoji = getMasteryEmoji;

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    .cp-feedback-dialog {
      border: none; border-radius: 16px; padding: 0;
      max-width: 520px; width: 90%; max-height: 85vh; overflow-y: auto;
      box-shadow: 0 20px 60px rgba(0,0,0,0.3);
      animation: dialog-enter 0.3s ease-out;
    }
    @keyframes dialog-enter {
      from { opacity: 0; transform: scale(0.95) translateY(-10px); }
      to { opacity: 1; transform: scale(1) translateY(0); }
    }
    .cp-feedback-dialog::backdrop { background: rgba(0,0,0,0.5); backdrop-filter: blur(4px); }
    .cp-feedback-content { padding: 24px; }

    /* Header */
    .fb-header { margin-bottom: 24px; }
    .fb-header h2 { margin: 0 0 12px; color: var(--text); font-size: 22px; font-weight: 600; }
    .fb-progress { display: flex; gap: 8px; margin-bottom: 8px; }
    .fb-progress-dot {
      flex: 1; height: 4px; border-radius: 2px; background: var(--border);
      transition: all 0.3s ease;
    }
    .fb-progress-dot.active { background: var(--primary); }
    .fb-progress-dot.completed { background: var(--primary); opacity: 0.5; }
    .fb-step-info { font-size: 12px; color: var(--muted); }

    /* Description */
    .fb-description {
      font-size: 15px; color: var(--text); margin: 0 0 20px;
      line-height: 1.5;
    }

    /* Mastery cards */
    .fb-mastery-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .fb-mastery-card {
      padding: 16px; border: 2px solid var(--border); border-radius: 12px;
      cursor: pointer; transition: all 0.2s ease;
      background: var(--bg);
    }
    .fb-mastery-card:hover { border-color: var(--primary); transform: translateY(-2px); }
    .fb-mastery-card.selected {
      border-color: var(--primary); background: var(--primary-soft);
      box-shadow: 0 4px 12px rgba(79,110,247,0.2);
    }
    .fb-mastery-emoji { font-size: 32px; margin-bottom: 8px; }
    .fb-mastery-label { font-weight: 600; font-size: 14px; margin-bottom: 4px; color: var(--text); }
    .fb-mastery-desc { font-size: 12px; color: var(--muted); line-height: 1.4; }

    /* Value rating */
    .fb-value-group { display: flex; gap: 8px; }
    .fb-value-btn {
      flex: 1; padding: 12px 8px; border: 2px solid var(--border); border-radius: 10px;
      background: var(--bg); cursor: pointer; transition: all 0.2s;
      display: flex; flex-direction: column; align-items: center; gap: 4px;
    }
    .fb-value-btn:hover { border-color: var(--primary); }
    .fb-value-btn.selected {
      border-color: var(--primary); background: var(--primary-soft);
    }
    .fb-value-btn .stars { font-size: 18px; }
    .fb-value-btn .label { font-size: 11px; color: var(--muted); }

    /* Chips */
    .fb-checkbox-group { display: flex; flex-wrap: wrap; gap: 8px; }
    .fb-chip {
      padding: 8px 14px; border: 1px solid var(--border); border-radius: 20px;
      background: var(--bg); cursor: pointer; font-size: 13px;
      transition: all 0.15s; color: var(--text);
    }
    .fb-chip:hover { border-color: var(--primary); }
    .fb-chip.selected {
      background: var(--primary); color: white; border-color: var(--primary);
    }

    /* Fields */
    .fb-field { margin-bottom: 18px; }
    .fb-field label {
      display: block; font-weight: 600; margin-bottom: 8px;
      color: var(--text); font-size: 14px;
    }
    .fb-field textarea {
      width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
      font-size: 14px; font-family: inherit; resize: vertical; line-height: 1.6;
      box-sizing: border-box; background: var(--bg);
    }
    .fb-field textarea:focus {
      outline: none; border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(79,110,247,0.1);
    }

    /* Note */
    .fb-note {
      font-size: 12px; color: var(--muted); margin: 16px 0 0;
      padding: 12px; background: var(--bg-soft); border-radius: 8px;
    }

    /* Actions */
    .fb-actions {
      display: flex; align-items: center; gap: 8px;
      margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--border);
    }
    .fb-actions .btn { min-width: 100px; }

    /* Success state */
    .fb-success {
      padding: 40px 24px; text-align: center;
      animation: success-pop 0.4s cubic-beat(0.68, -0.55, 0.265, 1.55);
    }
    @keyframes success-pop {
      0% { transform: scale(0.8); opacity: 0; }
      100% { transform: scale(1); opacity: 1; }
    }
    .success-icon {
      width: 64px; height: 64px; border-radius: 50%;
      background: #4caf50; color: white; font-size: 32px;
      display: inline-flex; align-items: center; justify-content: center;
      margin-bottom: 16px;
    }
    .fb-success h3 { margin: 0 0 8px; color: var(--text); font-size: 20px; }
    .fb-success p { margin: 0; color: var(--muted); font-size: 14px; }

    /* Responsive */
    @media (max-width: 520px) {
      .fb-mastery-grid { grid-template-columns: 1fr; }
      .fb-value-group { flex-wrap: wrap; }
      .fb-value-btn { min-width: calc(50% - 4px); }
    }

    /* Badge */
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
