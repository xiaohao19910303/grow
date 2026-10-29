/* Reading never completes a course; only the explicit save action records completion. */
(() => {
  'use strict';

  // 注入庆祝动画样式
  const celebrationStyle = document.createElement('style');
  celebrationStyle.textContent = `
    .completion-celebration {
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(4px);
      display: flex; align-items: center; justify-content: center;
      z-index: 10000; animation: celebration-fade-in 0.3s ease-out;
    }
    .completion-celebration.fade-out {
      animation: celebration-fade-out 0.5s ease-out forwards;
    }
    @keyframes celebration-fade-in {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes celebration-fade-out {
      from { opacity: 1; }
      to { opacity: 0; }
    }
    .celebration-content {
      background: white; padding: 48px 64px; border-radius: 20px;
      text-align: center; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
      animation: celebration-pop 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55);
      position: relative; overflow: hidden;
    }
    @keyframes celebration-pop {
      0% { transform: scale(0.5); opacity: 0; }
      100% { transform: scale(1); opacity: 1; }
    }
    .celebration-icon {
      font-size: 80px; margin-bottom: 20px;
      animation: celebration-bounce 0.6s ease-in-out;
    }
    @keyframes celebration-bounce {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-20px); }
    }
    .celebration-content h2 {
      margin: 0 0 12px; font-size: 32px; color: var(--text, #333);
      font-weight: 700;
    }
    .celebration-content p {
      margin: 0; font-size: 18px; color: var(--muted, #666);
    }
    .confetti-container {
      position: absolute; top: 0; left: 0; right: 0; bottom: 0;
      pointer-events: none; overflow: hidden;
    }
    .confetti {
      position: absolute; width: 10px; height: 10px;
      top: -10px; animation: confetti-fall 3s linear forwards;
    }
    @keyframes confetti-fall {
      0% { transform: translateY(0) rotate(0deg); opacity: 1; }
      100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
    }
  `;
  document.head.append(celebrationStyle);

  let modules = [], errors = [], loaded = false, generation = 0, reading = 0;
  const root = document.getElementById('dailyLearning');
  const reader = document.getElementById('dailyReader');
  let studyDraft = null, listRequest = null, pendingModules = [];
  const hasStudyDraft = () => studyDraft && !studyDraft.notes.safe;
  window.beforeStudyLeave = () => {
    if (studyDraft?.saving) { toast('正在保存学习记录，请稍候。'); return false; }
    if (window.StudyNotes && !window.StudyNotes.beforeLeave()) return false;
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
  // 课程完成庆祝动画
  function showCompletionCelebration(lessonNo) {
    const celebration = document.createElement('div');
    celebration.className = 'completion-celebration';
    celebration.innerHTML = `
      <div class="celebration-content">
        <div class="celebration-icon">🎉</div>
        <h2>太棒了！</h2>
        <p>你已完成第 ${lessonNo} 课</p>
        <div class="confetti-container"></div>
      </div>
    `;
    document.body.append(celebration);

    // 创建彩纸效果
    const confettiContainer = celebration.querySelector('.confetti-container');
    for (let i = 0; i < 50; i++) {
      const confetti = document.createElement('div');
      confetti.className = 'confetti';
      confetti.style.left = Math.random() * 100 + '%';
      confetti.style.animationDelay = Math.random() * 0.5 + 's';
      confetti.style.backgroundColor = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#f9ca24', '#6c5ce7'][Math.floor(Math.random() * 5)];
      confettiContainer.append(confetti);
    }

    // 动画结束后移除
    setTimeout(() => {
      celebration.classList.add('fade-out');
      setTimeout(() => celebration.remove(), 500);
    }, 2500);
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
    if (goTab('reader', {reading:true}) === false) return;
    const turn = window.studyReaderRequest;
    reader.hidden = false;
    reader.replaceChildren();
    const loading = window.LoadingState?.start(reader, '正在读取课程…', '正在读取课程正文和你的学习记录。');
    try {
      const data = await get('/api/study-materials/' + module.id + '/' + encodeURIComponent(lesson.filename));
      if (request !== reading || turn !== window.studyReaderRequest) return;
      reader.replaceChildren();
      window.AIEvidence?.mount(reader,'study-course',module.id+'/'+lesson.filename);

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

      button(reader, (window.lessonReturnLabel?.() || '返回我的课程'), () => returnFromLesson());
      reader.append(node('h2', lesson.topic));
      reader.append(node('p', '笔记与练习答案可随时暂存；只有主动确认学完才会更新完成记录。', 'desc'));
      const content = node('div'); reader.append(content);
      window.renderLearningMarkdown(content, data.content);
      if (data.lesson?.github_url) {
        const link = node('a', '在 GitHub 查看课程'); link.href = data.lesson.github_url;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; reader.append(link);
      }
      if (['yingyu', 'biaoda'].includes(module.id)) renderStudyRecord(module, lesson, data, content);
      window.LearningPractices?.mount(reader,{module_id:module.id,filename:lesson.filename});
      window.CourseLibrary?.recordOpened(module.id, lesson.lesson_no);
      reader.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      if (request !== reading || turn !== window.studyReaderRequest) return;
      stopLearningTimer();
      reader.replaceChildren(node('p', error.message));
      button(reader, (window.lessonReturnLabel?.() || '返回我的课程'), () => { ++reading; returnFromLesson(); });
      button(reader, '重试', () => read(module, lesson));
    } finally { loading?.finish(); }
  }
  function renderStudyRecord(module, lesson, data, content) {
    let record = data.record, pendingSave = null;
    const notes = window.StudyNotes.mount({parent: reader, content, kind: module.id,
      course: lesson.filename, version: data.lesson.version, seedNotes: record?.summary_text || ''});
    const form = notes.form;
    const status = node('p', record ? `已学完 · ${new Date(record.completed_at).toLocaleString('zh-CN')} · 学习 ${Math.round(record.time_spent_seconds / 60)} 分钟` :
      lesson.learning_state === 'completed' ? '本课已完成（历史记录）；笔记与答案可独立暂存。' : '本课尚未完成；暂存笔记不会标记学完。', 'desc');
    status.setAttribute('role', 'status');
    form.insertBefore(status, notes.status);
    const input = notes.input;
    const draft = {input, saved: input.value, saving: false, notes};
    studyDraft = draft;
    const actions = notes.actions;
    const generationPanel = node('div'); form.append(generationPanel);
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
      status.textContent = '正在保存学习记录…';
      try {
        await notes.flush();
        // Retain uncertain submissions so a lost response can be retried without duplicate records.
        pendingSave ||= {summary_text: input.value, time_spent_seconds: getElapsedTime(),
          version: data.lesson.version, revision: record?.revision || 0, key: crypto.randomUUID()};
        const sent = pendingSave;
        const response = await fetch('/api/study-materials/' + module.id + '/' + encodeURIComponent(lesson.filename) + '/learning-record', {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'}, body: JSON.stringify(sent)
        });
        const result = await response.json();
        if (!response.ok) {
          if (response.status < 500) pendingSave = null;
          throw new Error(result.message || result.detail || '保存失败，请重试。');
        }
        record = result; pendingSave = null; draft.saved = sent.summary_text;
        await window.refreshLearningCompletion?.(result);
        save.textContent = '保存学习记录';
        await window.loadDailyLearning({force:true});
        const current = modules.find(item => item.id === module.id);
        const hasNext = current?.lessons.some(item => item.learning_state !== 'completed');
        next.hidden = !hasNext;
        next.disabled = hasStudyDraft();
        status.textContent = input.value !== sent.summary_text ? '已学完；最新修改的笔记会单独暂存。' :
          '已学完，学习记录已保存。' + (hasNext ? '可以继续下一课。' : '本模块已保存课程已全部学完。');
        generationPanel.replaceChildren();
        if (current) window.CourseContinuation?.mount(generationPanel,module.id,{refresh:true});
      } catch (error) {
        status.textContent = '保存未完成，笔记仍保留：' + error.message;
      } finally { draft.saving = false; save.disabled = false; }
    });
    save.classList.add('primary');
    input.oninput = () => { next.disabled = hasStudyDraft(); };
    if (lesson.learning_state === 'completed') window.CourseContinuation?.mount(generationPanel,module.id,{refresh:true});
    reader.append(form);
  }
  window.openStudyCourse = async (moduleId, filename, options = {}) => {
    const module = modules.find(item => item.id === moduleId);
    const lesson = module?.lessons.find(item => item.filename === filename);
    if (!lesson) throw new Error('课程列表尚未更新，请刷新后重试。');
    const continuing = !!studyDraft;
    if (continuing && !window.beforeStudyLeave()) return;
    await read(module, lesson, continuing || !!options.preserveOrigin);
  };
  function lessonTarget(module, lesson) {
    return module.kind==='plan'?{kind:'plan',plan_id:module.id,lesson_no:lesson.lesson_no}:module.id==='renzhi'?{kind:'renzhi',lesson_no:lesson.lesson_no}:{kind:module.id,course:lesson.filename};
  }
  function lessonRow(parent, module, lesson, continuing = false) {
    const row = node('div', undefined, 'todo-row lesson-row' + (lesson.learning_state === 'completed' ? ' completed' : ''));
    const text = node('div'); text.style.flex = '1'; text.style.minWidth = '0'; text.style.overflowWrap = 'anywhere';
    text.append(node('strong', lesson.topic, 'lesson-title'));
    text.append(node('p', `第 ${lesson.lesson_no} 课 · ${lesson.learning_label}${lesson.complete === false ? ' · 资料待修复' : ''}`, 'desc'));
    row.append(text);
    const start=button(row, lesson.learning_state==='completed'?'再次阅读':continuing?'继续学习':'开始学习', () => {
      if(continuing)window.actionContentOrigin=null;
      return read(module, lesson);
    });
    if(continuing)start.classList.add('primary');
    if (module.id === 'renzhi' && lesson.learning_state === 'completed') {
      if (!lesson.completed_at) button(row, '标记完成', () => quickComplete(module, lesson));
      button(row, '查看记录', () => viewLearningRecord(module, lesson));
    }
    if (['yingyu', 'biaoda'].includes(module.id) && lesson.learning_state === 'completed') {
      button(row, '查看记录', () => viewLearningRecord(module, lesson));
    }
    parent.append(row);
    const scheduleControls=node('div');parent.append(scheduleControls);window.DailyAgenda?.mount(scheduleControls,lessonTarget(module,lesson),lesson.topic,parseInt(module.duration,10)||20,{compact:continuing});
  }
  // 待继续课程按学习进度选课；仅排除当前日期已安排的课程，不按内容生成日期推断今日任务。
  window.renderDailyLearning = () => {
    document.getElementById('dailyLearningTitle').textContent='待继续课程';root.replaceChildren();
    if(!loaded){root.append(node('p','正在读取学习内容…'));return;}
    errors.forEach(error=>root.append(node('p',error)));
    const selected=document.getElementById('personalDate')?.value||window.ActionPlans?.day();
    const available=modules.filter(module=>!['paused','archived'].includes(module.status)).map(module=>({module,lesson:[...module.lessons].sort((a,b)=>a.lesson_no-b.lesson_no).find(l=>l.learning_state!=='completed')})).filter(({module,lesson})=>lesson&&!window.DailyAgenda?.isScheduled(lessonTarget(module,lesson),selected)).slice(0,3);
    for(const {module,lesson} of available){const section=node('section',undefined,'learning-module');section.append(node('h3',module.name));lessonRow(section,module,lesson,true);root.append(section);}
    if(!available.length)root.append(node('p',pendingModules.length?'正在读取可继续的课程…':'当前日期已安排的课程在上方列表中；暂无其他待继续课程。全部课程可在「学习」中查看。','desc'));
    button(root,'查看全部课程',()=>goTab('library'));
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
      await window.refreshLearningCompletion?.(await response.json());
      stopLearningTimer();
      showCompletionCelebration(lesson.lesson_no);
      await window.loadDailyLearning({force:true});
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
  function renderLibrary() { window.CourseLibrary?.render(); }
  window.DailyLearning = {read, lessonRow, snapshot:()=>({modules,errors,pending:pendingModules,loaded})};
  const renderHome=window.renderDailyLearning;
  window.renderOptionalLearning=renderHome;
  window.renderDailyLearning=()=>{renderHome();renderLibrary();};
  window.loadDailyLearning = (options = {}) => {
    if(listRequest && !options.force)return listRequest;
    window.refreshAutoCheckins?.();
    const request=++generation;
    const groups=[modules.filter(m=>m.id==='renzhi'),modules.filter(m=>['yingyu','biaoda'].includes(m.id)),modules.filter(m=>m.kind==='plan')];
    const sources=[['认知课程','/api/copilot/today-task',data=>[{id:'renzhi',name:'认知与通识',duration:'15–20 分钟',lessons:data.lessons}]],
      ['英文阅读与结构化表达','/api/study-materials',data=>data.modules],
      ['课程规划','/api/plans',data=>data.plans.map(p=>({...p,kind:'plan',duration:p.brief.minutes+' 分钟'}))]];
    pendingModules=sources.map(s=>s[0]);errors=[];loaded=true;window.renderDailyLearning();
    const task=Promise.all(sources.map(async([name,path,decode],index)=>{
      try{const data=await get(path);if(request!==generation)return;groups[index]=decode(data);}
      catch(error){if(request!==generation)return;errors.push(name+'：'+error.message);}
      if(request!==generation)return;
      pendingModules=pendingModules.filter(item=>item!==name);
      modules=groups.flat().map(module=>({...module,lessons:module.lessons.map((lesson,index)=>({...lesson,
        lesson_no:lesson.lesson_no||Number((lesson.filename||'').match(/Day\s*(\d+)/i)?.[1])||index+1}))}));
      window.renderDailyLearning();
    })).finally(()=>{if(listRequest===task)listRequest=null;});
    listRequest=task;return task;
  };
  window.loadDailyLearning();
})();
