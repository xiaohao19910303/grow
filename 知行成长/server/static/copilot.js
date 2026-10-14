/* Local-only Markdown subset: construct DOM nodes, never interpret input as HTML. */
(() => {
  'use strict';
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function inline(parent, text) {
    const pattern = /(\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`)/g;
    let last = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(last, match.index)));
      if (match[2]) {
        let url;
        try { url = new URL(match[3]); } catch (_) { url = null; }
        if (url && ['https:', 'http:'].includes(url.protocol)) {
          const a = el('a', match[2]);
          a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer';
          parent.append(a);
        } else parent.append(document.createTextNode(match[2]));
      } else parent.append(el(match[4] ? 'strong' : 'code', match[4] || match[5]));
      last = match.index + match[0].length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function markdown(container, text) {
    container.replaceChildren();
    let target = container, code = null, table = null, list = null;
    for (const line of text.split('\n')) {
      if (line.startsWith('```')) {
        if (code) code = null;
        else { code = el('pre'); target.append(code); }
        continue;
      }
      if (code) { code.append(document.createTextNode(line + '\n')); continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) {
        table = list = null;
        if (heading[2].includes('参考分析')) {
          const details = el('details'); details.append(el('summary', '完成练习后，展开参考分析与自查'));
          container.append(details); target = details;
        } else if (target !== container && !heading[2].includes('自查')) target = container;
        const node = el('h' + Math.min(heading[1].length + 1, 6)); inline(node, heading[2]); target.append(node);
      } else if (/^\s*\|/.test(line)) {
        if (/^\s*\|[\s|:\-]+$/.test(line)) continue;
        if (!table) { table = el('table'); target.append(table); }
        const tr = el('tr');
        line.trim().replace(/^\||\|$/g, '').split('|').forEach(s => {
          const td = el('td'); inline(td, s.trim()); tr.append(td);
        });
        table.append(tr);
      } else if (/^\s*(?:[-*]|\d+\.)\s/.test(line)) {
        table = null;
        if (!list) { list = el('ul'); target.append(list); }
        const li = el('li'); inline(li, line.replace(/^\s*(?:[-*]|\d+\.)\s/, '')); list.append(li);
      } else {
        table = list = null;
        if (/^\s*---+\s*$/.test(line)) target.append(el('hr'));
        else if (line.trim()) {
          const p = el(line.startsWith('> ') ? 'blockquote' : 'p');
          inline(p, line.replace(/^> /, '')); target.append(p);
        }
      }
    }
  }
  const root = document.getElementById('view-copilot');
  const status = el('p', '', 'cp-status'); status.setAttribute('role', 'status');
  const heading = el('div', undefined, 'section');
  heading.append(el('h2', '学习副驾驶'), el('p', '认知与通识 · 课程生成和本人学习完成分开记录。', 'desc'), status);
  const controls = el('div', undefined, 'cp-actions');
  const summary = el('div', undefined, 'cp-summary');
  const blockers = el('ul', undefined, 'cp-blockers');
  const history = el('div'); const drafts = el('div'); const operations = el('div');
  const reader = el('section', undefined, 'section cp-reader'); reader.hidden = true;
  const editor = el('section', undefined, 'section'); editor.hidden = true;
  const bodyInput = el('textarea'); bodyInput.rows = 18; bodyInput.setAttribute('aria-label', '课程Markdown正文');
  const sourceInput = el('textarea'); sourceInput.rows = 8; sourceInput.setAttribute('aria-label', '资料Markdown摘要');
  const preview = el('div', undefined, 'cp-reader');
  let currentTask, currentDraft, aborter, generatingId, dirty = false, publicationKey;
  const readerStatus = el('p', '', 'reader-status'); readerStatus.setAttribute('role','status');
  const message = text => { status.textContent = text; readerStatus.textContent = text; };
  const uid = () => crypto.randomUUID();
  async function request(path, method = 'GET', body) {
    const headers = { 'X-Copilot-Request': '1' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch('/api/copilot' + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || data.detail || '请求失败，请检查本地服务。');
    return data;
  }
  function button(label, action, parent, cls = 'btn') {
    const b = el('button', label, cls);
    b.type = 'button'; b.onclick = async () => {
      b.disabled = true;
      try { await action(); } catch (e) { message(String(e.message)); }
      finally { b.disabled = false; }
    };
    parent.append(b); return b;
  }
  const refresh = button('刷新课程', () => load(), controls);
  button('确认安全写入时段', async () => {
    if (!confirm('请先暂停自动课程任务和其他编辑器的写入。确认接下来10分钟不会有其他程序修改课程或学习记录？此按钮不会替你暂停自动任务。')) return;
    const result = await request('/writer-session', 'POST', {confirmed: true});
    message('本次写入确认有效至 ' + result.expires_at); await load(false);
  }, controls);
  button('查看与确认主题', async () => {
    root.classList.add('reading-mode');
    const plan = await request('/plan'); reader.hidden = false; reader.replaceChildren(el('h3', '主题规划 · ' + plan.path));
    plan.items.forEach(x => reader.append(el('p', `第${x.lesson_no}课 · ${x.topic} · ${x.kind} · ${x.confirmed ? '已确认' : '待确认'}`)));
    button('确认以上主题', async () => {
      await request('/plan/confirm', 'POST', {hash: plan.hash, lessons: plan.items.map(x => x.lesson_no)});
      message('主题已确认。'); await load(false);
    }, reader);
    reader.append(el('p', '后续主题请在课程主题规划.md中补齐；格式见知行成长/README.md。'));
  }, controls);
  button('完整备份', async () => {
    const result = await request('/backups', 'POST', {});
    message('备份已保存：' + result.path + '。恢复步骤见使用说明。');
  }, controls);
  button('阅读设置', () => showReadingSettings(), controls);
  const generateButton = button('生成下一课草稿', () => generate(), controls, 'btn primary');
  heading.append(controls, summary, blockers);
  const management=el('details',undefined,'section cp-management');
  management.open=true; management.append(el('summary','课程管理与保存帮助'),heading);
  heading.classList.remove('section');
  root.append(reader,management,editor);
  const histories = el('section', undefined, 'section');
  histories.append(el('h3', '课程与学习记录'), history, el('h3', '草稿'), drafts, el('h3', '待恢复操作'), operations);
  management.append(histories); histories.classList.remove('section');

  function showDraft(d) {
    currentDraft = d; publicationKey = uid(); dirty = false; editor.hidden = false;
    editor.replaceChildren(el('h3', `第${d.lesson_no}课草稿 · ${d.status}`));
    bodyInput.value = d.content; sourceInput.value = d.sources;
    editor.append(el('label', '课程正文'), bodyInput, el('label', '本地资料摘要'), sourceInput);
    const actions = el('div', undefined, 'cp-actions');
    button('预览当前编辑', () => { markdown(preview, bodyInput.value + '\n\n## 参考资料\n' + sourceInput.value); }, actions);
    button('保存草稿修改', async () => {
      const saved = await request('/drafts/' + d.id, 'PATCH', {version: currentDraft.version, content: bodyInput.value, sources: sourceInput.value});
      showDraft(saved); message(saved.errors.length ? saved.errors.join('；') : '草稿已保存并通过结构校验。');
    }, actions);
    const publishButton = button('确认保存为正式课程', async () => {
      if (dirty) throw new Error('请先保存草稿修改，再发布。');
      const result = await request('/publications', 'POST', {draft_id: d.id, version: currentDraft.version, key: publicationKey});
      message(result.status === 'done' ? '课程与资料已保存；学习状态仍待本人记录。' : '保存尚未完成，请查看待恢复操作。');
      if (result.status === 'done') editor.hidden = true;
      await load(false);
    }, actions, 'btn primary');
    publishButton.disabled = d.status !== 'ready';
    button('重新生成（可能新增费用）', async () => {
      if (confirm('重新生成将创建新的模型调用，可能产生新增费用。继续？')) await generate(d.lesson_no);
    }, actions);
    editor.append(actions, preview);
    markdown(preview, d.content + '\n\n## 参考资料\n' + d.sources);
    editor.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
  bodyInput.oninput = sourceInput.oninput = () => { dirty = true; };
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  let readingRequest=0, activeTracker=null;
  const stopReading=()=>{if(activeTracker){activeTracker.stopTimer();window.removeEventListener('scroll',activeTracker.scrollHandler);activeTracker=null;}};
  async function read(number) {
    const requestId=++readingRequest;
    stopReading();root.classList.add('reading-mode');management.open=false;
    reader.hidden=false;reader.replaceChildren();
    button('返回学习列表',()=>returnFromLesson(),reader);
    readerStatus.textContent='正在读取课程…';reader.append(readerStatus);
    const lesson = await request('/lessons/' + number);
    if(requestId!==readingRequest)return;
    root.classList.add('reading-mode');management.open=false;
    reader.hidden = false; reader.replaceChildren();
    button('返回学习列表', () => returnFromLesson(), reader);
    readerStatus.textContent='';reader.append(readerStatus);
    const actions = el('div', undefined, 'cp-actions');
    button('课程正文', () => markdown(content, lesson.content), actions);
    button('参考资料', () => markdown(content, lesson.sources), actions);
    const feedbackKey = uid();
    const completion = button(lesson.learning_state === 'completed' ? '撤销本人完成记录' : '本人确认学完', async () => {
      const result = await request(`/lessons/${number}/learning-state`, 'PATCH', {
        state: lesson.learning_state === 'completed' ? 'unknown' : 'completed', version: lesson.version, key: feedbackKey
      });
      if (result.status !== 'done') { message('学习状态待恢复，请查看保存操作。'); return; }
      await read(number); await load(false); message('学习记录已更新，个人笔记保留。');
    }, actions);
    completion.disabled = !lesson.complete;
    const content = el('div', undefined, 'cp-reader');
    reader.append(content,actions,readerStatus); markdown(content, lesson.content);
    button('保存需要帮助',()=>{management.open=true;management.scrollIntoView({block:'start'});},actions);

    // 添加阅读监控和复盘区（仅在未完成时）
    if (lesson.learning_state !== 'completed') {
      const readingTracker = new ReadingTracker(number, lesson.version, feedbackKey);
      activeTracker=readingTracker;
      reader.append(readingTracker.createProgressBar());
      reader.append(readingTracker.createReviewSection());
      readingTracker.start();
    }

    reader.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  // 阅读监控类
  class ReadingTracker {
    constructor(lessonId, lessonVersion, feedbackKey) {
      this.lessonId = lessonId;
      this.lessonVersion = lessonVersion;
      this.feedbackKey = feedbackKey;

      // Load settings from localStorage
      const settings = JSON.parse(localStorage.getItem('copilot-reading-settings') || '{}');
      const defaults = {
        requireScrollToBottom: true,
        requireMinTime: 180,
        defaultCompletionMode: 'summary'
      };
      this.settings = {...defaults, ...settings};

      this.scrolledToBottom = false;
      this.timeSpent = 0;
      this.threshold = this.settings.requireMinTime;
      this.timer = null;
      this.completed = false;
      this.progressBar = null;
      this.timeDisplay = null;
      this.reviewSection = null;
    }

    start() {
      this.bindScrollListener();
      this.startTimer();
    }

    createProgressBar() {
      const container = el('div', undefined, 'cp-reading-progress');
      const bar = el('div', undefined, 'cp-progress-bar');
      this.progressBar = el('div', undefined, 'cp-progress-fill');
      bar.append(this.progressBar);

      const info = el('div', undefined, 'cp-reading-info');
      this.timeDisplay = el('span', '⏱️ 0:00 / 3:00');
      info.append(this.timeDisplay);

      container.append(bar, info);
      return container;
    }

    createReviewSection() {
      this.reviewSection = el('div', undefined, 'cp-review-section');
      this.reviewSection.hidden = true;

      this.reviewSection.append(el('h3', '💭 学习完成确认'));
      this.reviewSection.append(el('p', '选择一种方式完成本课学习：', 'desc'));

      // 选项卡
      const tabs = el('div', undefined, 'cp-review-tabs');
      const tabReview = button('回答复盘问题', () => this.showTab('review'), tabs, 'cp-tab active');
      const tabSummary = button('写学习总结', () => this.showTab('summary'), tabs, 'cp-tab');
      const tabQuick = button('快速完成', () => this.showTab('quick'), tabs, 'cp-tab');
      this.reviewSection.append(tabs);

      // 复盘问题 - will be populated dynamically
      const reviewContent = el('div', undefined, 'cp-tab-content');
      reviewContent.id = 'cp-tab-review';
      reviewContent.append(el('p', '请用 1-2 句话回答以下问题：'));
      this.questionsContainer = el('div', undefined, 'cp-questions');
      reviewContent.append(this.questionsContainer);

      this.reviewSubmitBtn = button('提交复盘，标记完成', async () => {
        const answers = [];
        this.questionsContainer.querySelectorAll('.cp-question').forEach((q, index) => {
          const textarea = q.querySelector('textarea');
          answers.push({
            question_id: index + 1,
            answer: textarea.value
          });
        });
        await this.submitReview(answers);
      }, reviewContent, 'btn primary');

      // 学习总结
      const summaryContent = el('div', undefined, 'cp-tab-content');
      summaryContent.id = 'cp-tab-summary';
      summaryContent.hidden = true;
      const summaryInput = el('textarea');
      summaryInput.rows = 4;
      summaryInput.placeholder = '用 50-100 字总结：今天我学到了什么？有什么启发？';
      summaryContent.append(summaryInput);
      button('提交总结，标记完成', async () => {
        await this.submitSummary(summaryInput.value);
      }, summaryContent, 'btn primary');

      // 快速完成
      const quickContent = el('div', undefined, 'cp-tab-content');
      quickContent.id = 'cp-tab-quick';
      quickContent.hidden = true;
      quickContent.append(el('p', '确认已认真学习本课内容？'));
      button('确认完成', async () => {
        await this.quickComplete();
      }, quickContent, 'btn primary');

      this.reviewSection.append(reviewContent, summaryContent, quickContent);

      // Load questions asynchronously
      this.loadQuestions();

      return this.reviewSection;
    }

    async loadQuestions() {
      try {
        const result = await request(`/lessons/${this.lessonId}/review-questions`);
        const questions = result.questions || [
          {question_id: 1, question_text: '本课的核心概念是什么？用自己的话解释。'},
          {question_id: 2, question_text: '你能举一个生活中的例子吗？'}
        ];

        this.questionsContainer.replaceChildren();
        questions.forEach((q, index) => {
          const qDiv = el('div', undefined, 'cp-question');
          qDiv.append(el('p', `${index + 1}. ${q.question_text}`));
          const textarea = el('textarea');
          textarea.rows = 2;
          textarea.placeholder = '用 1-2 句话回答...';
          qDiv.append(textarea);
          this.questionsContainer.append(qDiv);
        });
      } catch (e) {
        // Fallback to default questions
        this.questionsContainer.replaceChildren();
        const defaultQuestions = [
          '本课的核心概念是什么？用自己的话解释。',
          '你能举一个生活中的例子吗？'
        ];
        defaultQuestions.forEach((text, index) => {
          const qDiv = el('div', undefined, 'cp-question');
          qDiv.append(el('p', `${index + 1}. ${text}`));
          const textarea = el('textarea');
          textarea.rows = 2;
          textarea.placeholder = '用 1-2 句话回答...';
          qDiv.append(textarea);
          this.questionsContainer.append(qDiv);
        });
      }
    }

    showTab(tabName) {
      this.reviewSection.querySelectorAll('.cp-tab-content').forEach(el => el.hidden = true);
      this.reviewSection.querySelectorAll('.cp-tab').forEach(el => el.classList.remove('active'));
      document.getElementById('cp-tab-' + tabName).hidden = false;
      event.target.classList.add('active');
    }

    bindScrollListener() {
      this.scrollHandler = () => {
        const scrolled = (window.scrollY + window.innerHeight) >= document.body.scrollHeight - 100;
        if (scrolled && !this.scrolledToBottom) {
          this.scrolledToBottom = true;
          this.checkCompletion();
        }
      };
      window.addEventListener('scroll', this.scrollHandler);
    }

    startTimer() {
      this.timer = setInterval(() => {
        if (!this.completed && currentTab==='copilot' && root.classList.contains('reading-mode') && !document.hidden) {
          this.timeSpent++;
          this.updateUI();
          this.checkCompletion();
        }
      }, 1000);
    }

    checkCompletion() {
      const scrollMet = !this.settings.requireScrollToBottom || this.scrolledToBottom;
      const timeMet = this.timeSpent >= this.threshold;

      if (scrollMet && timeMet && !this.completed) {
        this.showReviewSection();
        this.completed = true;
        this.stopTimer();
      }
    }

    showReviewSection() {
      this.reviewSection.hidden = false;
      this.reviewSection.scrollIntoView({behavior: 'smooth', block: 'start'});
    }

    updateUI() {
      const minutes = Math.floor(this.timeSpent / 60);
      const seconds = this.timeSpent % 60;
      const thresholdMinutes = Math.floor(this.threshold / 60);
      const thresholdSeconds = this.threshold % 60;
      this.timeDisplay.textContent = `⏱️ ${minutes}:${seconds.toString().padStart(2, '0')} / ${thresholdMinutes}:${thresholdSeconds.toString().padStart(2, '0')}`;

      const progress = Math.min(this.timeSpent / this.threshold * 100, 100);
      this.progressBar.style.width = `${progress}%`;
    }

    stopTimer() {
      if (this.timer) {
        clearInterval(this.timer);
      }
      if (this.scrollHandler) {
        window.removeEventListener('scroll', this.scrollHandler);
      }
    }

    async submitReview(answers) {
      try {
        const result = await request(`/lessons/${this.lessonId}/review`, 'POST', {
          answers: answers,
          time_spent_seconds: this.timeSpent,
          version: this.lessonVersion,
          key: this.feedbackKey
        });
        message('✅ 已提交复盘，标记为学习完成！');
        await load(false);
        this.reviewSection.hidden = true;
      } catch (e) {
        message('提交失败：' + e.message);
      }
    }

    async submitSummary(summary) {
      try {
        const result = await request(`/lessons/${this.lessonId}/summary`, 'POST', {
          summary: summary,
          time_spent_seconds: this.timeSpent,
          version: this.lessonVersion,
          key: this.feedbackKey
        });
        message('✅ 已提交总结，标记为学习完成！');
        await load(false);
        this.reviewSection.hidden = true;
      } catch (e) {
        message('提交失败：' + e.message);
      }
    }

    async quickComplete() {
      try {
        const result = await request(`/lessons/${this.lessonId}/complete`, 'POST', {
          time_spent_seconds: this.timeSpent,
          version: this.lessonVersion,
          key: this.feedbackKey
        });
        message('✅ 已标记为学习完成！');
        await load(false);
        this.reviewSection.hidden = true;
      } catch (e) {
        message('提交失败：' + e.message);
      }
    }
  }
  async function load(clear = true) {
    if (clear) message('正在读取本地课程…');
    try {
      currentTask = await request('/today-task');
      summary.textContent = `已生成 ${currentTask.generated_count}/168　本人确认完成 ${currentTask.completed_count}/168　待本人记录 ${currentTask.pending_learning_lessons.length} 课`;
      blockers.replaceChildren();
      const reasons = [...currentTask.blockers.map(x => x.message)];
      if (currentTask.generation_unavailable) reasons.push(currentTask.generation_unavailable);
      if (!currentTask.writer_coordinated) reasons.push('正式保存或学习反馈前，请确认其他程序已暂停写入。阅读不受影响。');
      reasons.forEach(s => blockers.append(el('li', s)));
      generateButton.disabled = !currentTask.can_generate || !!aborter;
      generateButton.textContent = currentTask.next_generation_lesson ? `生成第${currentTask.next_generation_lesson}课草稿` : '第一轮已生成完毕';
      history.replaceChildren();
      currentTask.lessons.forEach(item => {
        const row = el('div', undefined, 'cp-row');
        row.append(el('span', `第${String(item.lesson_no).padStart(3, '0')}课 · ${item.topic} · ${item.learning_label}${item.complete ? '' : ' · 待修复'}`));
        button('阅读', () => {rememberLearningOrigin();return read(item.lesson_no);}, row); history.append(row);
      });
      const [saved, pending] = await Promise.all([request('/drafts'), request('/operations')]);
      drafts.replaceChildren();
      saved.items.forEach(item => {
        const row = el('div', undefined, 'cp-row'); row.append(el('span', `第${item.lesson_no}课 · ${item.status} · ${item.updated_at}`));
        button('恢复查看', async () => {
          if (dirty && !confirm('当前有未保存编辑，确定放弃并读取其他草稿？')) return;
          showDraft(await request('/drafts/' + item.id));
        }, row); drafts.append(row);
      });
      if (!saved.items.length) drafts.append(el('p', '还没有草稿。', 'desc'));
      operations.replaceChildren();
      pending.items.forEach(item => {
        const row = el('div', undefined, 'cp-row'); row.append(el('span', item.id + ' · ' + item.status + ' · ' + (item.error || '')));
        button('检查并恢复', async () => {
          const result = await request(`/operations/${item.id}/recover`, 'POST', {});
          message('恢复结果：' + result.status); await load(false);
        }, row); operations.append(row);
      });
      if (clear) message('本地课程已刷新；生成数量不等于学习完成数量。');
    } catch (e) { message(String(e.message)); }
  }
  async function generate(number) {
    if (aborter) return;
    if (dirty && !confirm('当前有未保存编辑，确定放弃并生成新草稿？')) return;
    const n = number || currentTask.next_generation_lesson;
    // Retain key until a concrete attempt ID is received; uncertain retries must not bill twice.
    const keyName = 'copilot-generation-' + n;
    const key = sessionStorage.getItem(keyName) || uid(); sessionStorage.setItem(keyName, key);
    aborter = new AbortController(); generatingId = null; generateButton.disabled = true;
    const live = el('pre', '', 'cp-stream'); editor.hidden = false; editor.replaceChildren(el('h3', '正在生成草稿'), live);
    const cancel = button('取消生成', async () => {
      if (generatingId) await request('/generations/' + generatingId + '/cancel', 'POST', {});
      aborter?.abort();
    }, editor);
    let terminal = false;
    try {
      const response = await fetch('/api/copilot/generations', {method: 'POST', signal: aborter.signal,
        headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'},
        body: JSON.stringify({lesson_no: n, key})});
      if (!response.ok) {
        const error = await response.json(); sessionStorage.removeItem(keyName);
        throw new Error(error.message || '无法开始生成。');
      }
      const stream = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      function parse() {
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const lines = block.split('\n'); const name = lines.find(s => s.startsWith('event:'))?.slice(6).trim();
          const payload = lines.filter(s => s.startsWith('data:')).map(s => s.slice(5).trimStart()).join('\n');
          if (!payload) continue;
          const data = JSON.parse(payload);
          if (name === 'started') { generatingId = data.id; sessionStorage.removeItem(keyName); }
          if (name === 'delta') live.append(document.createTextNode(data.text));
          if (name === 'completed') { terminal = true; showDraft(data); message('草稿生成完成，请检查后确认保存。'); }
          if (name === 'failed' || name === 'cancelled') { terminal = true; message(data.message || '生成已取消；未完成草稿不能发布。'); }
        }
      }
      for (;;) {
        const {done, value} = await stream.read();
        buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
        buffer = buffer.replace(/\r\n/g, '\n'); parse(); if (done) break;
      }
      if (!terminal) message('连接中断，请从草稿列表恢复查看。');
    } catch (e) { message(e.name === 'AbortError' ? '已取消；可从草稿列表查看。' : String(e.message)); }
    finally { aborter = null; cancel.disabled = true; await load(false); }
  }
  window.loadCopilot = load;
  window.renderLearningMarkdown = markdown;
  window.leaveCopilot = () => {++readingRequest;stopReading();};
  window.showCopilotManagement = () => { ++readingRequest;stopReading();root.classList.remove('reading-mode');management.open=true; };
  window.openCopilotLesson = async number => {
    goTab('copilot', {reading:true});
    try { await read(number); } catch (error) { message(error.message); }
  };

  // 阅读设置
  function showReadingSettings() {
    root.classList.add('reading-mode');
    const settings = JSON.parse(localStorage.getItem('copilot-reading-settings') || '{}');
    const defaults = {
      requireScrollToBottom: true,
      requireMinTime: 180,
      defaultCompletionMode: 'summary'
    };
    const current = {...defaults, ...settings};

    reader.hidden = false;
    reader.replaceChildren();
    reader.append(el('h3', '💭 阅读与完成设置'));
    reader.append(el('p', '自定义阅读完成条件和默认完成方式。', 'desc'));

    const form = el('div', undefined, 'cp-settings-form');

    // 滚动到底部
    const scrollOption = el('label', undefined, 'cp-setting-option');
    const scrollCheckbox = el('input');
    scrollCheckbox.type = 'checkbox';
    scrollCheckbox.checked = current.requireScrollToBottom;
    scrollCheckbox.onchange = () => { current.requireScrollToBottom = scrollCheckbox.checked; };
    scrollOption.append(scrollCheckbox, el('span', '要求滚动到底部'));
    form.append(scrollOption);

    // 最少停留时间
    const timeOption = el('div', undefined, 'cp-setting-option');
    timeOption.append(el('label', '最少停留时间（秒）：'));
    const timeInput = el('input');
    timeInput.type = 'number';
    timeInput.min = '0';
    timeInput.max = '600';
    timeInput.value = current.requireMinTime;
    timeInput.onchange = () => { current.requireMinTime = parseInt(timeInput.value) || 180; };
    timeOption.append(timeInput);
    form.append(timeOption);

    // 默认完成方式
    const modeOption = el('div', undefined, 'cp-setting-option');
    modeOption.append(el('label', '默认完成方式：'));
    const modeSelect = el('select');
    ['review', 'summary', 'quick'].forEach(mode => {
      const option = el('option', mode === 'review' ? '回答复盘问题' : mode === 'summary' ? '写学习总结' : '快速完成');
      option.value = mode;
      if (mode === current.defaultCompletionMode) option.selected = true;
      modeSelect.append(option);
    });
    modeSelect.onchange = () => { current.defaultCompletionMode = modeSelect.value; };
    modeOption.append(modeSelect);
    form.append(modeOption);

    // 保存按钮
    button('保存设置', () => {
      localStorage.setItem('copilot-reading-settings', JSON.stringify(current));
      message('设置已保存！');
      reader.hidden = true;
    }, form, 'btn primary');

    // 恢复默认
    button('恢复默认', () => {
      localStorage.removeItem('copilot-reading-settings');
      message('已恢复默认设置！');
      showReadingSettings();
    }, form);

    reader.append(form);
    reader.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
})();
