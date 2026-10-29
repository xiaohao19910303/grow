// 课程总结页面
(() => {
  'use strict';

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    .cp-summary-header h2 { margin: 0 0 8px; font-size: 24px; }
    .cp-summary-header .desc { margin: 0 0 20px; color: var(--muted, #666); font-size: 14px; }

    /* Stats cards with icons */
    .cp-summary-stats { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .cp-summary-stats .stat-card {
      flex: 1; min-width: 140px; padding: 20px; background: var(--bg-soft, #f8f9fa);
      border: 1px solid var(--border, #e0e0e0); border-radius: 12px;
      display: flex; align-items: center; gap: 16px;
      transition: all 0.2s;
    }
    .cp-summary-stats .stat-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .cp-summary-stats .stat-icon {
      width: 48px; height: 48px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-size: 24px; background: var(--primary-soft, #e0e7ff);
    }
    .cp-summary-stats .stat-info { flex: 1; }
    .cp-summary-stats .stat-value {
      display: block; font-size: 32px; font-weight: 600;
      color: var(--primary, #2563eb); line-height: 1;
    }
    .cp-summary-stats .stat-label {
      display: block; font-size: 13px; color: var(--muted, #666); margin-top: 6px;
    }

    /* Actions with secondary buttons */
    .cp-summary-actions {
      display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap;
      align-items: center;
    }
    .cp-summary-actions .btn {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 10px 18px; font-weight: 500;
    }
    .cp-summary-actions .btn-secondary {
      background: var(--bg-soft, #f8f9fa); color: var(--text, #333);
      border: 1px solid var(--border, #e0e0e0);
    }
    .cp-summary-actions .btn-secondary:hover {
      background: var(--border, #e0e0e0);
    }

    /* Output container with progress */
    .cp-summary-output {
      margin: 20px 0; padding: 0; background: #fff;
      border: 2px solid var(--primary, #2563eb);
      border-radius: 12px; overflow: hidden;
    }
    .cp-summary-output-header {
      padding: 12px 20px; background: var(--primary-soft, #e0e7ff);
      border-bottom: 1px solid var(--border, #e0e0e0);
      display: flex; justify-content: space-between; align-items: center;
    }
    .cp-summary-output-title {
      font-weight: 600; font-size: 15px; color: var(--text, #333);
      display: flex; align-items: center; gap: 8px;
    }
    .cp-summary-output-actions {
      display: flex; gap: 8px;
    }
    .cp-summary-output-actions button {
      padding: 6px 12px; font-size: 13px; border-radius: 6px;
      background: white; border: 1px solid var(--border, #e0e0e0);
      cursor: pointer; transition: all 0.2s;
      display: inline-flex; align-items: center; gap: 4px;
    }
    .cp-summary-output-actions button:hover {
      background: var(--primary, #2563eb); color: white;
      border-color: var(--primary, #2563eb);
    }
    .cp-summary-output-content {
      padding: 20px; min-height: 200px; max-height: 600px;
      overflow-y: auto;
    }
    .cp-summary-streaming {
      white-space: pre-wrap; line-height: 1.8; font-size: 15px;
      animation: fadeIn 0.3s;
    }
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    .cp-summary-thinking {
      display: inline-flex; align-items: center; gap: 8px;
      color: var(--muted, #666); font-size: 14px;
    }
    .cp-summary-thinking-dots {
      display: inline-flex; gap: 4px;
    }
    .cp-summary-thinking-dots span {
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--primary, #2563eb);
      animation: thinking 1.4s infinite;
    }
    .cp-summary-thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
    .cp-summary-thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes thinking {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
      40% { opacity: 1; transform: scale(1); }
    }
    .cp-summary-result { white-space: pre-wrap; line-height: 1.8; font-size: 15px; }
    .cp-summary-error {
      color: #dc2626; padding: 16px 20px;
      background: #fee2e2; border-radius: 0;
      display: flex; align-items: center; gap: 8px;
    }

    /* Summary list with better cards */
    .cp-summary-list { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }
    .cp-summary-card {
      padding: 20px; background: #fff; border: 1px solid var(--border, #e0e0e0);
      border-radius: 12px; transition: all 0.2s;
    }
    .cp-summary-card:hover {
      box-shadow: 0 4px 12px rgba(0,0,0,0.08);
      transform: translateY(-2px);
    }
    .cp-summary-card-header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 12px;
    }
    .cp-summary-scope {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 12px; background: var(--primary, #2563eb);
      color: #fff; border-radius: 6px; font-size: 13px; font-weight: 500;
    }
    .cp-summary-date { font-size: 13px; color: var(--muted, #666); }
    .cp-summary-preview {
      font-size: 14px; line-height: 1.7; color: #333;
      margin: 12px 0; max-height: 120px; overflow: hidden;
      position: relative;
    }
    .cp-summary-preview::after {
      content: ''; position: absolute; bottom: 0; left: 0; right: 0;
      height: 40px; background: linear-gradient(transparent, white);
    }
    .cp-summary-card-actions {
      display: flex; gap: 8px; margin-top: 12px;
    }
    .cp-summary-card-actions button {
      padding: 6px 14px; font-size: 13px; border-radius: 6px;
      background: var(--bg-soft, #f8f9fa); border: 1px solid var(--border, #e0e0e0);
      cursor: pointer; transition: all 0.2s;
    }
    .cp-summary-card-actions button:hover {
      background: var(--primary, #2563eb); color: white;
      border-color: var(--primary, #2563eb);
    }

    /* Empty state */
    .cp-summary-empty {
      text-align: center; padding: 60px 20px;
      color: var(--muted, #666);
    }
    .cp-summary-empty-icon {
      font-size: 64px; margin-bottom: 16px; opacity: 0.3;
    }
    .cp-summary-empty-text {
      font-size: 15px; line-height: 1.6;
    }

    /* Toast notifications */
    .toast {
      position: fixed; bottom: 20px; left: 50%;
      transform: translateX(-50%) translateY(100px);
      background: #333; color: white; padding: 12px 24px;
      border-radius: 8px; font-size: 14px; z-index: 10000;
      transition: transform 0.3s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .toast.show {
      transform: translateX(-50%) translateY(0);
    }
  `;
  document.head.append(style);

  async function request(path, method, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json', 'x-copilot-request': '1' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.json()).message || '请求失败');
    return r.json();
  }

  const masteryLabels = {
    fully_understood: '😎 完全掌握',
    basically_understood: '🙂 基本懂了',
    partially_understood: '😐 一知半解',
    not_understood: '😟 没学明白'
  };

  let currentSummaryContent = '';
  let summaryTask=null,advancedTask=null;
  let selectedSummaryResult=null,summaryDisplayRequest=0;
  let backgroundReady=Promise.resolve();
  const activeTask=task=>task&&['queued','generating'].includes(task.state);
  const backgroundTask=job=>window.GenerationTasks.external('course-background',job,{label:job.kind==='advanced'?'进阶课程生成':'整课总结生成',title:'认知与通识课程'});
  async function jobAPI(path,body){
    const response=await fetch('/api/copilot'+path,{method:body===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json','X-Copilot-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw new Error(data.message||'生成任务暂不可用。');return data;
  }

  async function loadSummaryPage() {
    const root = document.getElementById('summaryRoot');
    if (!root) return;
    root.replaceChildren();

    // Header with stats
    const header = document.createElement('div');
    header.className = 'cp-summary-header';
    header.innerHTML = `
      <h2>课程总结</h2>
      <p class="desc">基于已完成课程和用户反馈，生成整门课程的复盘总结。</p>
      <div id="summaryStats" class="cp-summary-stats"></div>
    `;
    root.append(header);

    // Load stats
    let completedCount = 0;
    let feedbackCount = 0;
    let summaryCount = 0;
    try {
      const [lessons, summaries] = await Promise.all([
        request('/api/copilot/lessons?state=completed', 'GET'),
        request('/api/copilot/summaries', 'GET')
      ]);
      const items = lessons.items || [];
      completedCount = items.length;
      summaryCount = (summaries.items || []).length;

      // Check feedback for each lesson - only show count if there are lessons
      if (items.length > 0) {
        const feedbackChecks = await Promise.all(
          items.map(l => request(`/api/copilot/lessons/${l.lesson_no}/feedback`, 'GET').catch(() => null))
        );
        feedbackCount = feedbackChecks.filter(fb => fb && fb.mastery_level).length;
      }

      const statsEl = header.querySelector('#summaryStats');
      statsEl.innerHTML = `
        <div class="stat-card">
          <div class="stat-icon">✓</div>
          <div class="stat-info">
            <span class="stat-value">${completedCount}</span>
            <span class="stat-label">已完成课程</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">💬</div>
          <div class="stat-info">
            <span class="stat-value">${feedbackCount}</span>
            <span class="stat-label">已提交反馈</span>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">📝</div>
          <div class="stat-info">
            <span class="stat-value">${summaryCount}</span>
            <span class="stat-label">已有总结</span>
          </div>
        </div>
      `;
    } catch (e) {
      // Stats optional
    }

    // Generate button - disable if no completed lessons
    const actions = document.createElement('div');
    actions.className = 'cp-summary-actions';
    if (completedCount === 0) {
      actions.innerHTML = `
        <p class="desc" style="margin:0">暂无已完成课程，请先完成一些课程再生成总结。</p>
      `;
    } else {
      actions.innerHTML = `
        <button class="btn primary" id="btnGenerateSummary">生成整课总结</button>
      `;
    }
    root.append(actions);

    // Streaming output area with header
    const output = document.createElement('div');
    output.id = 'summaryOutput';
    output.className = 'cp-summary-output';
    output.style.display = 'none';
    output.innerHTML = `
      <div class="cp-summary-output-header">
        <div class="cp-summary-output-title">
          <span>📄</span>
          <span>生成结果</span>
        </div>
        <div class="cp-summary-output-actions" id="outputActions" style="display:none">
          <button onclick="copySummaryToClipboard()" title="复制到剪贴板">📋 复制</button>
          <button onclick="exportSummaryAsMarkdown()" title="导出为Markdown">📥 导出</button>
        </div>
      </div>
      <div class="cp-summary-output-content" id="outputContent"></div>
    `;
    root.append(output);

    // After output: advanced generation button
    const postActions = document.createElement('div');
    postActions.id = 'summaryPostActions';
    postActions.className = 'cp-summary-actions';
    postActions.style.display = 'none';
    postActions.innerHTML = `
      <button class="btn" id="btnGenerateAdvanced">基于总结生成进阶课程</button>
    `;
    root.append(postActions);

    // Previous summaries list
    const listHeader = document.createElement('h3');
    listHeader.textContent = '历史总结';
    listHeader.style.marginTop = '32px';
    root.append(listHeader);

    const list = document.createElement('div');
    list.id = 'summaryList';
    list.className = 'cp-summary-list';
    root.append(list);

    // Load existing summaries
    loadSummaryList();

    // Bind generate button
    const generateButton = document.getElementById('btnGenerateSummary');
    if (generateButton) generateButton.onclick = generateSummary;
    const advancedButton=document.getElementById('btnGenerateAdvanced');if(advancedButton)advancedButton.onclick=generateAdvanced;
    if(activeTask(summaryTask)&&generateButton){generateButton.disabled=true;generateButton.textContent='总结生成中，请在任务中心查看';}
    if(activeTask(advancedTask)){const button=document.getElementById('btnGenerateAdvanced');if(button){button.disabled=true;button.textContent='进阶课程生成中';}}
    (selectedSummaryResult?viewSummary(selectedSummaryResult):resumeBackground()).catch(error=>showToast(error.message));
  }

  async function loadSummaryList() {
    const list = document.getElementById('summaryList');
    if (!list) return;
    list.replaceChildren();

    try {
      const data = await request('/api/copilot/summaries', 'GET');
      const items = data.items || [];

      if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'cp-summary-empty';
        empty.innerHTML = `
          <div class="cp-summary-empty-icon">📝</div>
          <div class="cp-summary-empty-text">
            暂无历史总结<br>
            点击上方按钮生成第一份总结
          </div>
        `;
        list.append(empty);
        return;
      }

      for (const item of items) {
        const card = document.createElement('div');
        card.className = 'cp-summary-card';
        const createdAt = item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : '-';
        const preview = item.content ? (item.content.length > 200 ? item.content.slice(0, 200) + '...' : item.content) : '';
        const scopeIcon = item.scope === 'full_course' ? '📚' : '📖';
        const scopeText = item.scope === 'full_course' ? '整课总结' : '单课总结';
        card.innerHTML = `
          <div class="cp-summary-card-header">
            <span class="cp-summary-scope">${scopeIcon} ${scopeText}</span>
            <span class="cp-summary-date">${createdAt}</span>
          </div>
          <div class="cp-summary-preview">${preview.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>
          <div class="cp-summary-card-actions">
            <button data-action="view" data-id="${item.id}">📖 查看</button>
            <button data-action="copy" data-content="${encodeURIComponent(item.content || '')}">📋 复制</button>
            <button data-action="export" data-content="${encodeURIComponent(item.content || '')}" data-date="${createdAt}">📥 导出</button>
          </div>
        `;
        list.append(card);
      }

      list.querySelectorAll('button[data-action="view"]').forEach(btn => {
        btn.onclick = () => viewSummary(parseInt(btn.dataset.id));
      });
      list.querySelectorAll('button[data-action="copy"]').forEach(btn => {
        btn.onclick = () => {
          const content = decodeURIComponent(btn.dataset.content);
          copyToClipboard(content);
        };
      });
      list.querySelectorAll('button[data-action="export"]').forEach(btn => {
        btn.onclick = () => {
          const content = decodeURIComponent(btn.dataset.content);
          const date = btn.dataset.date;
          exportAsMarkdown(content, date);
        };
      });
    } catch (e) {
      list.append(Object.assign(document.createElement('p'), { textContent: '加载失败：' + e.message }));
    }
  }

  async function observeBackground(job){
    const kind=job.kind,output=document.getElementById('outputContent');
    if(kind==='advanced')advancedTask=job;else summaryTask=job;
    const root=document.getElementById('view-summary');
    const displayRequest=summaryDisplayRequest;
    if(!selectedSummaryResult)output.dataset.backgroundJob=job.id;
    const current=()=>!selectedSummaryResult&&displayRequest===summaryDisplayRequest&&root.style.display!=='none'&&document.getElementById('outputContent')===output&&output.dataset.backgroundJob===job.id;
    const draw=progress=>{
      if(kind==='advanced')advancedTask=progress;else summaryTask=progress;
      if(!current())return;
      document.getElementById('summaryOutput').style.display='';
      const body=document.createElement('pre');body.className='cp-summary-streaming';body.textContent=progress.raw||'已提交后台，可切换页面或刷新，任务会继续。';output.replaceChildren(body);
    };
    try{
      await window.GenerationTasks.wait(backgroundTask(job),draw);
      const done=await jobAPI('/background-jobs/'+job.id);
      if(kind==='advanced')advancedTask=done;else summaryTask=done;
      if(!current())return;
      if(kind==='summary')await viewSummary(done.result_id);
      else{const note=document.createElement('p');note.textContent='进阶课程已保存为草稿。';const button=document.createElement('button');button.className='btn primary';button.textContent='打开进阶课程草稿';button.onclick=()=>window.openGeneratedCopilotDraft(done.draft_id);output.replaceChildren(note,button);}
      loadSummaryList();
    }catch(error){if(current())output.textContent=error.message+' 已保留进度，可在任务中心查看。';}
    finally{if(current()){const button=document.getElementById(kind==='summary'?'btnGenerateSummary':'btnGenerateAdvanced');if(button){button.disabled=false;button.textContent=kind==='summary'?'生成整课总结':'基于总结生成进阶课程';}}}
  }
  async function startBackground(kind,values){
    await backgroundReady;
    if(activeTask(kind==='summary'?summaryTask:advancedTask))return;
    selectedSummaryResult=null;++summaryDisplayRequest;
    const config=window.AIConfig.require(),keyName='background-summary:'+window.Account.user.id+':'+kind;
    let key=sessionStorage.getItem(keyName);if(!key){key=crypto.randomUUID();sessionStorage.setItem(keyName,key);}
    const button=document.getElementById(kind==='summary'?'btnGenerateSummary':'btnGenerateAdvanced');if(button)button.disabled=true;
    try{
      const job=await jobAPI(kind==='summary'?'/summaries/generate':'/summaries/generate-advanced',{module:'renzhi',key,ai_config:config,...values});
      sessionStorage.removeItem(keyName);window.GenerationTasks.track(backgroundTask(job));
      return observeBackground(job);
    }catch(error){showToast(error.message+' 原请求编号已保留，重试不会重复生成。');if(button)button.disabled=false;}
  }
  async function generateSummary(){try{return await startBackground('summary',{scope:'full_course'});}catch(error){showToast(error.message);}}
  async function resumeBackground(){
    const target=document.getElementById('outputContent');await backgroundReady;
    const data=await jobAPI('/background-jobs');if(selectedSummaryResult||target!==document.getElementById('outputContent'))return;
    const job=data.items.find(item=>['queued','generating'].includes(item.state));if(job)observeBackground(job);
  }

  async function viewSummary(summaryId) {
    selectedSummaryResult=summaryId;const turn=++summaryDisplayRequest;
    try {
      const data = await request(`/api/copilot/summaries/${summaryId}`, 'GET');
      if(turn!==summaryDisplayRequest||selectedSummaryResult!==summaryId)return;
      const output = document.getElementById('summaryOutput');
      const outputActions = document.getElementById('outputActions');
      const outputContent = document.getElementById('outputContent');
      output.style.display = '';
      outputContent.innerHTML = `<div class="cp-summary-result">${data.content.replace(/</g, '&lt;').replace(/\n/g, '<br>')}</div>`;
      outputActions.style.display = '';
      window.AIEvidence?.mount(outputContent,'course-summary',summaryId);
      currentSummaryContent = data.content;
      const generate=document.getElementById('btnGenerateSummary');if(generate&&!activeTask(summaryTask)){generate.disabled=false;generate.textContent='生成整课总结';}
      document.getElementById('summaryPostActions').style.display = '';
    } catch (e) {
      alert('加载失败：' + e.message);
    }
  }

  async function generateAdvanced(){try{if(currentSummaryContent)return await startBackground('advanced',{summary_content:currentSummaryContent});}catch(error){showToast(error.message);}}

  // Helper functions for copy and export
  function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
      showToast('已复制到剪贴板');
    }).catch(() => {
      showToast('复制失败，请手动复制');
    });
  }

  function copySummaryToClipboard() {
    if (currentSummaryContent) {
      copyToClipboard(currentSummaryContent);
    }
  }

  function exportAsMarkdown(content, date) {
    const filename = `课程总结-${date.replace(/[\/\s:]/g, '-')}.md`;
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('已导出为Markdown文件');
  }

  function exportSummaryAsMarkdown() {
    if (currentSummaryContent) {
      const now = new Date().toLocaleString('zh-CN');
      exportAsMarkdown(currentSummaryContent, now);
    }
  }

  function showToast(message) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.append(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2000);
  }

  // Auto-load when tab is shown
  const observer = new MutationObserver(() => {
    const view = document.getElementById('view-summary');
    if (view && view.style.display !== 'none' && !view.dataset.loaded) {
      view.dataset.loaded = '1';
      loadSummaryPage();
    }
    if (view && view.style.display === 'none') {
      delete view.dataset.loaded;
    }
  });

  if (document.getElementById('view-summary')) {
    observer.observe(document.getElementById('view-summary'), { attributes: true, attributeFilter: ['style'] });
  }

  window.loadSummaryPage = loadSummaryPage;
  backgroundReady=window.GenerationTasks?.register('course-background',{
    read:async job=>backgroundTask(await jobAPI('/background-jobs/'+job.ref)),
    cancel:async job=>backgroundTask(await jobAPI('/background-jobs/'+job.ref+'/cancel',{})),
    recover:async()=>{const data=await jobAPI('/background-jobs');return data.items.filter((job,index)=>['queued','generating'].includes(job.state)||index<5).map(backgroundTask);},
    open:async job=>{
      if(job.draft_id)return window.openGeneratedCopilotDraft(job.draft_id);
      selectedSummaryResult=job.result_id||null;++summaryDisplayRequest;
      if(goTab('summary')===false)return false;await loadSummaryPage();
      if(job.result_id)return viewSummary(job.result_id);
      return observeBackground(await jobAPI('/background-jobs/'+job.ref));
    }
  })||Promise.resolve();
  // Keep links to results created before durable background jobs were introduced.
  window.GenerationTasks?.register('summary-stream',{
    read:async job=>({...job,state:'interrupted',error:'这是旧连接记录，请在历史总结或课程管理核对结果。'}),
    open:async job=>{if(job.draft_id)return window.openGeneratedCopilotDraft(job.draft_id);if(goTab('summary')===false)return false;await loadSummaryPage();if(job.result_id)return viewSummary(job.result_id);}
  });
})();
