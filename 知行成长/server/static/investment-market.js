/* Explicit-source daily data and editable, whitelist-only local conditions. */
(() => {
  'use strict';
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const today = () => new Date(Date.now()+8*3600000).toISOString().slice(0,10);
  async function api(path,body,key) {
    const response=await fetch('/api/investments/'+path,{credentials:'same-origin',
      method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Copilot-Request':'1',...(key?{'Idempotency-Key':key}:{})},
      ...(body?{body:JSON.stringify(body)}:{})});
    const result=await response.json();
    if(!response.ok)throw new Error(result.message || '请求失败，请稍后重试。');
    return result;
  }
  function dialog(title,html) {
    const d=document.createElement('dialog');d.className='inv-dialog';
    d.innerHTML=`<h3>${esc(title)}</h3>${html}<p role="alert" data-error></p><button class="btn" type="button" data-close>关闭</button>`;
    document.body.append(d);d.addEventListener('close',()=>d.remove(),{once:true});
    d.querySelector('[data-close]').onclick=()=>d.close();d.showModal();return d;
  }
  function instruments(items) {
    return items.filter(i=>i.kind!=='fund').map(i=>`<option value="${esc(i.id)}">${esc(i.name)} · ${esc(i.code)}</option>`).join('');
  }
  async function sources() {
    const d=dialog('行情与查询来源','<p>正在读取来源目录…</p>');
    try {
      const result=await api('data-sources');
      if(!d.isConnected)return;
      const section=document.createElement('section');
      section.innerHTML='<p>接口适配、账号实际权限与外部网站查询分别标注。请在各服务官网核对当前覆盖和使用范围。</p>'+result.sources.map(s=>`<article class="inv-record"><h4><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a></h4><p>${esc(({adapter_ready:'已有适配，实际权限待核验',planned:'候选来源，尚未接入',external:'外部查询入口'})[s.status])}</p><p>${esc(s.scope)}</p></article>`).join('');
      d.querySelector('p').replaceWith(section);
    } catch(error){d.querySelector('[data-error]').textContent=error.message;}
  }
  function data(context) {
    const d=dialog('添加盘后行情',`<p>先添加股票或ETF标的。日线用于盘后研究，不代表实时价格或可成交状态。</p>
      <form class="inv-form"><label>行情标的<select name="instrument_id" required>${instruments(context.instruments)}</select></label>
      <label>接入方式<select name="mode"><option value="csv">导入日线CSV（无需接口权限）</option><option value="tushare">Tushare Pro（使用本人权限）</option></select></label>
      <div data-csv class="inv-form"><label>来源说明<input name="source_label" maxlength="100" placeholder="例如：本人从数据服务导出"></label>
      <label>日线CSV文件<input type="file" accept=".csv,text/csv" data-file></label>
      <label>日线CSV<textarea name="text" rows="7" placeholder="date,open,high,low,close,volume,amount"></textarea></label>
      <label>原成交量单位<select name="volume_unit"><option value="shares">股 / ETF份</option><option value="lots">手（按100股/份转换）</option></select></label>
      <label>原成交额单位<select name="amount_unit"><option value="cny">元</option><option value="thousand_cny">千元</option></select></label>
      <button class="btn" type="button" data-template>下载日线模板</button></div>
      <div data-provider class="inv-form" hidden><label>开始日期<input type="date" name="start_date" value="${today()}"></label>
      <label>结束日期<input type="date" name="end_date" value="${today()}"></label>
      <label>日历依据<select name="calendar_mode"><option value="public_reference">公开日历参考（覆盖内不请求trade_cal）</option><option value="provider">供应商日历（需trade_cal权限）</option></select></label><label>Tushare Token<input type="password" name="token" autocomplete="off" spellcheck="false"></label>
      <p>最多90个日历日。凭证仅用于本次请求；权限不足会停止，不会自动购买或重试。</p></div>
      <label class="inv-choice"><input name="ack" type="checkbox" required>我已核对资料使用范围；CSV为未复权日线，量额单位与选择一致。</label>
      <button class="btn" type="submit">保存行情与研究证据</button></form><div data-result role="status"></div>`);
    const form=d.querySelector('form');let requestKey=crypto.randomUUID();
    form.oninput=()=>{requestKey=crypto.randomUUID();};
    form.elements.mode.onchange=()=>{
      d.querySelector('[data-csv]').hidden=form.elements.mode.value!=='csv';
      d.querySelector('[data-provider]').hidden=form.elements.mode.value!=='tushare';
    };
    d.querySelector('[data-file]').onchange=async event=>{
      try {const file=event.target.files[0];if(!file)return;if(file.size>250000)throw new Error('CSV文件不能超过250KB。');form.elements.text.value=await file.text();requestKey=crypto.randomUUID();}
      catch(error){d.querySelector('[data-error]').textContent=error.message;}
    };
    d.querySelector('[data-template]').onclick=()=>{
      const url=URL.createObjectURL(new Blob(['date,open,high,low,close,volume,amount\n'],{type:'text/csv'}));
      const link=document.createElement('a');link.href=url;link.download='daily-history-template.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    form.onsubmit=async event=>{
      event.preventDefault();const values=Object.fromEntries(new FormData(form));
      const submit=form.querySelector('[type=submit]');const controls=[...form.elements];controls.forEach(c=>c.disabled=true);d.querySelector('[data-error]').textContent='';
      try {
        const base={instrument_id:values.instrument_id,account_id:context.accountId || null};
        const body=values.mode==='csv'?{...base,text:values.text,source_label:values.source_label,volume_unit:values.volume_unit,amount_unit:values.amount_unit,use_confirmed:values.ack==='on'}:
          {...base,start_date:values.start_date,end_date:values.end_date,token:values.token,calendar_mode:values.calendar_mode,licensed_use_confirmed:values.ack==='on'};
        const result=await api(values.mode==='csv'?'market/import':'provider/daily',body,requestKey);
        form.elements.token.value='';
        d.querySelector('[data-result]').textContent=`已保存 ${result.bars.length} 条日线及研究证据。最后数据日 ${result.bars.at(-1)?.date || '无有效行情'}；来源 ${result.declared_source || result.provider}。`;
        submit.textContent='行情已保存';await context.refresh();
      } catch(error){d.querySelector('[data-error]').textContent=error.message;submit.disabled=false;}
      finally {controls.forEach(c=>c.disabled=false);}
    };
  }
  function screen() {
    const fields=[['close','收盘价'],['close_change_pct','相邻有效记录收盘变化%'],['turnover_cny','成交额（元）'],['volume_ratio_5','最近成交量 / 前5条均量'],['price_above_ma20','收盘高于MA20'],['name','名称'],['market','市场'],['kind','品种']];
    const d=dialog('本地行情条件筛选',`<p>仅筛选本账号已保存行情的标的。可使用外部查询入口补充全市场查找，再导入候选标的。</p>
      <form class="inv-form"><label>数据截至日期<input name="as_of" type="date" value="${today()}" required></label>
      <label>条件关系<select name="combine"><option value="all">满足全部条件</option><option value="any">满足任一条件</option></select></label>
      <div data-conditions></div><button class="btn" type="button" data-add>添加筛选条件</button>
      <label>排序<select name="sort_by"><option value="turnover_cny">成交额从高到低</option><option value="close_change_pct">收盘变化从高到低</option><option value="close">收盘价从高到低</option><option value="volume_ratio_5">成交量比值从高到低</option></select></label>
      <button class="btn" type="submit">执行本地筛选</button></form><div data-results aria-live="polite"></div>`);
    const form=d.querySelector('form');const rows=d.querySelector('[data-conditions]');
    function add() {
      if(rows.children.length>=10)return;
      const row=document.createElement('fieldset');row.className='inv-form';
      row.innerHTML=`<legend>条件</legend><label>字段<select data-field>${fields.map(([v,t])=>`<option value="${v}">${t}</option>`).join('')}</select></label>
        <label>比较<select data-op></select></label><label>条件值<input data-value value="0" maxlength="100" required></label><button type="button" class="btn">移除此条件</button>`;
      row.querySelector('button').onclick=()=>row.remove();
      const field=row.querySelector('[data-field]'),op=row.querySelector('[data-op]'),value=row.querySelector('[data-value]');
      field.onchange=()=>{
        const text=['name','market','kind'].includes(field.value),bool=field.value==='price_above_ma20';
        const ops=text?[['eq','等于'],['ne','不等于'],['contains','包含']]:bool?[['eq','等于'],['ne','不等于']]:[['gte','大于等于'],['gt','大于'],['lte','小于等于'],['lt','小于'],['eq','等于'],['ne','不等于']];
        op.innerHTML=ops.map(([v,t])=>`<option value="${v}">${t}</option>`).join('');
        value.value=bool?'true':text?'':'0';value.placeholder=bool?'true / false':field.value==='market'?'SSE / SZSE / BSE':field.value==='kind'?'stock / etf':'填写阈值';
      };field.onchange();rows.append(row);
    }
    add();d.querySelector('[data-add]').onclick=add;
    form.onsubmit=async event=>{
      event.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try {
        const values=Object.fromEntries(new FormData(form));
        const conditions=[...rows.children].map(r=>({field:r.querySelector('[data-field]').value,op:r.querySelector('[data-op]').value,value:r.querySelector('[data-value]').value}));
        const result=await api('screen',{...values,conditions});
        d.querySelector('[data-results]').innerHTML=`<h4>本地覆盖 ${result.universe_count} 个标的 · 命中 ${result.total} 个</h4><p>数据不足未判定：${result.unresolved} 个。最多显示100条。</p>${result.items.map(i=>`<article class="inv-record"><h4>${esc(i.name)} · ${esc(i.code)}</h4><p>收盘 ${esc(i.values.close)} · 成交额 ${esc(i.values.turnover_cny)} 元</p><p>数据日 ${esc(i.data_date)} · 来源 ${esc(i.provider)}</p></article>`).join('')}${result.limitations.map(t=>`<p class="inv-muted">${esc(t)}</p>`).join('')}`;
        d.querySelector('[data-error]').textContent='';
      }catch(error){d.querySelector('[data-error]').textContent=error.message;}
      finally{submit.disabled=false;}
    };
  }
  function pathImport(context) {
    if(!context.accountId)throw new Error('请先选择投资账户。');
    const d=dialog('导入持有路径',`<p>仅作事后路径复盘，不是实时或回测。接收沪深股票/ETF普通竞价的一分钟未复权OHLC，最多2000条/250KB。</p>
      <form class="inv-form"><label>路径标的<select aria-label="路径标的" name="instrument_id" required>${instruments(context.instruments.filter(i=>['SSE','SZSE'].includes(i.market)))}</select></label>
      <label>路径来源说明<input name="source_label" maxlength="100" required></label><label>路径核对备注<textarea name="source_note" maxlength="2000"></textarea></label>
      <label>分钟CSV文件<input type="file" accept=".csv,text/csv" data-path-file></label><label>分钟路径CSV<textarea name="text" rows="6" required placeholder="start,open,high,low,close,volume,amount"></textarea></label>
      <p>start须含时区，例如2026-10-27T10:00:00+08:00。该行从10:00:00起，到10:01:00前结束；不把日线高低点当持有期间极值。</p>
      <label>路径成交量单位<select aria-label="路径成交量单位" name="volume_unit"><option value="shares">股/份</option><option value="lots100">手（100股/份）</option></select></label>
      <label>路径成交额单位<select aria-label="路径成交额单位" name="amount_unit"><option value="cny">元</option><option value="thousand_cny">千元</option></select></label>
      <label><input name="ack" type="checkbox" required>我已核对用途、未复权口径和一分钟区间定义</label><button type="submit" class="btn">保存分钟路径</button></form><p role="status" data-path-result></p>`);
    const form=d.querySelector('form');let key=crypto.randomUUID();form.oninput=()=>key=crypto.randomUUID();
    d.querySelector('[data-path-file]').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>250000)throw new Error('文件不能超过250KB。');form.elements.text.value=await file.text();key=crypto.randomUUID();}catch(error){d.querySelector('[data-error]').textContent=error.message;}};
    form.onsubmit=async event=>{
      event.preventDefault();const submit=form.querySelector('button');submit.disabled=true;
      try {
        const values=Object.fromEntries(new FormData(form));
        const result=await api('paths/import',{account_id:context.accountId,instrument_id:values.instrument_id,text:values.text,
          source_label:values.source_label,source_note:values.source_note,volume_unit:values.volume_unit,amount_unit:values.amount_unit,
          price_basis:'unadjusted',use_confirmed:values.ack==='on'},key);
        if(!d.isConnected)return;d.querySelector('[data-path-result]').textContent=`已保存 ${result.bars.length} 条分钟路径；进入完整交易链的路径复盘查看。原始单位与来源哈希保留，未独立核验来源。`;
        d.querySelector('[data-error]').textContent='';await context.refresh();
      }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
      finally{submit.disabled=false;}
    };
  }

  async function replay(context) {
    const d=dialog('持有路径复盘与回放','<p>正在查找本人导入路径…</p>');
    try {
      const result=await api('paths?'+new URLSearchParams({account_id:context.accountId,instrument_id:context.instrumentId}));
      if(!d.isConnected)return;
      const section=document.createElement('section');section.innerHTML=`<p>显示当前账户前50份相符路径（共 ${result.total} 份）。仅使用实际持有分钟和当时剩余数量；不是模拟成交或行情实时播放。</p><form class="inv-form"><label>选择分钟路径<select aria-label="选择分钟路径" name="path_id" required>${result.items.map(p=>`<option value="${esc(p.id)}">${esc(p.source_label)} · ${esc(p.created_at)}</option>`).join('')}</select></label><label>回放截至时间（留空为当前）<input type="datetime-local" name="cutoff" step="1"></label><button class="btn" type="submit" ${result.total?'':'disabled'}>核对持有路径</button></form><div data-replay-results aria-live="polite"></div>`;
      d.querySelector('p').replaceWith(section);const form=section.querySelector('form');
      form.onsubmit=async event=>{
        event.preventDefault();const button=form.querySelector('button');button.disabled=true;
        try {
          const query=new URLSearchParams({path_id:form.elements.path_id.value});const cutoff=form.elements.cutoff.value;
          if(cutoff)query.set('cutoff',(cutoff.length===16?cutoff+':00':cutoff)+'+08:00');
          const result=await api(`accounts/${encodeURIComponent(context.accountId)}/campaigns/${encodeURIComponent(context.campaignId)}/replay?`+query);
          if(!d.isConnected)return;
          const target=section.querySelector('[data-replay-results]'),show=value=>value==null?'未知':esc(value);
          target.innerHTML=`<h4>${result.status==='complete_declared_path'?'所声明范围内路径完整':'路径缺失或尚未核验'}</h4><p>完整MAE ${show(result.mae_cash)} 元 · 完整MFE ${show(result.mfe_cash)} 元</p><p>已观察边界：${show(result.observed_mae_cash)} 至 ${show(result.observed_mfe_cash)} 元；不能替代缺段的完整极值。</p><p>有效分钟 ${result.coverage.usable_minutes} / ${show(result.coverage.expected_minutes)} · 缺失 ${show(result.coverage.missing_minutes)} · 边界不确定 ${result.coverage.boundary_minutes}</p><p>成交与路径冲突 ${result.fact_conflict_count} 项</p><p>截至时点实际净已实现 ${show(result.actual_net_realized)} · ${result.open_at_cutoff?'仍有开放仓位':'截至时点已平仓'}</p><label>已覆盖分钟回放<input type="range" min="0" max="${Math.max(0,result.rows.length-1)}" step="1" value="0" data-replay-slider ${result.rows.length?'':'disabled'}></label><div data-minute-detail></div><details><summary>公式与限制</summary><p>${esc(result.formula)}</p>${result.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}<p>路径哈希 ${esc(result.path_hash)}<br>账本哈希 ${esc(result.ledger_hash)}</p></details>`;
          const slider=target.querySelector('[data-replay-slider]'),detail=target.querySelector('[data-minute-detail]');
          const render=()=>{const row=result.rows[Number(slider.value)];detail.innerHTML=row?`<p>第 ${Number(slider.value)+1} / ${result.rows.length} 条已覆盖分钟；缺段不插值。</p><p>${esc(row.start)} 至 ${esc(row.end)}</p><dl><dt>当时剩余数量</dt><dd>${esc(row.quantity)}</dd><dt>当时剩余成本</dt><dd>${show(row.cost)}</dd><dt>分钟低 / 高</dt><dd>${esc(row.low)} / ${esc(row.high)}</dd><dt>标记净结果下 / 上界</dt><dd>${show(row.lower_pnl)} / ${show(row.upper_pnl)}</dd></dl>`:'<p>没有可用持有分钟，不能按整日日线极值补齐。</p>';};
          slider.oninput=render;render();d.querySelector('[data-error]').textContent='';
        }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
        finally{button.disabled=false;}
      };
    }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
  }
  const conditionLabels={not_started:'尚未开始',expired:'已过期',rule_conflict:'规则冲突',rules_unknown:'规则未覆盖',rules_expired:'核对资料已过期',calendar_unknown:'日历缺失',closed_session:'休市',outside_session:'普通竞价时段外',trading_status_unknown:'交易状态未核实',missing_quote:'尚无已到达价格',future_quote:'未来价格',stale:'价格过期或断流',no_trades:'本分钟无成交',sell_rule_unknown:'回转机制未知',invalid_buy_session:'假设买入日休市',sell_delay:'未满足假设可卖间隔',not_met:'价格条件未满足',duplicate_suppressed:'本日重复提示已抑制',matched:'满足声明的价格条件'};
  function renderConditionResult(target,result) {
    target.innerHTML=`<h4>离线演练结果 · 条件满足 ${result.matched_count} 次</h4><p>${esc(result.rule_snapshot.title)} · 分钟收盘${result.rule_snapshot.op==='gte'?'大于等于':'小于等于'} ${esc(result.rule_snapshot.threshold)} · ${esc(result.rule_snapshot.valid_from)} 至 ${esc(result.rule_snapshot.valid_until)}</p><p>模拟页面提示 ${result.page_candidate_count} 条 · 实际发送通知 0 条</p><p>这只是价格条件线索，未核对真实可卖数量、资金或委托成交。</p><p>${Object.entries(result.status_counts).map(([k,v])=>`${esc(conditionLabels[k] || k)} ${v}`).join(' · ')}</p><details><summary>查看演练时序（前100条，共${result.rows.length}条）</summary>${result.rows.slice(0,100).map(r=>`<article class="inv-record"><p>${esc(r.at)} · ${esc(conditionLabels[r.status] || r.status)}</p><p>资料时点 ${esc(r.quote_as_of || '无')} · 声明收盘 ${esc(r.price || '未知')}${r.page_candidate?' · 模拟页面提示':''}</p></article>`).join('')}</details><details><summary>冻结依据与范围</summary><p>来源 ${esc(result.source_label)} · 路径哈希 ${esc(result.path_hash)}</p><p>核对资料版本 ${esc(result.check_snapshot.version)} · 结果哈希 ${esc(result.result_hash)}</p>${result.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}</details>`;
  }
  async function conditionDrills(context) {
    if(!context.accountId)throw new Error('请先选择投资账户。');
    const d=dialog('离线条件演练','<p>正在读取路径与核对资料…</p>');
    try {
      const [paths,checks,saved]=await Promise.all([api('paths?'+new URLSearchParams({account_id:context.accountId})),api('plan-checks?page_size=100'),api('condition-drills?'+new URLSearchParams({account_id:context.accountId}))]);
      if(!d.isConnected)return;
      const section=document.createElement('section');section.innerHTML=`<p>用已导入一分钟CSV验证价格阈值、延迟、过期和去重。不会发送通知；关闭页面后没有后台检查。路径前50份、核对资料前100份；缺少时先导入路径并保存核对资料。</p><form class="inv-form"><label>演练标题<input name="title" required maxlength="160" value="价格条件演练"></label><label>演练分钟路径<select aria-label="演练分钟路径" name="path_id" required>${paths.items.map(p=>`<option value="${esc(p.id)}">${esc(p.source_label)}</option>`).join('')}</select></label><label>演练核对资料<select aria-label="演练核对资料" name="check_id" required></select></label><label>价格关系<select aria-label="价格关系" name="op"><option value="gte">分钟收盘大于等于</option><option value="lte">分钟收盘小于等于</option></select></label><label>演练价格阈值<input name="threshold" inputmode="decimal" required></label><label>演练用途<select aria-label="演练用途" name="intent"><option value="observe">观察条件</option><option value="entry">入场条件线索</option><option value="exit">退出条件线索（假设批次）</option></select></label><label>假设买入日期（退出时填写）<input type="date" name="assumed_bought_on"></label><label>演练开始时间<input type="datetime-local" step="1" name="valid_from" required></label><label>演练到期时间<input type="datetime-local" step="1" name="valid_until" required></label><label>价格最长有效秒数<input type="number" name="max_age_seconds" min="1" max="300" value="60" required></label><label>模拟行情延迟秒数<input type="number" name="arrival_delay_seconds" min="0" max="3600" value="0" required></label><label>模拟提示范围<select aria-label="模拟提示范围" name="notification_scope"><option value="none">只记录核对结果</option><option value="page">本页模拟提示</option></select></label><label>额外检查时点（每行一个，含时区，最多10个）<textarea name="probes" placeholder="2026-10-27T12:00:00+08:00"></textarea></label><label><input name="ack" type="checkbox" required>我确认这是离线演练，不判断当前可成交或计划自由文本</label><button class="btn" type="submit" disabled>保存并运行演练</button></form><div data-condition-result aria-live="polite"></div><h4>已保留演练（前50项）</h4><div data-condition-history></div>`;
      d.querySelector('p').replaceWith(section);const form=section.querySelector('form'),button=form.querySelector('[type=submit]');let key=crypto.randomUUID(),generation=0;
      function renderHistory(items) {
        section.querySelector('[data-condition-history]').innerHTML=items.map(x=>`<article class="inv-record"><p>${esc(x.rule_snapshot.title)} · ${esc(x.created_at)}</p><button type="button" class="btn" data-drill-id="${esc(x.id)}">查看已存演练</button></article>`).join('') || '<p>尚无演练记录。</p>';
        section.querySelectorAll('[data-drill-id]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const result=await api('condition-drills/'+encodeURIComponent(b.dataset.drillId));if(d.isConnected)renderConditionResult(section.querySelector('[data-condition-result]'),result);}catch(e){if(d.isConnected)d.querySelector('[data-error]').textContent=e.message;}finally{b.disabled=false;}});
      }
      renderHistory(saved.items);form.oninput=()=>key=crypto.randomUUID();
      form.elements.path_id.onchange=async()=>{
        const selected=paths.items.find(p=>p.id===form.elements.path_id.value),ticket=++generation;button.disabled=true;
        form.elements.check_id.innerHTML=checks.items.filter(c=>c.instrument_id===selected?.instrument_id).map(c=>`<option value="${esc(c.id)}">${esc(c.quote_as_of)} · ${esc(c.source_note)}</option>`).join('');
        if(!selected)return;
        try{const path=await api('paths/'+encodeURIComponent(selected.id));if(!d.isConnected || ticket!==generation)return;
          form.elements.valid_from.value=path.bars[0].start.slice(0,19);form.elements.valid_until.value=path.bars.at(-1).end.slice(0,19);
          form.elements.threshold.value=path.bars[0].close;form.elements.assumed_bought_on.value=path.bars[0].start.slice(0,10);key=crypto.randomUUID();
          button.disabled=!form.elements.check_id.value;d.querySelector('[data-error]').textContent=button.disabled?'该路径证券还没有本人核对资料，请先保存。':'';
        }catch(e){if(d.isConnected && ticket===generation)d.querySelector('[data-error]').textContent=e.message;}
      };
      form.onsubmit=async event=>{
        event.preventDefault();const values=Object.fromEntries(new FormData(form)),controls=[...form.elements];controls.forEach(c=>c.disabled=true);
        const local=value=>(value.length===16?value+':00':value)+'+08:00';
        try{const result=await api('condition-drills',{account_id:context.accountId,path_id:values.path_id,check_id:values.check_id,title:values.title,
          op:values.op,threshold:values.threshold,intent:values.intent,assumed_bought_on:values.intent==='exit'?values.assumed_bought_on:null,
          valid_from:local(values.valid_from),valid_until:local(values.valid_until),max_age_seconds:Number(values.max_age_seconds),arrival_delay_seconds:Number(values.arrival_delay_seconds),
          notification_scope:values.notification_scope,probe_at:values.probes.split(/\r?\n/).map(t=>t.trim()).filter(Boolean),acknowledged:values.ack==='on'},key);
          if(!d.isConnected)return;renderConditionResult(section.querySelector('[data-condition-result]'),result);d.querySelector('[data-error]').textContent='';
          const history=await api('condition-drills?'+new URLSearchParams({account_id:context.accountId}));if(d.isConnected)renderHistory(history.items);
        }catch(e){if(d.isConnected)d.querySelector('[data-error]').textContent=e.message;}
        finally{controls.forEach(c=>c.disabled=false);}
      };
      await form.elements.path_id.onchange();
    }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
  }
  async function experiments(context) {
    const d=dialog('前向试验列表','<p>正在读取前向观察试验…</p>');
    async function render() {
      try {
        const result=await api('experiments?'+new URLSearchParams({account_id:context.accountId}));if(!d.isConnected)return;
        let section=d.querySelector('[data-trials]');if(!section){section=document.createElement('section');section.dataset.trials='';d.querySelector('p').replaceWith(section);}
        section.innerHTML=`<p>当前显示前50项（共 ${result.total} 项）。事前登记仅冻结观察方案；失败/停止的试验保留，不修改策略或资金限制。</p>${result.items.map(x=>`<article class="inv-record"><h4>${esc(x.title)}</h4><p>${esc(({draft:'草稿，尚未登记',registered:'已事前登记',finished:'已保留结项评价'})[x.state])} · 版本 ${x.version}</p><p>${esc(x.start_at)} 至 ${esc(x.end_at)}</p><p>目标样本 ${x.sample_target}；达到数量不代表方法有效。</p>${x.decision?`<p>本人决定：${esc(({retain:'保留观察',reject:'拒绝原假设',inconclusive:'无法判定',stopped:'停止试验'})[x.decision])} · ${esc(x.decision_reason)}</p>`:''}<div class="inv-actions">${x.state==='draft'?`<button type="button" class="btn" data-trial-edit="${esc(x.id)}">修改试验草稿</button><button type="button" class="btn" data-trial-register="${esc(x.id)}" data-version="${x.version}">事前登记并冻结</button>`:`<button type="button" class="btn" data-trial-evaluate="${esc(x.id)}">查看前向评价</button>`}</div></article>`).join('') || '<p>先从工作台新建前向试验，补齐假设、反例和成本。</p>'}`;
        section.querySelectorAll('[data-trial-edit]').forEach(b=>b.onclick=()=>{d.close();context.onEdit(b.dataset.trialEdit);});
        section.querySelectorAll('[data-trial-register]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api(`experiments/${encodeURIComponent(b.dataset.trialRegister)}/register`,{version:Number(b.dataset.version),state:'confirmed'},crypto.randomUUID());await render();}catch(error){d.querySelector('[data-error]').textContent=error.message;b.disabled=false;}});
        section.querySelectorAll('[data-trial-evaluate]').forEach(b=>b.onclick=()=>{d.close();experimentEvaluation(b.dataset.trialEvaluate,context);});
      }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
    }
    await render();
  }

  async function experimentEvaluation(id,context) {
    const d=dialog('前向观察评价','<p>正在按事前协议核对当前账本…</p>');
    try {
      const [record,result]=await Promise.all([api('experiments/'+encodeURIComponent(id)),api('experiments/'+encodeURIComponent(id)+'/evaluation')]);
      if(!d.isConnected)return;const show=v=>v==null?'未知':esc(v),section=document.createElement('section');
      section.innerHTML=`<h4>${esc(record.title)}</h4><p>平仓 ${result.closed_count} · 开放仓位 ${result.open_count} · 已知净结果 ${result.known_net_count} · 未知 ${result.unknown_net_count}</p><p>成交净结果 ${show(result.net_realized)} · 胜率比例 ${show(result.win_rate)} · 净期望 ${show(result.net_expectancy)}</p><p>${result.small_sample?'探索性小样本；':''}不证明方法有优势，也不会扩大风险。</p>${result.archived_evaluation_outdated?'<p class="inv-notice">当前账本与结项时不同；原评价保留，没有自动重写本人决定。</p>':''}<h4>额外成本压力（假设）</h4>${result.cost_sensitivity.map(x=>`<p>每条完整交易额外 ${esc(x.additional_cost_per_roundtrip)} 元：合计 ${show(x.net_after_extra_cost)}</p>`).join('')}<h4>自动纳入的交易链（含亏损）</h4>${result.observations.map(x=>`<p>${esc(x.opened_at)} · ${x.state==='closed'?'已平仓':'开放'} · 净结果 ${show(x.net_realized)} · ${x.pre_recorded_plan?'有有效事前计划':'事前计划未核验合规'}</p>`).join('') || '<p>尚无相符策略版本的实际样本。</p>'}<p>其他/混合或无冻结版本 ${result.excluded.length} 条，未隐去为零。</p><details><summary>冻结协议与限制</summary><pre>${esc(JSON.stringify(record.protocol_snapshot,null,2))}</pre>${result.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}</details>${record.state==='registered'?'<form class="inv-form"><label>本人试验决定<select aria-label="本人试验决定" name="decision"><option value="inconclusive">无法判定</option><option value="reject">拒绝原假设</option><option value="retain">保留观察</option><option value="stopped">停止试验</option></select></label><label>试验评价依据<textarea name="reason" maxlength="3000" required></textarea></label><p>期间未结束仅能停止；结项冻结当前评价，未来更正不会覆盖。</p><button class="btn" type="submit">保存结项评价</button></form>':'<p>该试验已结项；需要改变参数时另建未来试验。</p>'}<p data-finish-status role="status"></p>`;
      d.querySelector('p').replaceWith(section);
      const form=section.querySelector('form');if(form)form.onsubmit=async event=>{
        event.preventDefault();const b=form.querySelector('button');b.disabled=true;
        try {await api(`experiments/${encodeURIComponent(id)}/finish`,{version:record.version,decision:form.elements.decision.value,reason:form.elements.reason.value,evaluation_hash:result.evaluation_hash},crypto.randomUUID());form.remove();section.querySelector('[data-finish-status]').textContent='已保留本人决定与评价快照；不改变策略或风险。';}
        catch(error){d.querySelector('[data-error]').textContent=error.message;b.disabled=false;}
      };
    }catch(error){if(d.isConnected)d.querySelector('[data-error]').textContent=error.message;}
  }
  window.InvestmentMarket={sources,data,screen,pathImport,replay,experiments,conditionDrills};
})();
