/* Home learning list reads existing lessons; it never changes completion records. */
(() => {
  'use strict';
  let modules = [], errors = [], loaded = false, generation = 0, reading = 0;
  const root = document.getElementById('dailyLearning');
  const reader = document.getElementById('dailyReader');

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
  async function read(module, lesson) {
    if(module.kind==='plan'){ await window.openPlanCourse(module.id, lesson.lesson_no); return; }
    rememberLearningOrigin();
    if (module.id === 'renzhi') {
      await window.openCopilotLesson(lesson.lesson_no);
      // 开始自动追踪学习时间
      startLearningTimer(lesson.lesson_no);
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
      startLearningTimer(lesson.lesson_no);

      button(reader, '返回学习列表', () => { ++reading; stopLearningTimer(); returnFromLesson(); });
      reader.append(node('h2', lesson.topic));
      reader.append(node('p', '阅读不会自动标记学完；本模块的完成情况以本地学习记录中的本人反馈为准。', 'desc'));
      const content = node('div'); reader.append(content);
      window.renderLearningMarkdown(content, data.content);
      reader.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      if (request !== reading) return;
      stopLearningTimer();
      reader.replaceChildren(node('p', error.message));
      button(reader, '返回学习列表', () => { ++reading; returnFromLesson(); });
      button(reader, '重试', () => read(module, lesson));
    }
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
      const response = await fetch('/api/copilot/lessons/' + lesson.lesson_no + '/learning-record');
      if (!response.ok) throw new Error('加载失败');
      const record = await response.json();

      if (!record || !record.lesson_no) {
        alert('该课程暂无学习记录。');
        return;
      }

      // 显示学习记录对话框
      const dialog = document.createElement('dialog');
      dialog.className = 'learning-record-dialog';

      const content = document.createElement('div');
      content.className = 'learning-record-content';

      content.append(node('h3', `第${String(lesson.lesson_no).padStart(3, '0')}课学习记录`));

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
