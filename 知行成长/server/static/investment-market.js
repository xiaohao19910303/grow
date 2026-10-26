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
      <label>Tushare Token<input type="password" name="token" autocomplete="off" spellcheck="false"></label>
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
          {...base,start_date:values.start_date,end_date:values.end_date,token:values.token,licensed_use_confirmed:values.ack==='on'};
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
  window.InvestmentMarket={sources,data,screen};
})();
