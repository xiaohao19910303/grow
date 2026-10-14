/* Home learning list reads existing lessons; it never changes completion records. */
(() => {
  'use strict';
  let modules = [], errors = [], loaded = false, generation = 0, reading = 0;
  const root = document.getElementById('dailyLearning');
  const reader = document.getElementById('dailyReader');
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  async function get(path) {
    const response = await fetch(path, {cache: 'no-store'});
    if (!response.ok) throw new Error('读取失败，请刷新；若刚升级页面，请重启本地服务。');
    return response.json();
  }
  function button(parent, label, action) {
    const control = node('button', label, 'btn');
    control.type = 'button'; control.onclick = action; parent.append(control);
  }
  async function read(module, lesson) {
    if(module.kind==='plan'){ await window.openPlanCourse(module.id, lesson.lesson_no); return; }
    rememberLearningOrigin();
    if (module.id === 'renzhi') {
      await window.openCopilotLesson(lesson.lesson_no);
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
      button(reader, '返回学习列表', () => { ++reading; returnFromLesson(); });
      reader.append(node('h2', lesson.topic));
      reader.append(node('p', '阅读不会自动标记学完；本模块的完成情况以本地学习记录中的本人反馈为准。', 'desc'));
      const content = node('div'); reader.append(content);
      window.renderLearningMarkdown(content, data.content);
      reader.scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      if (request !== reading) return;
      reader.replaceChildren(node('p', error.message));
      button(reader, '返回学习列表', () => { ++reading; returnFromLesson(); });
      button(reader, '重试', () => read(module, lesson));
    }
  }
  function lessonRow(parent, module, lesson) {
    const row = node('div', undefined, 'todo-row lesson-row');
    const text = node('div'); text.style.flex = '1'; text.style.minWidth = '0'; text.style.overflowWrap = 'anywhere';
    text.append(node('strong', lesson.topic, 'lesson-title'));
    text.append(node('p', `${lesson.date || '日期未标注'} · ${lesson.learning_label}${lesson.complete === false ? ' · 资料待修复' : ''}`, 'desc'));
    row.append(text);
    button(row, lesson.learning_state==='completed'?'再次阅读':'开始学习', () => read(module, lesson)); parent.append(row);
  }
  window.renderDailyLearning = () => {
    const selected = document.getElementById('personalDate').value || today();
    const prefix = selected === today() ? '今日' : fmtDateCN(selected);
    document.getElementById('dailyLearningTitle').textContent = prefix + '待学习';
    root.replaceChildren();
    if (!loaded) { root.append(node('p', '正在读取学习内容…')); return; }
    errors.forEach(error => root.append(node('p', error)));
    modules.forEach(module => {
      const available = module.lessons.filter(lesson => !lesson.date || lesson.date <= selected);
      const todayLessons = available.filter(lesson => lesson.date === selected);
      const pending = available.filter(lesson => lesson.date !== selected && lesson.learning_state !== 'completed');
      const completed = available.filter(lesson => lesson.learning_state === 'completed').length;
      const section = node('section', undefined, 'learning-module');
      section.append(node('h3', module.name + ' · ' + module.duration));
      section.append(node('p', `已保存 ${available.length} 课 · 本人确认完成 ${completed} 课`, 'desc'));
      const newPending = todayLessons.filter(lesson => lesson.learning_state !== 'completed');
      newPending.forEach(lesson => lessonRow(section, module, lesson));
      if (!todayLessons.length) section.append(node('p', prefix + '暂无新课。', 'desc'));
      else if (!newPending.length) section.append(node('p', prefix + '课程已确认学完。', 'desc'));
      if (pending.length) {
        const details = node('details');
        details.open = false;
        details.append(node('summary', `继续之前的课程 · ${pending.length} 课待本人反馈`));
        pending.forEach(lesson => lessonRow(details, module, lesson));
        section.append(details);
      }
      if (!available.length) section.append(node('p', '该日期暂无已保存课程。', 'desc'));
      root.append(section);
    });
  };
  function renderLibrary() {
    const library=document.getElementById('learningLibrary');
    library.replaceChildren();
    if(!loaded){library.append(node('p','正在读取课程…'));return;}
    errors.forEach(error=>library.append(node('p',error)));
    modules.forEach(module=>{
      const section=node('section',undefined,'learning-module');
      section.append(node('h3',module.name+' · '+module.duration));
      module.lessons.forEach(lesson=>lessonRow(section,module,lesson));
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
    loaded = true;
    window.renderDailyLearning();
  };
  window.loadDailyLearning();
})();
