/* 浏览器筛选计算：十进制转 BigInt 分数，阈值与排序不使用浮点近似。 */
(() => {
  'use strict';
  const algorithm='browser-screen-rational-v1';
  function decimal(value){
    const text=String(value),m=/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(text);
    if(!m||text.length>100||Math.abs(Number(m[4]||0))>100)throw Error('数值格式或精度超出浏览器筛选范围。');
    const scale=(m[3]||'').length-Number(m[4]||0),n=BigInt((m[2]+(m[3]||''))||'0')*(m[1]==='-'?-1n:1n);
    return scale>=0?{n,d:10n**BigInt(scale)}:{n:n*10n**BigInt(-scale),d:1n};
  }
  const add=(a,b)=>({n:a.n*b.d+b.n*a.d,d:a.d*b.d});
  const sub=(a,b)=>({n:a.n*b.d-b.n*a.d,d:a.d*b.d});
  const mul=(a,b)=>({n:a.n*b.n,d:a.d*b.d});
  function div(a,b){if(b.n===0n)return null;const sign=b.n<0n?-1n:1n;return {n:a.n*b.d*sign,d:a.d*b.n*sign};}
  const cmp=(a,b)=>{const n=a.n*b.d-b.n*a.d;return n<0n?-1:n>0n?1:0;};
  const sum=values=>values.reduce((a,b)=>add(a,decimal(b)),decimal('0'));
  function display(r){
    if(r==null)return null;
    const negative=r.n<0n,n=negative?-r.n:r.n,scale=10n**28n,v=n*scale/r.d;
    const fraction=(v%scale).toString().padStart(28,'0').replace(/0+$/,'');
    return (negative&&v!==0n?'-':'')+(v/scale)+(fraction?'.'+fraction:'');
  }
  function metrics(item,asof){
    const bars=item.bars.filter(b=>b.date<=asof).sort((a,b)=>a.date.localeCompare(b.date));
    const last=bars.at(-1),numeric={},values={market:item.market,kind:item.kind,name:item.name,
      close:last?.close??null,turnover_cny:last?.turnover_cny??null,close_change_pct:null,volume_ratio_5:null,price_above_ma20:null};
    if(last){numeric.close=decimal(last.close);numeric.turnover_cny=decimal(last.turnover_cny);}
    if(bars.length>=2&&cmp(decimal(bars.at(-2).close),decimal('0'))>0){
      numeric.close_change_pct=mul(sub(div(decimal(last.close),decimal(bars.at(-2).close)),decimal('1')),decimal('100'));
      values.close_change_pct=display(numeric.close_change_pct);
    }
    if(bars.length>=6){
      const previous=sum(bars.slice(-6,-1).map(b=>b.volume_shares));
      numeric.volume_ratio_5=div(mul(decimal(last.volume_shares),decimal('5')),previous);
      values.volume_ratio_5=display(numeric.volume_ratio_5);
    }
    if(bars.length>=20)values.price_above_ma20=cmp(mul(decimal(last.close),decimal('20')),sum(bars.slice(-20).map(b=>b.close)))>0;
    return {bars,values,numeric};
  }
  function match(value,condition,numeric){
    if(value==null)return null;
    if(['market','kind','name'].includes(condition.field)){
      if(!['eq','ne','contains'].includes(condition.op))throw Error('文本筛选关系无效。');
      return condition.op==='eq'?value===condition.value:condition.op==='ne'?value!==condition.value:value.includes(condition.value);
    }
    if(condition.field==='price_above_ma20'){
      if(!['eq','ne'].includes(condition.op)||!['true','false'].includes(condition.value))throw Error('均线筛选关系无效。');
      const equal=value===(condition.value==='true');return condition.op==='eq'?equal:!equal;
    }
    const order=cmp(numeric||decimal(value),decimal(condition.value));
    const result={eq:order===0,ne:order!==0,gt:order>0,gte:order>=0,lt:order<0,lte:order<=0};
    if(!(condition.op in result))throw Error('数值筛选关系无效。');return result[condition.op];
  }
  function screen(bundle){
    if(bundle.algorithm!==algorithm)throw Error('浏览器计算版本不兼容，请刷新后新建批次。');
    const request=bundle.request,selected=[];let unresolved=0;
    for(const item of bundle.universe){
      const m=metrics(item,request.as_of);
      const outcomes=request.conditions.map(c=>match(m.values[c.field],c,m.numeric[c.field]));
      if(!m.bars.length){unresolved++;continue;}
      const accepted=!outcomes.length||(request.combine==='all'?outcomes.every(x=>x===true):outcomes.some(x=>x===true));
      if(!accepted&&outcomes.some(x=>x==null))unresolved++;
      if(accepted)selected.push({instrument_id:item.instrument_id,data_date:m.bars.at(-1).date,values:m.values,
        condition_results:outcomes,sort:m.numeric[request.sort_by]});
    }
    selected.sort((a,b)=>a.sort==null?(b.sort==null?0:1):b.sort==null?-1:cmp(a.sort,b.sort)*(request.descending?-1:1));
    return {algorithm,items:selected.slice(0,request.limit).map(({sort,...item})=>item),total:selected.length,unresolved};
  }
  function modelConfig(value){
    if(typeof value.api_base_url!=='string'||value.api_base_url.length>2048||/[\x00-\x1f]/.test(value.api_base_url)||/\s/.test(value.api_base_url.trim()))throw Error('请填写有效模型地址。');
    if(typeof value.model_name!=='string'||(value.api_key!=null&&typeof value.api_key!=='string')||/[\x00-\x1f]/.test(value.model_name+(value.api_key||'')))throw Error('请核对模型名称和密钥。');
    const u=new URL(value.api_base_url.trim()),model=value.model_name.trim(),key=(value.api_key||'').trim();
    if(u.username||u.password||u.search||u.hash||!model||model.length>100||key.length>4096||/[\x00-\x1f]/.test(model+key))throw Error('请核对模型地址、名称和密钥。');
    if(u.protocol!=='https:'&&!(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname)))throw Error('模型需使用 HTTPS，或本机回环 HTTP 地址。');
    if(u.origin===globalThis.location?.origin)throw Error('浏览器模式需填写独立模型 API 地址，不使用平台服务器转发。');
    const url=u.href.replace(/\/+$/,'');return {url:url.endsWith('/chat/completions')?url:url+'/chat/completions',model,key};
  }
  async function model(messages,config,signal,fetcher=fetch){
    if(config.transport==='relay'){
      const ctx=config.relayContext;if(!ctx?.key||!ctx.account_id)throw Error('缺少本次转发身份，尚未调用模型。');
      const login=globalThis.Account?.user?.id;
      const body={account_id:ctx.account_id,purpose:ctx.purpose,consent:true,
        ai_config:{api_base_url:config.url,api_key:config.key,model_name:config.model},
        ...(ctx.purpose==='candidate'?{job_id:ctx.job_id,executor:ctx.executor,input_hash:ctx.input_hash}:{messages})};
      const response=await fetcher('/api/investments/ai-relay',{method:'POST',credentials:'same-origin',redirect:'error',cache:'no-store',signal,
        headers:{'Content-Type':'application/json','X-Copilot-Request':'1','Idempotency-Key':ctx.key},body:JSON.stringify(body)});
      const value=await response.json();
      if(login!==globalThis.Account?.user?.id)throw Error('账号已变化，转发结果未展示。');
      if(!response.ok||value.state!=='ready'||typeof value.raw!=='string')throw Error(value.message||'转发结果未确认，不会自动重发。');
      return value.raw;
    }
    const response=await fetcher(config.url,{method:'POST',mode:'cors',credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer',signal,
      headers:{'Content-Type':'application/json',...(config.key?{Authorization:'Bearer '+config.key}:{})},
      body:JSON.stringify({model:config.model,messages,stream:false})});
    if(!response.ok)throw Error('模型接口拒绝请求，请检查本人配置与接口权限。');
    const reader=response.body.getReader(),decoder=new TextDecoder();let raw='',size=0;
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>400000){await reader.cancel();throw Error('模型响应过大。');}raw+=decoder.decode(value,{stream:true});}
    raw+=decoder.decode();const packet=JSON.parse(raw),choice=packet.choices?.[0];
    if(packet.error||choice?.finish_reason!=='stop'||typeof choice.message?.content!=='string'||choice.message.content.length>80000)throw Error('模型响应不完整或格式不兼容。');
    return choice.message.content;
  }
  globalThis.InvestmentBrowserCore={algorithm,decimal,cmp,display,metrics,screen,modelConfig,model};
})();
