/* Reading never completes a course; only the explicit save action records completion. */
(() => {
  'use strict';
  let modules = [], errors = [], loaded = false, generation = 0, reading = 0;
  const root = document.getElementById('dailyLearning');
  const reader = document.getElementById('dailyReader');
  let studyDraft = null;
  const hasStudyDraft = () => studyDraft && studyDraft.input.value !== studyDraft.saved;
  window.beforeStudyLeave = () => {
    if (studyDraft?.saving) { toast('正在保存学习记录，请稍候。'); return false; }
    if (hasStudyDraft() && !confirm('学习笔记尚未保存，确定离开？')) return false;
    studyDraft = null;
    ++reading;
    stopLearningTimer();
    return true;
  };
  window.addEventListener('beforeunload', event => {
    if (hasStudyDraft() || studyDraft?.saving) { event.preventDefault(); event.returnValue = ''; }
  });

  // 自动学习时长追踪
  let learningStartTime = null;
  let currentLessonNo = null;
  let elapsedTime = 0; // 已累积的时间（秒）
  let timerInterval = null;

  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };

  // 开始追踪学习时间
  function startLearningTimer(lessonNo) {
    if (currentLessonNo === lessonNo && timerInterval) {
      return; // 已经在追踪同一课程
    }

    stopLearningTimer(); // 停止之前的追踪

    currentLessonNo = lessonNo;
    learningStartTime = Date.now();
    elapsedTime = 0;

    // 每秒更新一次显示
    timerInterval = setInterval(() => {
      elapsedTime = Math.floor((Date.now() - learningStartTime) / 1000);
      updateTimerDisplay();
    }, 1000);

    updateTimerDisplay();
  }

  // 停止追踪学习时间
  function stopLearningTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
    learningStartTime = null;
    elapsedTime = 0;
    updateTimerDisplay();
  }

  // 获取当前学习时长
  function getElapsedTime() {
    if (learningStartTime) {
      return Math.floor((Date.now() - learningStartTime) / 1000);
    }
    return elapsedTime;
  }

  // 更新计时器显示
  function updateTimerDisplay() {
    const timerEl = document.getElementById('learningTimer');
    if (timerEl) {
      const seconds = getElapsedTime();
      const minutes = Math.floor(seconds / 60);
      const secs = seconds % 60;
      timerEl.textContent = `${minutes}:${String(secs).padStart(2, '0')}`;
    }
  }
  async function get(path) {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) throw new Error('读取失败，请刷新；若刚升级页面，请重启本地服务。');
    return response.json();
  }
  function button(parent, label, action) {
    const control = node('button', label, 'btn');
    control.type = 'button'; control.onclick = action; parent.append(control);
    return control;
  }
  function toast(message) {
    const toastEl = document.createElement('div');
    toastEl.className = 'toast';
    toastEl.textContent = message;
    document.body.append(toastEl);
    setTimeout(() => toastEl.classList.add('show'), 10);
    setTimeout(() => {
      toastEl.classList.remove('show');
      setTimeout(() => toastEl.remove(), 300);
    }, 2000);
  }
  async function read(module, lesson, continuing = false) {
    if(module.kind==='plan'){ await window.openPlanCourse(module.id, lesson.lesson_no); return; }
    if (!continuing) rememberLearningOrigin();
    if (module.id === 'renzhi') {
      await window.openCopilotLesson(lesson.lesson_no);
      // 开始自动追踪学习时间
      startLearningTimer(module.id + ':' + lesson.lesson_no);
      return;
    }
    const request = ++reading;
    goTab('reader', {reading:true});
    reader.hidden = false;
    reader.replaceChildren(node('p', '正在读取课程…'));
    try {
      const data = await get('/api/study-materials/' + module.id + '/' + encodeURIComponent(lesson.filename));
      if (request !== reading) return;
      reader.replaceChildren();

      // 添加计时器显示
      const timerContainer = node('div', undefined, 'learning-timer-container');
      timerContainer.innerHTML = `
        <span style="color:var(--muted);font-size:12px;">学习时长：</span>
        <span id="learningTimer" style="font-weight:600;color:var(--primary);font-size:14px;">0:00</span>
      `;
      timerContainer.style.cssText = 'margin:12px 0;padding:8px 12px;background:var(--primary-soft);border-radius:8px;display:inline-flex;align-items:center;gap:8px;';
      reader.append(timerContainer);

      // 开始自动追踪学习时间
      startLearningTimer(module.id + ':' + lesson.lesson_no);

      button(reader, '返回学习列表', () => returnFromLesson());
      reader.append(node('h2', lesson.topic));
      reader.append(node('p', '阅读不会自动标记学完。完成后可在下方保存自己的学习笔记和完成记录。', 'desc'));
      const content = node('div'); reader.append(content);
      window.renderLearningMarkdown(content, data.content);
      if (['yingyu', 'biaoda'].includes(module.id)) renderStudyRecord(module, lesson, data);
      reader.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      if (request !== reading) return;
      stopLearningTimer();
      reader.replaceChildren(node('p', error.message));
      button(reader, '返回学习列表', () => { ++reading; returnFromLesson(); });
      button(reader, '重试', () => read(module, lesson));
    }
  }
  function renderStudyRecord(module, lesson, data) {
    let record = data.record, pendingSave = null;
    const form = node('section', undefined, 'section study-record-form');
    form.append(node('h3', '我的学习记录'));
    const status = node('p', record ? `已学完 · ${new Date(record.completed_at).toLocaleString('zh-CN')} · 学习 ${Math.round(record.time_spent_seconds / 60)} 分钟` : '笔记可选，点击保存后才会标记学完。', 'desc');
    status.setAttribute('role', 'status');
    form.append(status);
    const label = node('label', '学习笔记（可选）');
    const input = node('textarea');
    input.rows = 5; input.maxLength = 10000; input.value = record?.summary_text || '';
    input.placeholder = '记录本课收获、练习答案或想继续思考的问题。';
    input.style.cssText = 'display:block;width:100%;box-sizing:border-box;margin:8px 0 12px;';
    label.append(input); form.append(label);
    const draft = {input, saved: input.value, saving: false};
    studyDraft = draft;
    const actions = node('div', undefined, 'day-actions'); form.append(actions);
    const next = button(actions, '继续下一课', async () => {
      if (hasStudyDraft()) { status.textContent = '请先保存当前笔记。'; return; }
      const current = modules.find(item => item.id === module.id);
      const following = current?.lessons.filter(item => item.learning_state !== 'completed').sort((a, b) => a.lesson_no - b.lesson_no)[0];
      if (following) { studyDraft = null; stopLearningTimer(); await read(current, following, true); }
    });
    next.hidden = true;
    const save = button(actions, record || lesson.learning_state === 'completed' ? '保存学习记录' : '标记学完并保存', async () => {
      if (draft.saving) return;
      draft.saving = true; save.disabled = true; next.disabled = true;
      // Retain uncertain submissions so a lost response can be retried without duplicate records.
      pendingSave ||= {summary_text: input.value, time_spent_seconds: getElapsedTime(),
        version: data.lesson.version, revision: record?.revision || 0, key: crypto.randomUUID()};
      const sent = pendingSave;
      status.textContent = '正在保存学习记录…';
      try {
        const response = await fetch('/api/study-materials/' + module.id + '/' + encodeURIComponent(lesson.filename) + '/learning-record', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'}, body: JSON.stringify(sent)
        });
        const result = await response.json();
        if (!response.ok) {
          if (response.status < 500) pendingSave = null;
          throw new Error(result.message || result.detail || '保存失败，请重试。');
        }
        record = result; pendingSave = null; draft.saved = sent.summary_text;
        save.textContent = '保存学习记录';
        await window.loadDailyLearning();
        const current = modules.find(item => item.id === module.id);
        const hasNext = current?.lessons.some(item => item.learning_state !== 'completed');
        next.hidden = !hasNext;
        next.disabled = hasStudyDraft();
        status.textContent = hasStudyDraft() ? '上次提交已保存，当前修改尚未保存。' :
          '已学完，学习记录已保存。' + (hasNext ? '可以继续下一课。' : '本模块已保存课程已全部学完。');
      } catch (error) {
        status.textContent = '保存未完成，笔记仍保留：' + error.message;
      } finally { draft.saving = false; save.disabled = false; }
    });
    save.classList.add('primary');
    input.oninput = () => { next.disabled = hasStudyDraft(); };
    reader.append(form);
  }
  function lessonRow(parent, module, lesson) {
    const row = node('div', undefined, 'todo-row lesson-row' + (lesson.learning_state === 'completed' ? ' completed' : ''));
    const text = node('div'); text.style.flex = '1'; text.style.minWidth = '0'; text.style.overflowWrap = 'anywhere';
    text.append(node('strong', lesson.topic, 'lesson-title'));
    text.append(node('p', `第 ${lesson.lesson_no} 课 · ${lesson.learning_label}${lesson.complete === false ? ' · 资料待修复' : ''}`, 'desc'));
    row.append(text);
    button(row, lesson.learning_state==='completed'?'再次阅读':'开始学习', () => read(module, lesson));
    if (module.id === 'renzhi' && lesson.learning_state === 'completed') {
      if (!lesson.completed_at) button(row, '标记完成', () => quickComplete(module, lesson));
      button(row, '查看记录', () => viewLearningRecord(module, lesson));
    }
    if (['yingyu', 'biaoda'].includes(module.id) && lesson.learning_state === 'completed') {
      button(row, '查看记录', () => viewLearningRecord(module, lesson));
    }
    parent.append(row);
  }
  window.renderDailyLearning = () => {
    document.getElementById('dailyLearningTitle').textContent = '继续学习';
    root.replaceChildren();
    if (!loaded) { root.append(node('p', '正在读取学习内容…')); return; }
    errors.forEach(error => root.append(node('p', error)));
    modules.forEach(module => {
      const lessons = [...module.lessons].sort((a, b) => a.lesson_no - b.lesson_no);
      const pending = lessons.filter(lesson => lesson.learning_state !== 'completed');
      const completed = lessons.filter(lesson => lesson.learning_state === 'completed');
      const section = node('section', undefined, 'learning-module');
      section.append(node('h3', module.name + ' · ' + module.duration));
      section.append(node('p', `待学习 ${pending.length} 课 · 累计已完成 ${completed.length} 课`, 'desc'));

      if (pending.length) {
        section.append(node('h4', '下一课'));
        lessonRow(section, module, pending[0]);
        if (pending.length > 1) {
          const details = node('details');
          details.append(node('summary', `后续课程 · ${pending.length - 1} 课`));
          pending.slice(1).forEach(lesson => lessonRow(details, module, lesson));
          section.append(details);
        }
      } else {
        section.append(node('p', lessons.length ? '已保存课程已全部学完，可随时复习。' : '尚无已保存课程。', 'desc'));
      }
      if (completed.length) {
        const details = node('details', undefined, 'completed-today');
        details.append(node('summary', `已完成课程 · ${completed.length} 课`));
        completed.forEach(lesson => lessonRow(details, module, lesson));
        section.append(details);
      }
      root.append(section);
    });
  };

  async function quickComplete(module, lesson) {
    try {
      const timeSpent = getElapsedTime();
      const response = await fetch('/api/copilot/lessons/' + lesson.lesson_no + '/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Copilot-Request': '1' },
        body: JSON.stringify({ time_spent_seconds: timeSpent, version: lesson.version, key: crypto.randomUUID() })
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.message || '请求失败');
      }
      stopLearningTimer();
      toast(`课程已标记完成（学习时长：${Math.round(timeSpent / 60)} 分钟）`);
      await window.loadDailyLearning();
    } catch (e) {
      alert('标记失败：' + e.message);
    }
  }

  async function viewLearningRecord(module, lesson) {
    try {
      const path = module.id === 'renzhi' ? '/api/copilot/lessons/' + lesson.lesson_no + '/learning-record' :
        '/api/study-materials/' + module.id + '/' + encodeURIComponent(lesson.filename) + '/learning-record';
      const response = await fetch(path, {cache: 'no-store'});
      if (!response.ok) throw new Error('加载失败');
      const record = await response.json();

      if (!record || !record.lesson_no) {
        alert('该课程暂无网页学习记录，可以打开课程补充笔记。');
        return;
      }

      // 显示学习记录对话框
      const dialog = document.createElement('dialog');
      dialog.className = 'learning-record-dialog';

      const content = document.createElement('div');
      content.className = 'learning-record-content';

      content.append(node('h3', `${module.name} · 第${String(lesson.lesson_no).padStart(3, '0')}课学习记录`));

      if (record.completed_at) {
        content.append(node('p', `完成时间：${new Date(record.completed_at).toLocaleString('zh-CN')}`, 'desc'));
      }
      if (record.time_spent_seconds) {
        content.append(node('p', `学习时长：${Math.round(record.time_spent_seconds / 60)} 分钟`, 'desc'));
      }

      if (record.summary_text) {
        const summarySection = node('div', undefined, 'record-section');
        summarySection.append(node('h4', '核心收获'));
        summarySection.append(node('p', record.summary_text));
        content.append(summarySection);
      }

      if (record.review_answers && Object.keys(record.review_answers).length) {
        const reviewSection = node('div', undefined, 'record-section');
        reviewSection.append(node('h4', '练习反馈'));
        const answersList = node('ul');
        Object.entries(record.review_answers).forEach(([qNum, answer]) => {
          const li = node('li');
          li.append(node('strong', `问题${qNum}: `));
          li.append(node('span', answer));
          answersList.append(li);
        });
        reviewSection.append(answersList);
        content.append(reviewSection);
      }

      const closeBtn = document.createElement('button');
      closeBtn.textContent = '关闭';
      closeBtn.className = 'btn';
      closeBtn.onclick = () => dialog.close();
      dialog.addEventListener('close', () => dialog.remove(), {once: true});
      content.append(closeBtn);

      dialog.append(content);
      document.body.append(dialog);
      dialog.showModal();
    } catch (e) {
      alert('加载记录失败：' + e.message);
    }
  }
  function renderLibrary() {
    const library=document.getElementById('learningLibrary');
    library.replaceChildren();
    if(!loaded){library.append(node('p','正在读取课程…'));return;}
    errors.forEach(error=>library.append(node('p',error)));
    modules.forEach(module=>{
      const section=node('section',undefined,'learning-module');
      section.append(node('h3',module.name+' · '+module.duration));
      [...module.lessons].sort((a,b)=>a.lesson_no-b.lesson_no).forEach(lesson=>lessonRow(section,module,lesson));
      if(!module.lessons.length)section.append(node('p','尚无已保存课程。','desc'));
      library.append(section);
    });
  }
  const renderHome=window.renderDailyLearning;
  window.renderDailyLearning=()=>{renderHome();renderLibrary();};
  window.loadDailyLearning = async () => {
    const request = ++generation;
    const results = await Promise.allSettled([get('/api/copilot/today-task'), get('/api/study-materials'), get('/api/plans')]);
    if (request !== generation) return;
    modules = []; errors = [];
    if (results[0].status === 'fulfilled') {
      modules.push({id: 'renzhi', name: '认知与通识', duration: '15–20 分钟', lessons: results[0].value.lessons});
    } else errors.push('认知课程：' + results[0].reason.message);
    if (results[1].status === 'fulfilled') modules.push(...results[1].value.modules);
    else errors.push('英文阅读与结构化表达：' + results[1].reason.message);
    if(results[2].status==='fulfilled') modules.push(...results[2].value.plans.map(p=>({id:p.id,kind:'plan',name:p.name,duration:p.brief.minutes+' 分钟',lessons:p.lessons})));
    else errors.push('学习计划：'+results[2].reason.message);
    modules.forEach(module => {
      module.lessons = module.lessons.map((lesson, index) => ({
        ...lesson,
        lesson_no: lesson.lesson_no || Number((lesson.filename || '').match(/Day\s*(\d+)/i)?.[1]) || index + 1
      }));
    });
    loaded = true;
    window.renderDailyLearning();
  };
  window.loadDailyLearning();
})();
