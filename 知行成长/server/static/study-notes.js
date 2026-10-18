/* Shared notes and inline exercises for all course readers. */
(() => {
  let current = null;
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  function mount({parent, content, kind, course, version, seedNotes = ''}) {
    const userId = window.Account?.user?.id;
    if (!userId) throw Error('登录信息尚未就绪，请重新打开课程。');
    const form = node('section', undefined, 'section study-notes-form');
    form.append(node('h3', '学习笔记与练习'));
    const status = node('p', '正在读取暂存…', 'desc');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    form.append(status);
    const label = node('label', '学习笔记（可选）');
    const input = node('textarea'); input.rows = 5; input.maxLength = 10000;
    input.placeholder = '随时记下收获或疑问，可暂存后下次继续，不必标记学完。';
    label.append(input); form.append(label);
    const actions = node('div', undefined, 'day-actions'); form.append(actions);
    const save = node('button', '暂存笔记与答案', 'btn'); save.type = 'button'; actions.append(save);
    parent.append(form);
    const fields = new Map();
    let timer = null, storage;
    try { storage = localStorage; } catch (_) { /* Cloud saves remain available. */ }
    const session = new window.StudyDraftSession({kind, course: String(course), version, userId, seedNotes, storage,
      fetch: (url, options) => fetch(url, options), onStatus: text => { status.textContent = text; showConflict(); },
      onChange: value => {
        if (input.value !== value.notes) input.value = value.notes;
        for (const [key, field] of fields) if (field.value !== (value.answers[key] || '')) field.value = value.answers[key] || '';
        // Preserve access to answers whose question was changed in a newer course version.
        for (const key of Object.keys(value.answers)) if (!fields.has(key)) {
          let old = form.querySelector('.previous-exercise-answers');
          if (!old) { old = node('details', undefined, 'previous-exercise-answers'); old.append(node('summary', '其他已保存的练习答案')); form.append(old); }
          answerField(old, key, key, null);
        }
      }});
    input.value = session.notes;
    const sync = () => session.save().catch(error => { status.textContent = error.message + (session.safe ? ' 输入已保留在本机。' : ' 请勿关闭页面。'); throw error; });
    function showConflict() {
      form.querySelector('.study-notes-conflict')?.remove();
      if (!session.conflict) return;
      const box = node('details', undefined, 'study-notes-conflict'); box.open = true;
      box.append(node('summary', '核对云端版本与当前输入'));
      box.append(node('p', '下方是云端内容；当前输入框仍保留本机版本。', 'desc'));
      const cloud = node('pre', session.remote ? session.remote.notes + '\n\n' + Object.entries(session.remote.answers || {}).map(([key, value]) => key + '\n' + value).join('\n\n') : '暂时无法读取云端版本。');
      box.append(cloud);
      for (const [label, action] of [
        ['重新读取云端', () => session.load()],
        ['采用云端版本', () => { if (confirm('确定采用云端版本，替换当前输入框内容？')) session.useCloud(); }],
        ['保留本机并同步', async () => { if (session.remote && confirm('已核对两个版本，确认用当前笔记和答案更新云端？')) { session.keepLocal(); await sync().catch(() => {}); } }]
      ]) { const button = node('button', label, 'btn'); button.type = 'button'; button.disabled = label !== '重新读取云端' && !session.remote; button.onclick = action; box.append(button); }
      form.append(box);
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => { sync().catch(() => {}); }, 900); };
    input.addEventListener('input', () => { session.setNotes(input.value); schedule(); });
    save.onclick = async () => { save.disabled = true; try { await sync(); } catch (_) {} finally { save.disabled = false; } };
    function answerField(target, key, prompt, after) {
      if (fields.has(key)) return;
      const wrap = node('label', '我的答案（自动暂存）', 'practice-answer');
      const field = node('textarea'); field.rows = 3; field.maxLength = 10000;
      field.setAttribute('aria-label', prompt.slice(0, 250) + ' 的答案');
      field.placeholder = '在这里填写；可中途离开，下次继续。';
      field.value = session.answers[key] || '';
      field.addEventListener('input', () => { session.setAnswer(key, field.value); schedule(); });
      wrap.append(field); fields.set(key, field);
      if (after) after.after(wrap); else target.append(wrap);
    }
    function exercises(container) {
      const headings = [...container.querySelectorAll('h2,h3,h4,h5,h6')];
      let excluded = 0;
      for (const heading of headings) {
        const level = Number(heading.tagName.slice(1));
        if (excluded && level <= excluded) excluded = 0;
        if (/参考答案|参考分析|答案解析|答案与解释/.test(heading.textContent)) excluded = level;
        if (excluded || heading.closest('details')) continue;
        const section = [];
        let next = heading.nextElementSibling;
        while (next && (!/^H[2-6]$/.test(next.tagName) || Number(next.tagName.slice(1)) > level)) {
          section.push(next); next = next.nextElementSibling;
        }
        const title = heading.textContent.trim().slice(0, 180);
        const isQuestion = /练习|阅读理解|引导问题|思考题|思考问题|复盘问题/.test(title) ||
          (/[？?]$/.test(title) && section.some(element => /写在这里/.test(element.textContent)));
        if (!isQuestion) continue;
        if (section.some(element => /^H[2-6]$/.test(element.tagName) && /练习|阅读理解|思考题/.test(element.textContent))) continue;
        const questions = /练习\s*[\d一二三四五六七八九十]/.test(title) ? [] : section.filter(element => element.tagName === 'UL' || element.tagName === 'OL').flatMap(list => [...list.children]).filter(question => question.textContent.trim());
        // Completion checklists are progress reminders, rather than answer prompts.
        if (questions.length && questions.every(question => /^\s*\[[ xX]\]/.test(question.textContent))) continue;
        if (questions.length && questions.length <= 10) {
          questions.forEach((question, index) => answerField(question, title + ':' + (index + 1), title + ' · ' + question.textContent, null));
        } else {
          answerField(container, title + ':1', title, section.at(-1) || heading);
        }
      }
    }
    exercises(content);
    const controller = {session, input, form, actions, status, fields,
      bind: container => { fields.clear(); form.querySelector('.previous-exercise-answers')?.remove(); exercises(container); session.onChange(session.snapshot()); },
      flush: sync,
      close: () => { clearTimeout(timer); session.persist(); if (session.dirty) sync().catch(() => {}); },
      get safe() { return session.safe; }};
    current = controller;
    controller.ready = session.load().then(ok => { if (ok && session.dirty && !session.conflict) schedule(); return ok; });
    return controller;
  }
  function beforeLeave() {
    if (!current) return true;
    current.session.persist();
    if (!current.safe && !confirm('笔记尚未同步，且浏览器无法暂存。确定放弃当前输入并离开？')) return false;
    current.close(); current = null; return true;
  }
  window.addEventListener('beforeunload', event => {
    if (current) { current.session.persist(); if (!current.safe) { event.preventDefault(); event.returnValue = ''; } }
  });
  const contentVersion = async text => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text)))].map(value => value.toString(16).padStart(2, '0')).join('');
  window.StudyNotes = {mount, beforeLeave, contentVersion};
})();
