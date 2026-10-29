/* Explicit generation only. Reloading a page resumes observation of the same job. */
(() => {
  'use strict';
  const observers = new Map();
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  async function api(module, suffix, body) {
    const response = await fetch('/api/study-materials/' + module + '/generations' + suffix, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Copilot-Request': '1'},
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.message || data.detail || '请求未完成，请重试。');
      error.status = response.status;
      throw error;
    }
    if(data.id&&data.state)trackGeneration(module,data);
    return data;
  }
  const task=(module,job)=>window.GenerationTasks?.external('study',job,{module,kind:'study-course',label:(module==='yingyu'?'英文':'表达')+'课程生成',title:'第 '+job.lesson_no+' 课草稿'});
  function trackGeneration(module,job){if(window.GenerationTasks)window.GenerationTasks.track(task(module,job));}
  function observe(module, id, listener) {
    let observer = observers.get(id);
    if (observer) { observer.listeners.add(listener); return; }
    observer = {listeners: new Set([listener]), delay: 1500};
    observers.set(id, observer);
    async function poll() {
      try {
        const job = await api(module, '/' + id);
        for (const callback of observer.listeners) if (!callback(job)) observer.listeners.delete(callback);
        if (!['queued', 'generating'].includes(job.state) || !observer.listeners.size) { observers.delete(id); return; }
        observer.delay = document.hidden ? 10000 : 1500;
      } catch (_) {
        observer.delay = Math.min(observer.delay * 2, 10000);
        for (const callback of observer.listeners) if (!callback(null)) observer.listeners.delete(callback);
        if (!observer.listeners.size) { observers.delete(id); return; }
      }
      setTimeout(poll, observer.delay);
    }
    poll();
  }
  window.renderStudyGeneration = (parent, module) => {
    if (!['yingyu', 'biaoda'].includes(module.id)) return;
    const panel = node('section', undefined, 'study-generation-panel');
    panel.style.cssText = 'margin:16px 0;padding:16px;border:1px solid var(--border);border-radius:12px;overflow-wrap:anywhere;';
    parent.append(panel);
    const storageKey = 'study-generation:' + (window.Account?.user?.id || 'current') + ':' + module.id;
    let current = module.generation;
    const nextNumber = Math.max(0, ...module.lessons.map(lesson => Number(lesson.lesson_no))) + 1;
    function control(parent, label, action, primary = false) {
      const button = node('button', label, 'btn' + (primary ? ' primary' : ''));
      button.type = 'button';
      button.onclick = async () => {
        button.disabled = true;
        try { await action(); }
        catch (error) { status.textContent = error.message; }
        finally { if (button.isConnected) button.disabled = false; }
      };
      parent.append(button);
      return button;
    }
    let status;
    function draw(job) {
      current = job;
      if(job)trackGeneration(module.id,job);
      if (job) module.generation = job;
      panel.replaceChildren(node('h4', '生成下一课'));
      if(job)window.AIEvidence?.mount(panel,'study',job.id);
      panel.append(node('p', '按课号和已学主题接续，不安排学习日期。使用你的 AI 配置，不发送个人学习笔记。', 'desc'));
      status = node('p', '', 'desc'); status.setAttribute('role', 'status'); panel.append(status);
      const actions = node('div', undefined, 'day-actions'); panel.append(actions);
      if (job && ['queued', 'generating'].includes(job.state)) {
        status.textContent = `正在生成第 ${job.lesson_no} 课…` + (job.raw ? `已收到 ${job.raw.length} 字符。` : '正在等待模型响应。');
        control(actions, '取消生成', async () => { const result = await api(module.id, '/' + job.id + '/cancel', {}); draw(result); });
        return;
      }
      if (job?.state === 'ready') {
        if (!job.content) { status.textContent = '正在读取已生成的草稿…'; return; }
        status.textContent = `第 ${job.lesson_no} 课草稿已生成，请预览后保存。`;
        const preview = node('div', undefined, 'study-course-preview');
        preview.style.cssText = 'max-height:65vh;overflow:auto;margin:12px 0;';
        panel.append(preview);
        if (job.content) window.renderLearningMarkdown(preview, job.content);
        control(actions, '保存课程并开始学习', async () => {
          const origin = panel.closest('[id^="view-"]');
          const course = await api(module.id, '/' + job.id + '/publish', {});
          status.textContent = '课程已保存到 GitHub。';
          const visible = origin && origin.style.display !== 'none';
          await window.loadDailyLearning({force:true});
          const dialog=panel.closest('dialog');
          if(dialog){dialog.close();if(goTab('library')!==false)await window.openStudyCourse(module.id,course.filename);return;}
          if (visible && origin.style.display !== 'none') await window.openStudyCourse(module.id, course.filename);
        }, true);
        control(actions, '放弃草稿', async () => { draw(await api(module.id, '/' + job.id + '/cancel', {})); });
        return;
      }
      status.textContent = job?.error || `现有课程已学完，可以生成第 ${nextNumber} 课。`;
      if (job?.state === 'failed' && job.raw) {
        const details = node('details'); details.append(node('summary', '查看已收到的内容'));
        const raw = node('pre', job.raw); raw.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;';
        details.append(raw); panel.append(details);
      }
      control(actions, job?.state === 'failed' || job?.state === 'cancelled' ? '重新生成下一课' : '生成下一课', async () => {
        const config = window.AIConfig.require();
        let key = sessionStorage.getItem(storageKey);
        if (!key || job?.state === 'failed' || job?.state === 'cancelled') {
          key = crypto.randomUUID(); sessionStorage.setItem(storageKey, key);
        }
        status.textContent = '正在提交生成请求…';
        try {
          const result = await api(module.id, '', {key, ai_config: config});
          sessionStorage.removeItem(storageKey);
          draw(result);
          watch(result);
        } catch (error) {
          if (error.status && error.status < 500) sessionStorage.removeItem(storageKey);
          throw error;
        }
      }, true);
    }
    function watch(job) {
      if (!job || !['queued', 'generating', 'ready'].includes(job.state)) return;
      if (job.state === 'ready' && job.content) return;
      observe(module.id, job.id, result => {
        if (!panel.isConnected) return false;
        if (result) draw(result);
        else status.textContent = '读取进度暂时中断，正在重连；不会重新调用模型。';
        return true;
      });
    }
    if (current?.state === 'published') current = null;
    if (current?.id) sessionStorage.removeItem(storageKey);
    draw(current);
    watch(current);
  };
  window.GenerationTasks?.register('study',{
    read:async job=>task(job.module,await api(job.module,'/'+job.ref)),
    cancel:async job=>task(job.module,await api(job.module,'/'+job.ref+'/cancel',{})),
    recover:async()=>{const response=await fetch('/api/study-materials',{cache:'no-store'});if(!response.ok)return [];const data=await response.json();return data.modules.filter(m=>m.generation).map(m=>task(m.id,m.generation));},
    open:async job=>{
      const [response,current]=await Promise.all([fetch('/api/study-materials',{cache:'no-store'}),api(job.module,'/'+job.ref)]);
      if(!response.ok)throw new Error('暂时无法读取课程，请稍后重试。');
      const data=await response.json(),module=data.modules.find(m=>m.id===job.module);
      if(!module)throw new Error('课程模块暂不可用。');
      if(current.state==='published'){if(goTab('library')===false)return false;await window.loadDailyLearning({force:true});return window.openStudyCourse(job.module,current.course.filename);}
      const dialog=node('dialog',undefined,'action-dialog');dialog.setAttribute('aria-label','课程生成预览');
      const close=node('button','关闭预览','btn');close.type='button';close.onclick=()=>dialog.close();dialog.append(close);
      document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
      window.renderStudyGeneration(dialog,{...module,generation:current});
    }
  });
})();
