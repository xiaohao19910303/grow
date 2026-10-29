/* Private investment workspace. Money stays decimal text across the HTTP boundary. */
(() => {
  'use strict';
  const root = () => document.getElementById('investment-workspace');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dateTime = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 16);
  const today = () => dateTime().slice(0, 10);
  const label = {untriggered:'未触发',skipped:'主动跳过',draft:'草稿', confirmed:'已确认', declined:'主动放弃', expired:'已到期', cancelled:'已取消', paused:'已暂停',open:'持有中',closed:'已平仓'};
  const money = value => value == null ? '待核对' : value;
  const s = {view:'today', accountId:null, accounts:[], instruments:[], policies:[], strategies:[], plans:[], fills:[], reviews:[], research:[], fundOrders:[], campaigns:[], notices:[],watches:[],dossiers:[],principles:[],periods:[],checks:[],capital:null,balance:null, generation:0, loading:false};
  let dialog = null;

  async function api(path, options = {}) {
    const response = await fetch('/api/investments/' + path, {
      credentials:'same-origin', ...options,
      headers:{'Content-Type':'application/json','X-Copilot-Request':'1', ...(options.headers || {})}
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if ([401,403].includes(response.status)) {
        s.accounts=[];s.accountId=null;s.fills=[];s.reviews=[];s.balance=null;
      }
      throw new Error(typeof body.message === 'string' ? body.message : '读取或保存失败，请核对连接和输入后重试。');
    }
    return body;
  }
  const button = (text, action, extra = '') => `<button type="button" class="btn" data-inv-action="${action}" ${extra}>${esc(text)}</button>`;
  const options = (items, display) => items.map(item => [item.id, display(item)]);
  const instrumentName = id => s.instruments.find(i => i.id === id)?.name || '未载入标的';
  function status(text, error = false) {
    const target = root()?.querySelector('[data-inv-status]');
    if (target) {target.textContent = text;target.setAttribute('role',error ? 'alert' : 'status');}
  }

  async function load() {
    if (!root()) return;
    const generation = ++s.generation;
    s.loading=true;root().setAttribute('aria-busy','true');
    root().querySelectorAll('[data-inv-action],[data-inv-account]').forEach(c=>c.disabled=true);
    status('正在读取投资记录…');
    try {
      const [accounts, instruments, strategies, checks] = await Promise.all([
        api('accounts?page_size=100'), api('instruments?page_size=100'), api('strategies?page_size=100'),api('plan-checks?page_size=100')
      ]);
      if (generation !== s.generation) return;
      const id = accounts.items.some(a => a.id === s.accountId) ? s.accountId : accounts.items[0]?.id;
      const resources = id ? await Promise.all([
        api(`accounts/${encodeURIComponent(id)}/balance`),
        api(`accounts/${encodeURIComponent(id)}/campaigns`),
        ...['policies','trade-plans','fills','reviews','fund-orders','research'].map(kind => api(`${kind}?account_id=${encodeURIComponent(id)}&page_size=100`)),
        api(`accounts/${encodeURIComponent(id)}/policy-status?as_of=${today()}`),api(`period-plans?account_id=${encodeURIComponent(id)}&page_size=100`),...['watchlist','dossiers','principles','ledger-notices'].map(k=>api(`${k}?account_id=${encodeURIComponent(id)}&page_size=100`))
      ]) : null;
      if (generation !== s.generation) return;
      Object.assign(s, {accounts:accounts.items,instruments:instruments.items,strategies:strategies.items,checks:checks.items,accountId:id || null});
      if (resources) {
        [s.balance] = resources;s.campaigns=resources[1].items;
        [s.policies,s.plans,s.fills,s.reviews,s.fundOrders,s.research] = resources.slice(2).map(r => r.items);
        s.capital=resources[8];s.periods=resources[9].items;[s.watches,s.dossiers,s.principles,s.notices]=resources.slice(10).map(r=>r.items);
      } else Object.assign(s,{balance:null,campaigns:[],policies:[],plans:[],fills:[],reviews:[],fundOrders:[],research:[]});
      s.loading=false;render();refreshOverview();
    } catch (error) {if (generation === s.generation) status(error.message,true);}
    finally {if(generation===s.generation){s.loading=false;root()?.setAttribute('aria-busy','false');root()?.querySelectorAll('[data-inv-action],[data-inv-account]').forEach(c=>c.disabled=false);}}
  }

  function cards(items, renderItem, empty) {
    return items.length ? items.map(item => `<article class="inv-record">${renderItem(item)}</article>`).join('') : `<p class="inv-empty">${esc(empty)}</p>`;
  }
  function versions(kind, item) {
    return `<div class="inv-actions"><small>版本 ${item.version} · ${esc(label[item.state] || '')}</small>` +
      button('查看历史', 'history', `data-kind="${kind}" data-id="${item.id}"`) +
      button('修改版本', 'edit', `data-kind="${kind}" data-id="${item.id}"`) +
      (['trade-plans','period-plans'].includes(kind)?button('记录未交易决定','non-trade',`data-kind="${kind}" data-id="${item.id}" data-version="${item.version}"`):'') +
      (kind==='principles' && item.state==='confirmed'?button('暂停试验','pause-principle',`data-id="${item.id}" data-version="${item.version}"`):'') +
      (item.state === 'draft' ? button('确认','confirm',`data-kind="${kind}" data-id="${item.id}" data-version="${item.version}"`) : '') + '</div>';
  }
  function todayView() {
    const account = s.accounts.find(a => a.id === s.accountId);
    return `<section><h3>先确定资金边界，再写交易计划</h3><p>月度管资金，周度管策略，每日核对执行。条件未到，可以不交易。</p>
      <div class="inv-actions">${button('资金预算','policy')}${button('周日准备计划','period')}${button('新增策略','strategy')}${button('交易计划','plan')}${button('核对日历与交易规则','check')}${button('添加标的','instrument')}${button('保存研究','research')}${button('添加自选跟踪','watch')}${button('结构化研究','dossier')}${button('AI研究与建议','analysis')}${button('AI报告','reports')}${button('配置与验收要求','readiness')}${button('离线条件演练','condition-drills')}</div>
      ${account ? `<p class="inv-muted">当前账户：${esc(account.name)} · 核对起点 ${esc(account.baseline_date)}</p>` : ''}
      ${s.capital?.policy ? `<article class="inv-record"><h4>当前生效预算 · 版本 ${s.capital.policy.version}</h4><p>实际入金 ${esc(s.capital.actual_deposit)} · 对比拟入金差额 ${esc(s.capital.deposit_gap)}</p><p>实际出金 ${esc(s.capital.actual_withdrawal)} · 对比拟取出差额 ${esc(s.capital.withdrawal_gap)}</p><p>当前账本扣除现金缓冲后 ${esc(money(s.capital.available_after_buffer))}</p>${s.capital.conflicts.includes('new_risk_paused')?'<p class="inv-notice">资金政策已暂停新增风险；实际成交仍可记录。</p>':''}<small>草稿不替换生效版本；估值、总风险与亏损复核线缺行情时仍待核对。</small></article>`:'<p class="inv-notice">当前日期没有已确认资金政策。先核对用途与风险预算，拟入金不会增加账本现金。</p>'}
      <h3>资金政策</h3>${cards(s.policies, p => `<h4>${esc(p.period_start)} 至 ${esc(p.period_end)}</h4><p>${esc(p.purpose || '待补充资金用途')}</p><p>拟入金 ${esc(p.planned_deposit)} · 拟取出 ${esc(p.planned_withdrawal)} · 单笔风险预算 ${esc(money(p.trade_risk_budget))}</p>${p.pause_new_risk ? '<p>已设置暂停新增风险</p>' : ''}${versions('policies',p)}`, '先记录资金用途、用钱需求和能承受的损失。')}
      <h3>周日准备计划</h3>${cards(s.periods,p=>`<h4>${esc(p.title)} · ${p.period==='week'?'周计划':'日计划'}</h4><p>${esc(p.period_start)} 至 ${esc(p.period_end)} · ${esc(p.focus)}</p><p>${p.no_trade?'本期可选择不交易':'按条件准备，不要求交易'}</p>${p.session_dates?`<p>已核对开市日 ${esc(p.session_dates.join('、'))}</p>`:''}${p.state_reason?`<p>状态原因：${esc(p.state_reason)}</p>`:''}${versions('period-plans',p)}`,'周计划关注策略与情景，日计划核对执行；不自动新开仓。')}
      <h3>自选跟踪</h3>${cards(s.watches,w=>`<h4>${esc(instrumentName(w.instrument_id))} · ${esc(({observing:'观察',researching:'研究中',ready:'条件准备',held:'持有关注',archived:'已归档'})[w.stage])}</h4><p>${esc(w.reason)}</p><p>下次核对 ${esc(w.next_check || '未设置')}</p>${versions('watchlist',w)}`,'跟踪阶段不是买入信号，也不会改变持仓。')}
      <h3>结构化研究</h3>${cards(s.dossiers,d=>`<h4>${esc(d.title)} · ${d.horizon==='short'?'短线':'波段'}</h4>${[['市场与板块',d.market_context],['量价假设',d.technical_case],['催化事件',d.catalyst],['公司风险',d.company_risk],['估值假设',d.valuation_assumptions],['流动性',d.liquidity],['ETF净值与时差',d.nav_context],['组合影响',d.portfolio_impact],['反对理由',d.contrary_case],['缺少输入',d.missing_inputs]].filter(([title])=>title!=='ETF净值与时差' || s.instruments.find(i=>i.id===d.instrument_id)?.kind!=='stock').map(([t,v])=>`<p>${t}：${esc(v || '待核对')}</p>`).join('')}<p>选定原文 ${d.evidence_ids.length} 份，研究笔记不等于核验事实。</p>${versions('dossiers',d)}`,'股票风险、估值假设与ETF净值/流动性分开记录。')}
      <h3>研究资料与反证</h3>${cards(s.research, r => `<h4>${esc(r.title)}</h4><p class="inv-preserve">${esc(r.content)}</p><p>可获知时间 ${esc(r.available_at)}</p>${r.source_url?`<a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">原始资料</a>`:''}<p>反对证据：${esc(r.contrary_evidence || '尚未补充')}</p>`, '先保存公告、财报或自己的观察，分析时由你选择发送范围。')}
      <h3>交易计划</h3>${cards(s.plans, p => `<h4>${esc(p.title)} · ${esc(instrumentName(p.instrument_id))}</h4><p>用途：${esc(({entry:'做多入场',exit:'退出核对，仅研究草稿',observe:'继续观察，仅研究草稿'})[p.intent || 'entry'])}</p><p>${esc(p.rationale)}</p><p>触发：${esc(p.entry_conditions || '待补充')}<br>失效：${esc(p.invalidation || '待补充')}</p><p>有效截至 ${esc(p.valid_until)} · 风险预算 ${esc(money(p.risk_budget))}</p>${button('估算数量与核对','assess',`data-id="${p.id}"`)}${p.assessment_snapshot?`<p>本人核对的条件计划 · 数量 ${esc(p.assessment_snapshot.quantity)} · 最晚复核 ${esc(p.assessment_snapshot.review_on)}</p>`:''}${versions('trade-plans',p)}`, '从少量自选标的开始，先写触发和放弃条件。')}
      </section>`;
  }
  function ledgerView() {
    const balance = s.balance;
    return `<section><h3>实际成交与持仓</h3><div class="inv-actions">${button('记录成交','fill')}${button('资金流水','cash')}${button('导入CSV','csv')}${button('导入分时路径','path-import')}${button('基金申请','fund')}${button('导出投资记录','export')}${button('关联旧记录','legacy-link')}${button('新增核对事项','notice')}${button('添加标的','instrument')}</div>
      ${balance ? `<dl class="inv-metrics"><div><dt>现金${balance.cash_verified ? '' : '（暂估）'}</dt><dd>${esc(balance.cash)}</dd></div><div><dt>已实现净盈亏</dt><dd>${esc(money(balance.net_realized))}</dd></div><div><dt>总资产</dt><dd>${esc(money(balance.equity))}</dd></div></dl>${balance.warnings.map(w => `<p class="inv-notice">${esc(w)}</p>`).join('')}` : ''}
      <p class="inv-muted">未录入行情时不推算浮动盈亏；费用留空表示尚未核对。这里只记录实际成交。</p>
      <h3>持仓</h3>${cards(balance?.positions || [], p => `<h4>${esc(instrumentName(p.instrument_id))}</h4><p>${p.quantity_verified===false?'所录数量（待核对）':'数量'} ${esc(p.quantity)} · 成本${p.fees_complete && p.settlements_complete!==false ? '' : '（暂估）'} ${esc(money(p.cost))}</p>`, '尚无持仓。')}
      <h3>账实核对事项</h3>${cards(s.notices,n=>`<h4>${esc(instrumentName(n.instrument_id))} · ${n.status==='open'?'待核对':'本人已核对'}</h4><p>${esc(n.reason)}</p><p>${esc(n.resolution || '尚未记录处理结果')}</p><small>系统不自动处理拆分、份额折算等公司行动。先核对并补齐真实事实，再填写处理说明；解除标记不会修改账本。</small>${versions('ledger-notices',n)}`,'如发现公司行动、份额折算或账实差异，先标记核对；不继续把旧数量与收益当作已验证。')}
      <h3>最近成交</h3>${cards(s.fills, f => `<h4>${esc(instrumentName(f.instrument_id))} · ${f.side === 'buy' ? '买入' : '卖出'}</h4><dl class="inv-fill"><div><dt>成交价格</dt><dd>${esc(f.price)}</dd></div><div><dt>数量</dt><dd>${esc(f.quantity)}</dd></div></dl><p>手续费 ${esc(money(f.fee))} · 税费 ${esc(money(f.tax))}</p><small>${esc(f.executed_at)} · ID ${esc(f.id)}</small>${button('核对更正','correction',`data-id="${f.id}"`)}`, '记录第一笔实际成交，刷新后可继续查看。')}
      <h3>基金申请与到账</h3>${cards(s.fundOrders, o => `<h4>${esc(instrumentName(o.instrument_id))} · ${o.side==='subscription'?'申购':'赎回'}</h4><p>${esc(({pending:'待确认',partially_confirmed:'部分确认，待继续核对',confirmed:'已确认，待到账',settled:'已完成'})[o.state] || o.state)} · 待到账 ${esc(o.receivable || '0')}</p>${o.confirmations?.map(b=>`<p>批次净值 ${esc(b.price)} · 份额 ${esc(b.quantity)} · 费用 ${esc(b.fee)} · 净值日 ${esc(b.nav_date)}</p>`).join('') || ''}${['pending','partially_confirmed'].includes(o.state)?button('确认净值与份额','fund-confirm',`data-id="${o.id}"`):o.state==='confirmed'?button('登记赎回到账','fund-settle',`data-id="${o.id}"`):''}`, '申请、确认和到账分别记录，尚未到账的赎回不增加现金。')}
      <h3>完整交易链</h3>${cards(s.campaigns, c => `<h4>${esc(instrumentName(c.instrument_id))} · ${esc(label[c.state])}</h4><p>剩余 ${esc(c.quantity)} · 已实现净盈亏 ${esc(money(c.net_realized))} · R ${esc(money(c.realized_r))}</p><small>R按冻结的实际入场价格差风险和费用预算计算，非最大损失保证；无事前预算不计算。同账户同标的一条进行中交易链。</small>${button('对照复盘','campaign-review',`data-id="${c.id}"`)}${button('路径复盘','path-replay',`data-id="${c.id}" data-instrument="${c.instrument_id}"`)}`, '成交后自动整理分批进出，周末不重置。')}</section>`;
  }
  function reviewView() {
    return `<section><h3>先记录事实，再形成下一项试验</h3><div class="inv-actions">${button('写复盘','review')}${button('新增策略','strategy')}${button('周期统计与建议跟踪','summary')}${button('形成试验原则','principle')}${button('新建前向试验','experiment')}${button('前向试验列表','experiments')}${button('撮合情景验证','execution-studies')}</div>
      <h3>复盘与思考</h3>${cards(s.reviews, r => `<h4>${esc(r.date)} · ${esc(({day:'盘后',campaign:'完整交易',week:'周复盘',month:'月复盘',quarter:'季度',event:'事件',thought:'思考'})[r.period])}</h4><p class="inv-preserve">${esc(r.text)}</p>${r.execution ? `<p>执行：${esc(r.execution)}</p>` : ''}${r.next_experiment ? `<p>下一项试验：${esc(r.next_experiment)}</p>` : ''}<p>执行评价：${esc(({followed:'遵守规则',deviated:'偏离规则',unknown:'尚未评价'})[r.adherence || 'unknown'])} · 逻辑验证：${esc(({supported:'获得支持',refuted:'出现反证',unknown:'尚未判定'})[r.thesis || 'unknown'])}</p>${r.no_trade ? '<p>本次未交易</p>' : ''}${button('生成改进行动','review-action',`data-id="${r.id}" data-version="${r.version}"`)}${button('查看行动引用','action-refs',`data-id="${r.id}"`)}${versions('reviews',r)}`, '一句话也可以保存。盈利、亏损与是否遵守计划分别评价。')}
      <h3>原则与规则试验</h3>${cards(s.principles,p=>`<h4>${esc(p.title)}</h4><p>${esc(p.rule)}</p><p>支持：${esc(p.supporting_case || '待补充')}<br>反例：${esc(p.contrary_case || '待补充')}</p><p>验证范围：${esc(p.validation_scope || '待定义')}</p><small>确认仅表示本人开始试验，不证明有效，不自动修改策略或扩大风险。</small>${versions('principles',p)}`,'先保留原始复盘，再形成有反例和试验范围的候选规则。')}
      <h3>策略</h3>${cards(s.strategies, p => `<h4>${esc(p.title)}</h4><p>入场：${esc(p.entry_conditions || '待补充')}<br>退出：${esc(p.exit_conditions || '待补充')}</p><p>验证：${esc(p.validation_scope || '待定义')}</p>${versions('strategies',p)}`, '先形成一套可验证的方法，不要求每天交易。')}</section>`;
  }
  function render() {
    if (!root()) return;
    root().innerHTML = `<div class="inv-workspace"><header><h2>投资工作台</h2><p class="inv-muted">资金、计划、实际交易和复盘放在一起。</p><div class="inv-actions">
      <label>当前账户<select data-inv-account aria-label="当前账户"><option value="">请选择账户</option>${s.accounts.map(a => `<option value="${a.id}" ${a.id === s.accountId ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}</select></label>
      ${button('新建账户','account')}${button('刷新','refresh')}${button('行情与查询来源','sources')}${button('添加盘后行情','market')}${button('账号缓存筛选','screen')}${button('浏览器筛选与评估','browser-screen')}${button('查找投资记录','private-search')}</div></header>
      <p class="inv-notice">支持CSV、AKShare东方财富及Tushare盘后日线。请核对来源、数据日期和使用范围，实时判断尚未开放。</p>
      <p data-inv-status role="status" aria-live="polite"></p>
      <nav class="inv-tabs" role="tablist" aria-label="投资视图">${[['today','今日与计划'],['ledger','交易簿'],['review','复盘与策略']].map(([key,text]) => `<button role="tab" type="button" aria-selected="${s.view === key}" aria-controls="investment-panel" data-inv-view="${key}">${text}</button>`).join('')}</nav>
      <div id="investment-panel" role="tabpanel">${!s.accountId ? `<div class="inv-empty"><h3>先建立自己的账户</h3><p>从核对过的现金开始，保留实际成交与当时的思考。</p>${button('添加标的','instrument')}</div>` : s.view === 'today' ? todayView() : s.view === 'ledger' ? ledgerView() : reviewView()}</div>
      <p class="inv-muted">列表展示最近100条；完整历史及筛选将随相应切片开放。私人资料保存至当前部署的账号数据库。</p></div>`;
    root().querySelector('[data-inv-account]').onchange = event => {s.accountId = event.target.value;load();};
    root().querySelectorAll('[data-inv-view]').forEach(tab => tab.onclick = () => {s.view=tab.dataset.invView;render();root().querySelector(`[data-inv-view="${s.view}"]`).focus();});
    root().querySelectorAll('[data-inv-action]').forEach(control => control.onclick = () => act(control.dataset.invAction, control.dataset));
    if(s.loading){root().querySelectorAll('[data-inv-action],[data-inv-account]').forEach(c=>c.disabled=true);status('正在读取投资记录…');}
  }

  const field = (key,text,type='text',value='', extra={}) => ({key,text,type,value,...extra});
  const select = (key,text,items,value='') => field(key,text,'select',value,{items});
  const multi = (key,text,items) => field(key,text,'multi',[],{items,optional:true});
  function formFor(action) {
    const aid = s.accountId;
    const securities = options(s.instruments,i => `${i.name} · ${i.code}`);
    const strategyOptions = [['','暂不关联'], ...options(s.strategies,i => `${i.title} · ${label[i.state] || ''}`)];
    if (action === 'account') return {kind:'accounts',title:'新建账户',fields:[field('name','账户名称'),field('baseline_date','核对基准日','date',today()),field('opening_cash','期初现金','decimal')]};
    if (action === 'instrument') return {kind:'instruments',title:'添加标的',fields:[field('code','证券代码'),field('name','证券名称'),select('market','市场',[['SSE','上海'],['SZSE','深圳'],['BSE','北京'],['FUND','场外基金']],'SSE'),select('kind','品种',[['etf','ETF'],['stock','股票'],['fund','场外基金']],'etf')]};
    if (!aid) throw new Error('请先新建或选择账户。');
    if (action === 'fill') {
      if (!securities.length) throw new Error('请先添加标的。');
      return {kind:'fills',title:'记录实际成交',base:{account_id:aid},fields:[select('instrument_id','成交标的',securities),select('side','操作',[['buy','买入'],['sell','卖出']],'buy'),field('price','成交价格','decimal'),field('quantity','成交数量','decimal'),field('fee','手续费','decimal','',{optional:true}),field('tax','税费','decimal','',{optional:true}),field('executed_at','成交时间','datetime-local',dateTime()),{...select('plan_id','关联事前计划',[['','无关联计划'],...options(s.plans,p=>`${p.title} · ${label[p.state] || p.state}`)]),optional:true},field('plan_version','历史计划版本（不填自动匹配）','integer','',{optional:true}),field('external_id','外部成交编号','text','',{optional:true}),field('note','备注','textarea','',{optional:true})]};
    }
    if (action === 'research') return {kind:'research',title:'保存研究资料',base:{account_id:aid},fields:[field('title','资料标题'),field('content','资料原文或观察','textarea'),{...select('instrument_id','关联标的',[['','不关联'],...securities]),optional:true},field('source_url','原始链接','text','',{optional:true}),field('locator','原文位置','text','',{optional:true}),field('available_at','资料可获知时间','datetime-local',dateTime()),field('period_end','资料统计期末','date','',{optional:true}),field('contrary_evidence','反对证据','textarea','',{optional:true})]};
    if (action === 'fund') {
      const funds=options(s.instruments.filter(i=>i.kind==='fund'),i=>`${i.name} · ${i.code}`);
      if(!funds.length) throw new Error('请先添加场外基金标的。');
      return {kind:'fund-orders',title:'基金申请',base:{account_id:aid},fields:[select('instrument_id','基金标的',funds),select('side','申请类型',[['subscription','申购'],['redemption','赎回']]),field('applied_at','申请时间','datetime-local',dateTime()),field('amount','申购金额','decimal','',{optional:true}),field('quantity','赎回份额','decimal','',{optional:true}),field('note','备注','textarea','',{optional:true})]};
    }
    if (action === 'cash') return {kind:'cash-events',title:'资金流水',base:{account_id:aid},fields:[select('kind','流水类型',[['deposit','入金'],['withdrawal','出金'],['dividend','分红'],['interest','利息'],['fee','其他费用']]),field('amount','金额','decimal'),field('occurred_at','发生时间','datetime-local',dateTime()),field('note','备注','textarea','',{optional:true})]};
    if (action === 'check') return {kind:'plan-checks',title:'本人核对日历与交易规则',message:'按券商与交易所原文核对具体证券，不自动推断ETF制度。日历必须逐日连续覆盖收盘资料日、当前日及持有期，休市日也要填写。核对记录保留，不会独立证明资料真实或保证成交。',fields:[select('instrument_id','核对标的',securities),field('quote_price','最近完成开市日的收盘价','decimal'),field('quote_as_of','收盘资料时点','datetime-local'),field('sessions','逐日日历（每行：日期,开市 或 日期,休市）','textarea'),field('rules_valid_from','规则适用开始','date',today()),field('rules_valid_until','规则适用截至','date',today()),field('price_tick','最小价格变动单位','decimal'),field('quantity_step','买入数量递增单位','decimal'),field('minimum_quantity','最低买入数量','decimal'),field('sell_delay_sessions','买入后至少间隔的开市日数','integer'),select('trading_status','已核对交易状态',[['unknown','尚未核对'],['normal','正常'],['halted','停牌或受限']]),field('source_url','核对原始链接'),field('source_note','资料位置与核对说明','textarea'),field('acknowledged','本人已核对资料和适用证券','checkbox',false)]};
    if (action === 'period') return {kind:'period-plans',title:'周日准备计划',base:{account_id:aid},fields:[field('title','准备计划标题'),select('period','准备周期',[['day','日计划'],['week','周计划（周一至周日）']]),field('period_start','准备开始日期','date',today()),field('period_end','准备结束日期','date',today()),field('focus','本期关注与检查事项','textarea'),field('contrary_evidence','本期反对理由','textarea','',{optional:true}),select('strategy_id','关联策略',strategyOptions),{...select('check_id','本人核对资料',[['','尚未核对'],...options(s.checks,c=>`${instrumentName(c.instrument_id)} · ${c.quote_as_of}`)]),optional:true},field('no_trade','本期选择不交易','checkbox',false)]};
    if (action === 'watch') return {kind:'watchlist',title:'自选跟踪',base:{account_id:aid},fields:[select('instrument_id','跟踪标的',securities),select('stage','跟踪阶段',[['observing','观察'],['researching','研究中'],['ready','条件准备'],['held','持有关注'],['archived','已归档']]),field('reason','关注理由','textarea','',{optional:true}),field('next_check','下次核对日期','date','',{optional:true})]};
    if (action === 'dossier') return {kind:'dossiers',title:'股票与ETF结构化研究',base:{account_id:aid},fields:[field('title','研究标题'),select('instrument_id','研究标的',securities),select('horizon','研究持有视角',[['short','短线'],['swing','波段']]),...([['market_context','市场与板块'],['technical_case','量价假设'],['catalyst','催化事件'],['company_risk','公司风险'],['valuation_assumptions','估值假设'],['liquidity','流动性'],['nav_context','ETF净值与时差'],['portfolio_impact','组合影响'],['contrary_case','反对理由'],['missing_inputs','缺少输入']].map(([k,t])=>field(k,t,'textarea','',{optional:true}))),multi('evidence_ids','选择相关原始资料',options(s.research,r=>r.title))]};
    if(action==='experiment') {
      const approved=s.strategies.filter(x=>x.state==='confirmed').map(x=>({...x}));
      if(!approved.length)throw new Error('请先保存并确认一套策略，再登记前向试验。');
      const start=new Date(Date.now()+8*3600000+3600000).toISOString().slice(0,16),end=new Date(Date.now()+8*3600000+7*86400000).toISOString().slice(0,16);
      return {kind:'experiments',title:'新建前向观察试验',message:'先保存草稿，再在开始前显式登记。登记后冻结策略版本、参数、成本假设和期间；全部相符策略版本的盈亏都会列入，不自动增加风险，也不是样本外回测。',base:{account_id:aid},fields:[field('title','试验标题'),select('strategy_id','试验策略',options(approved,x=>`${x.title} · 版本 ${x.version}`)),field('hypothesis','待验证假设','textarea'),field('counter_case','试验反例','textarea'),field('stop_condition','停止观察条件','textarea'),field('parameters','参数记录（每行 名称=值）','textarea'),field('cost_assumptions','成本与样本核对约定','textarea'),field('start_at','试验开始时间','datetime-local',start),field('end_at','试验结束时间','datetime-local',end),field('sample_target','复核样本目标','integer'),field('additional_roundtrip_costs','额外每条完整交易成本压力（元，逗号分隔）','text','0')],transform:values=>{
        const parameters={};for(const line of values.parameters.trim().split('\n')){const split=line.indexOf('=');if(split<1)throw new Error('参数请逐行填写名称=值。');const key=line.slice(0,split).trim();if(Object.hasOwn(parameters,key))throw new Error('参数名不可重复。');Object.defineProperty(parameters,key,{value:line.slice(split+1).trim(),enumerable:true});}
        const strategy=approved.find(x=>x.id===values.strategy_id);if(!strategy)throw new Error('请重新选择已确认策略版本。');
        return {...values,parameters,strategy_version:strategy.version,additional_roundtrip_costs:values.additional_roundtrip_costs.replaceAll('，',',').split(',').map(x=>x.trim())};
      }};
    }
    if (action === 'principle') return {kind:'principles',title:'形成可验证的试验原则',message:'从本人确认的事实出发，保留支持与反例。开始试验不会自动改变策略或交易风险。',base:{account_id:aid},fields:[field('title','原则标题'),field('rule','候选规则','textarea'),field('supporting_case','支持案例','textarea','',{optional:true}),field('contrary_case','反例与失效情形','textarea','',{optional:true}),field('validation_scope','前向试验范围','textarea','',{optional:true}),multi('source_review_ids','选择原始复盘',options(s.reviews,r=>`${r.date} · ${r.text.slice(0,60)}`))]};
    if (action === 'notice') return {kind:'ledger-notices',title:'记录账实核对事项',base:{account_id:aid},fields:[select('instrument_id','核对证券',securities),select('kind','差异类型',[['corporate_action','公司行动或份额折算'],['missing_fact','遗漏事实'],['cost_or_fee','成本或费用'],['other','其他']]),field('observed_at','发现时间','datetime-local',dateTime()),field('reason','待核对原因','textarea'),field('source_url','核对资料链接','text','',{optional:true}),select('status','核对状态',[['open','待核对'],['resolved','本人核对完成']]),field('resolution','处理与核对说明','textarea','',{optional:true})]};
    if (action === 'policy') return {kind:'policies',title:'资金预算',base:{account_id:aid},fields:[field('period_start','开始日期','date',today()),field('period_end','结束日期','date',today()),field('purpose','资金用途','textarea'),field('liquidity_needs','近期用钱需求','textarea'),field('loss_capacity','能承受的损失','textarea'),field('planned_deposit','拟入金','decimal','0'),field('planned_withdrawal','拟取出','decimal','0'),field('cash_buffer','现金缓冲','decimal','',{optional:true}),field('trade_risk_budget','单笔风险预算','decimal','',{optional:true}),field('max_exposure','最大持仓金额','decimal','',{optional:true}),field('loss_review_line','亏损复核线','decimal','',{optional:true}),field('pause_new_risk','暂停新增风险','checkbox',false)]};
    if (action === 'strategy') return {kind:'strategies',title:'新增策略',fields:[field('title','策略名称'),field('environment','适用环境','textarea','',{optional:true}),field('entry_conditions','入场条件','textarea'),field('exclusions','排除条件','textarea','',{optional:true}),field('exit_conditions','退出条件','textarea'),field('validation_scope','验证范围','textarea')]};
    if (action === 'plan') {
      if (!securities.length) throw new Error('请先添加标的。');
      return {kind:'trade-plans',title:'交易计划草稿',base:{account_id:aid},fields:[field('title','计划标题'),select('intent','计划用途',[['entry','做多入场'],['exit','退出核对（研究草稿）'],['observe','继续观察（研究草稿）']]),select('instrument_id','计划标的',securities),select('strategy_id','关联策略',strategyOptions),field('rationale','交易理由','textarea','',{optional:true}),field('entry_conditions','触发条件','textarea','',{optional:true}),field('invalidation','失效条件','textarea','',{optional:true}),field('contrary_evidence','反对理由','textarea','',{optional:true}),field('risk_budget','风险预算','decimal','',{optional:true}),field('holding_sessions','预计持有交易日','integer','',{optional:true}),field('entry_price','计划入场价格','decimal','',{optional:true}),field('invalidation_price','计划失效价格','decimal','',{optional:true}),field('fee_budget','预计本次进出总费用','decimal','',{optional:true}),field('planned_for','计划开市日','date',today(),{optional:true}),{...select('check_id','本人核对资料',[['','尚未核对'],...options(s.checks,c=>`${instrumentName(c.instrument_id)} · ${c.quote_as_of}`)]),optional:true},field('valid_until','有效截至','datetime-local',dateTime())]};
    }
    if (action === 'review') return {kind:'reviews',title:'写复盘',base:{account_id:aid},fields:[select('campaign_id','关联交易链',[['','不关联'],...options(s.campaigns,c=>`${instrumentName(c.instrument_id)} · ${label[c.state]}`)]),field('date','记录日期','date',today()),select('period','复盘周期',[['day','盘后'],['campaign','完整交易'],['week','每周'],['month','每月'],['quarter','季度'],['event','事件'],['thought','投资思考']]),field('text','复盘原文','textarea'),field('judgment','判断依据','textarea','',{optional:true}),field('execution','执行情况','textarea','',{optional:true}),field('next_experiment','下一项试验','textarea','',{optional:true}),select('adherence','执行评价',[['unknown','尚未评价'],['followed','遵守规则'],['deviated','偏离规则']]),select('thesis','逻辑验证',[['unknown','尚未判定'],['supported','获得支持'],['refuted','出现反证']]),field('no_trade','本次未交易','checkbox',false)]};
    throw new Error('此操作尚未开放。');
  }

  function closeDialog() {if (dialog) {dialog.close();dialog.remove();dialog=null;}}
  function openForm(spec) {
    closeDialog();
    dialog=document.createElement('dialog');dialog.className='inv-dialog';
    dialog.setAttribute('aria-labelledby','inv-dialog-title');
    dialog.innerHTML=`<form><h3 id="inv-dialog-title">${esc(spec.title)}</h3>${spec.message?`<p>${esc(spec.message)}</p>`:''}<div class="inv-form">${spec.fields.map(f => {
      const value=esc(f.value),id='inv-field-'+f.key;
      const optional=f.optional || ['strategy_id','campaign_id'].includes(f.key) ? '' : 'required';
      const input=f.type==='multi' ? `<select multiple id="${id}" name="${f.key}" aria-label="${esc(f.text)}">${f.items.map(([v,t])=>`<option value="${esc(v)}" ${(f.value || []).includes(v)?'selected':''}>${esc(t)}</option>`).join('')}</select>` : f.type==='select' ? `<select id="${id}" name="${f.key}" aria-label="${esc(f.text)}" ${optional}>${f.items.map(([v,t]) => `<option value="${esc(v)}" ${v===f.value?'selected':''}>${esc(t)}</option>`).join('')}</select>` : f.type==='textarea' ? `<textarea id="${id}" name="${f.key}" rows="3" ${optional}>${value}</textarea>` : f.type==='checkbox' ? `<input id="${id}" name="${f.key}" type="checkbox" ${f.value?'checked':''}>` : `<input id="${id}" name="${f.key}" type="${['decimal','integer'].includes(f.type)?'text':f.type}" ${['decimal','integer'].includes(f.type)?'inputmode="decimal"':''} value="${value}" ${optional}>`;
      return `<label for="${id}">${esc(f.text)}${f.optional?'（可留空）':''}${input}</label>`;
    }).join('')}</div><p role="alert" data-inv-form-error></p><div class="inv-actions"><button class="btn" type="button" data-inv-cancel>取消</button><button class="btn primary" type="submit">保存</button></div></form>`;
    document.body.append(dialog);dialog.showModal();
    const currentDialog=dialog;
    currentDialog.querySelector('[data-inv-cancel]').onclick=closeDialog;
    currentDialog.addEventListener('close',()=> {currentDialog.remove();if(dialog===currentDialog)dialog=null;});
    if(spec.kind==='plan-checks')attachRulePrefill(currentDialog,spec);
    let requestKey=crypto.randomUUID(), priorBody=null, saving=false;
    currentDialog.querySelector('form').onsubmit=async event => {
      event.preventDefault();if(saving)return;
      const data={...(spec.base || {})};
      for (const f of spec.fields) {
        const input=currentDialog.querySelector(`[name="${f.key}"]`);
        const value=input.value.trim();
        data[f.key]=f.type==='multi' ? [...input.selectedOptions].map(o=>o.value) : f.type==='checkbox' ? input.checked : f.type==='integer' ? (value===''?null:Number(value)) : f.type==='datetime-local' ? (value.length===16?value+':00':value)+'+08:00' : value;
        if (value==='' && f.optional && (['decimal','integer','date','select'].includes(f.type) || ['external_id','source_url','check_id'].includes(f.key))) data[f.key]=null;
        if (['strategy_id','campaign_id','instrument_id','check_id','plan_id'].includes(f.key) && value==='') data[f.key]=null;
      }
      const outgoing=spec.transform ? spec.transform(data) : data;
      const body=JSON.stringify(outgoing);
      if (priorBody!==null && priorBody!==body) requestKey=crypto.randomUUID();
      priorBody=body;saving=true;
      const controls=currentDialog.querySelectorAll('input,select,textarea,button');controls.forEach(c=>c.disabled=true);
      currentDialog.oncancel=event=>event.preventDefault();
      try {
        const path=spec.edit ? `${spec.kind}/${spec.edit.id}` : spec.kind;
        const payload=spec.edit ? JSON.stringify({version:spec.edit.version,data:outgoing}) : body;
        const result=await api(path,{method:spec.edit ? 'PUT':'POST',headers:{'Idempotency-Key':requestKey},body:payload});
        if(spec.kind==='accounts')s.accountId=result.id;
        closeDialog();await load();
        if(spec.kind.endsWith('/actions'))status('已安排改进行动，未复制私人复盘正文或金额。');
        if(spec.kind==='experiments')status('已保存试验草稿，请打开前向试验列表，在开始前登记。');
        if(spec.kind==='legacy-links')status('已保存旧记录关联；旧估算未计入新账盈亏。');
      } catch(error) {currentDialog.querySelector('[data-inv-form-error]').textContent=error.message;}
      finally {saving=false;controls.forEach(c=>c.disabled=false);currentDialog.oncancel=null;}
    };
    currentDialog.querySelector('input,select,textarea')?.focus();
  }

  function attachRulePrefill(d,spec) {
    const panel=document.createElement('div');panel.className='inv-notice';
    panel.innerHTML='<button type="button" class="btn" data-reference>自动填入公开规则与日历</button><p role="status" data-reference-status>无需行情凭证。自动核对公开规则的已覆盖部分；价格、停牌状态及账户权限仍需本人核对。</p>';
    d.querySelector('h3').after(panel);
    const controls=d.querySelector('form').elements,button=panel.querySelector('button'),message=panel.querySelector('p');
    const generated=['sessions','rules_valid_from','rules_valid_until','price_tick','quantity_step','minimum_quantity','sell_delay_sessions'];
    controls.instrument_id.addEventListener('change',()=>{
      if(spec.base?.rulebook_id){for(const key of generated)controls[key].value='';controls.quote_price.value='';controls.quote_as_of.value='';delete spec.base.rulebook_id;}
      message.textContent='标的已变更，请重新核对；不会沿用前一标的的自动依据。';
    });
    button.onclick=async()=>{
      const id=controls.instrument_id.value,instrument=s.instruments.find(i=>i.id===id);if(!instrument)return;
      button.disabled=true;
      try {
        const start=new Date(Date.now()+8*3600000-7*86400000).toISOString().slice(0,10);
        const end=new Date(Date.now()+8*3600000+30*86400000).toISOString().slice(0,10);
        const [rules,cal,data]=await Promise.all([api(`instruments/${encodeURIComponent(id)}/rules?on=${today()}`),api('calendar?'+new URLSearchParams({market:instrument.market,start,end})),api(`instruments/${encodeURIComponent(id)}/data-status`)]);
        if(!d.isConnected || controls.instrument_id.value!==id)return;
        if(rules.status!=='available' || cal.status!=='available')throw new Error('该标的、日期或规则复核期限不在自动覆盖内，请使用原始资料人工核对。');
        for(const key of ['price_tick','quantity_step','minimum_quantity','sell_delay_sessions'])controls[key].value=rules.rules[key]??'';
        controls.sessions.value=Object.entries(cal.sessions).map(([day,open])=>day+','+(open?'开市':'休市')).join('\n');
        controls.rules_valid_from.value=today();controls.rules_valid_until.value=end<rules.review_until?end:rules.review_until;
        controls.source_url.value=rules.source_url;
        controls.source_note.value='公开规则参考 '+rules.rulebook_id+'；仅竞价限价买入。价格、当前交易状态、账户权限及ETF具体机制另核对。';
        spec.base={...(spec.base || {}),rulebook_id:rules.rulebook_id};
        controls.trading_status.value='unknown';controls.acknowledged.checked=false;
        message.textContent='已填入公开参考。当前资料：'+({missing:'尚无行情记录',stale:'数据过期',latest_completed_session:'最近完成开市日的日线',incomplete_or_future:'日线未完成或超前',coverage_unknown:'日历覆盖未知'})[data.status]+'；未核验实时状态。'+(rules.rules.sell_delay_sessions===null?'ETF可卖机制未知，请查具体基金文件后填写。':'请补收盘价与时点，并本人核对状态后保存。');
      }catch(error){if(d.isConnected)message.textContent=error.message;}
      finally{button.disabled=false;}
    };
  }

  async function act(action, data={}) {
    try {
      if(action==='refresh') return await load();
      if(action==='private-search')return searchDialog();
      if(action==='execution-studies')return window.InvestmentMarket.executionStudies({accountId:s.accountId});
      if(action==='condition-drills')return window.InvestmentMarket.conditionDrills({accountId:s.accountId});
      if(action==='experiments') {
        if(!s.accountId)throw new Error('请先选择账户。');
        if(!window.InvestmentMarket)throw new Error('试验入口尚未载入，请刷新。');
        return window.InvestmentMarket.experiments({accountId:s.accountId,onEdit:id=>act('edit',{kind:'experiments',id})});
      }
      if(action==='path-import' || action==='path-replay') {
        if(!window.InvestmentMarket)throw new Error('路径入口尚未载入，请刷新。');
        if(!s.accountId)throw new Error('请先选择账户。');
        return action==='path-import'?window.InvestmentMarket.pathImport({accountId:s.accountId,instruments:s.instruments,refresh:load}):window.InvestmentMarket.replay({accountId:s.accountId,campaignId:data.id,instrumentId:data.instrument});
      }
      if(action==='readiness') {
        const result=await api('readiness');closeDialog();const d=document.createElement('dialog');dialog=d;d.className='inv-dialog';
        d.innerHTML=`<h3>配置与验收要求</h3><p>手工记账、CSV和公开规则参考不需要付费行情或AI凭证。</p><h4>AI配置</h4><p>在设置中填写自己的HTTPS Base URL、API Key和准确模型ID；须支持OpenAI兼容流式聊天及要求的JSON输出。</p><p>${esc(result.ai.cost)}</p><h4>盘后行情</h4><p>AKShare / 东方财富无需Token，支持沪深股票和ETF未复权日线；请先核对使用范围，公开接口可能延迟或限流。</p><p>Tushare Token和daily权限；公开日历覆盖内不需要trade_cal权限。选择供应商日历时另核对trade_cal，ETF另核对fund_daily权限/配额和本人用途许可。Token仅请求时填写，不写入投资记录。</p><h4>未开放</h4><p>分钟/实时权限另行验收，填入Token不会自动开放。真实模型效果和供应商账号权限目前未验证。</p><p>不需要券商登录密码、交易密码或短信验证码。请勿在聊天或文档中粘贴密钥。</p><p>公开规则复核截至 ${esc(result.automatic_reference.review_until)}，超过期限将停止自动填入。</p><button type="button" class="btn">关闭</button>`;
        document.body.append(d);d.showModal();d.querySelector('button').onclick=closeDialog;return;
      }
      if(action==='pause-principle'){await api(`principles/${data.id}/state`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({version:Number(data.version),state:'paused',reason:'本人暂停试验'})});return load();}
      if(action==='review-action')return openForm({kind:`reviews/${data.id}/actions`,title:'把改进安排为行动',message:'仅把下列本人填写的标题和日期保存到行动，不自动复制复盘正文、证券或金额；不会标记课程完成。',base:{source_version:Number(data.version)},fields:[field('title','改进行动标题','text','核对原始资料'),field('date','行动日期','date',today())]});
      if(action==='action-refs') {
        const result=await api(`reviews/${encodeURIComponent(data.id)}/actions`);
        closeDialog();dialog=document.createElement('dialog');dialog.className='inv-dialog';
        dialog.innerHTML=`<h3>已关联的改进行动</h3>${result.items.map(r=>`<article class="inv-record"><p>${r.availability==='available'?'行动仍可查看':'行动已不可用，原复盘与引用保留'}</p><p>来源复盘版本 ${r.source_version}</p>${r.availability==='available'?`<button type="button" class="btn" data-action-open="${esc(r.action_id)}">打开行动</button>`:''}</article>`).join('') || '<p>尚未安排改进行动。</p>'}<button class="btn" data-close>关闭</button>`;
        document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-close]').onclick=closeDialog;
        dialog.querySelectorAll('[data-action-open]').forEach(b=>b.onclick=async()=>{try{if(!window.ActionPlans)throw new Error('行动入口未载入。');const id=b.dataset.actionOpen;closeDialog();if(window.goTab?.('action-plans')===false)return;await window.ActionPlans.openRecord(id);}catch(error){status(error.message,true);}});return;
      }
      if(action==='legacy-link') {
        const result=await api('legacy-records');
        if(!result.items.length)throw new Error('当前账号没有旧投资记录。');
        return openForm({kind:'legacy-links',title:'本人核对后关联旧记录',message:'旧结果是历史估算，不会复制成成交或计入新账净盈亏。先在交易簿补齐真实事实，再关联；缺成本的旧卖出不能据此补造收益。',fields:[select('legacy_id','旧记录',result.items.map(v=>[v.original.id,`${v.original.date} · ${v.original.stock_name} · ${v.original.action}（历史估算）`])),select('target_id','关联成交或复盘',[...s.fills.map(f=>['fills:'+f.id,`成交 · ${instrumentName(f.instrument_id)} · ${f.side==='buy'?'买入':'卖出'} ${f.quantity} · ${f.executed_at}`]),...s.reviews.map(r=>['reviews:'+r.id,`复盘 · ${r.date} · ${r.text.slice(0,60)}`])]),field('note','本人核对说明','textarea'),field('reconciled','本人已核对原始资料和关联事实','checkbox',false)],transform:values=>{const separator=values.target_id.indexOf(':');return {...values,target_kind:values.target_id.slice(0,separator),target_id:values.target_id.slice(separator+1)};}});
      }
      if(action==='summary')return periodDialog();
      if(action==='non-trade')return openForm({kind:`${data.kind}/${data.id}/state`,title:'记录未交易决定',base:{version:Number(data.version)},fields:[select('state','处理结果',[['untriggered','条件未触发'],['skipped','主动跳过'],['declined','主动放弃'],['expired','计划已到期']]),field('reason','决定原因','textarea')]});
      if(action==='assess') {
        const result=await api(`trade-plans/${encodeURIComponent(data.id)}/assessment`);
        closeDialog();dialog=document.createElement('dialog');dialog.className='inv-dialog';
        dialog.innerHTML=`<h3>条件计划数量估算</h3><p>估算数量 ${esc(result.quantity)} · 计划价格差损失含费用 ${esc(result.planned_loss)}</p><p>预计占用 ${esc(result.estimated_commitment)} · 复核日期 ${esc(result.review_on)} · 最早可卖日期 ${esc(result.earliest_sell_on)}</p>${result.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}<button class="btn">关闭</button>`;
        document.body.append(dialog);dialog.showModal();dialog.querySelector('button').onclick=closeDialog;return;
      }
      if(action==='campaign-review')return campaignDialog(data.id);
      if(action==='browser-screen')return window.InvestmentBrowser.open({accountId:s.accountId,instruments:s.instruments});
      if(['sources','market','screen'].includes(action)) {
        if(!window.InvestmentMarket)throw new Error('行情入口尚未载入，请刷新。');
        if(action==='sources')return window.InvestmentMarket.sources();
        if(action==='screen')return window.InvestmentMarket.screen();
        return window.InvestmentMarket.data({accountId:s.accountId,instruments:s.instruments,refresh:load});
      }
      if(action==='analysis') {
        if(!window.InvestmentAI)throw new Error('分析入口尚未载入，请刷新。');
        return window.InvestmentAI.open({accountId:s.accountId,instruments:s.instruments,evidence:s.research,plans:s.plans,reviews:s.reviews,policies:s.policies,dossiers:s.dossiers,campaigns:s.campaigns});
      }
      if(action==='reports')return window.InvestmentAI?.reports();
      if(action==='export') return download('grow-investments.json',JSON.stringify(await api('export'),null,2),'application/json');
      if(action==='csv') return importDialog();
      if(action==='correction') {
        const item=await api(`fills/${data.id}`);
        return openForm({kind:`fills/${item.id}/corrections`,title:'核对更正',message:'保留原记录；此处更正价格、数量和费用，时间/方向错误需另行核对。',fields:[field('price','成交价格','decimal',item.price),field('quantity','成交数量','decimal',item.quantity),field('fee','手续费','decimal',item.fee ?? '',{optional:true}),field('tax','税费','decimal',item.tax ?? '',{optional:true}),field('note','备注','textarea',item.note,{optional:true}),field('reason','更正原因','textarea')],transform:values=>{const {reason,...changes}=values;return {version:item.version,reason,data:changes};}});
      }
      if(action==='fund-confirm') {
        const item=await api(`fund-orders/${data.id}`);
        return openForm({kind:`fund-orders/${item.id}/confirm`,title:'确认净值与份额',base:{version:item.version},message:'请按每批实际确认记录填写。申购净额为实际扣款（含费用），赎回净额为实际待到账金额；不把净值乘份额直接当作实际净额。赎回确认只形成待到账金额。',fields:[field('price','确认净值','decimal'),field('quantity','确认份额','decimal',''),field('fee','实际手续费','decimal'),field('tax','实际税费','decimal'),field('settlement_amount','本批实际收支净额（含费用）','decimal'),field('nav_date','净值日期','date',today()),field('confirmed_at','确认时间','datetime-local',dateTime()),field('final_confirmation','本申请全部确认完毕','checkbox',true)]});
      }
      if(action==='fund-settle') {
        const item=await api(`fund-orders/${data.id}`);
        return openForm({kind:`fund-orders/${item.id}/settle`,title:'登记赎回到账',base:{version:item.version},message:`请先核对实际到账与确认净额 ${item.receivable} 一致。不一致时先核对确认记录。`,fields:[field('received_at','实际到账时间','datetime-local',dateTime())]});
      }
      if(action==='edit') {
        const item=await api(`${data.kind}/${data.id}`);
        const actionFor={'policies':'policy','strategies':'strategy','trade-plans':'plan','reviews':'review','period-plans':'period','watchlist':'watch','dossiers':'dossier','principles':'principle','ledger-notices':'notice','experiments':'experiment'};
        const spec=formFor(actionFor[data.kind]);
        spec.edit={id:item.id,version:item.version};spec.title='修改 · '+spec.title;
        for(const f of spec.fields) {
          f.value=item[f.key] ?? '';
          if(data.kind==='experiments' && f.key==='parameters')f.value=Object.entries(f.value).map(([k,v])=>k+'='+v).join('\n');
          if(data.kind==='experiments' && f.key==='additional_roundtrip_costs')f.value=f.value.join(',');
          if(f.type==='select' && f.value!=='' && !f.items.some(([id])=>id===f.value))f.items.push([f.value,'当前引用未载入，保存时保留']);
          if(f.type==='multi')for(const id of f.value || [])if(!f.items.some(([value])=>value===id))f.items.push([id,'原引用未载入，保存时保留']);
          if(f.type==='datetime-local' && f.value)f.value=new Date(new Date(f.value).getTime()+8*3600000).toISOString().slice(0,16);
        }
        return openForm(spec);
      }
      if(action==='confirm') {
        await api(`${data.kind}/${data.id}/state`,{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({version:Number(data.version),state:'confirmed'})});
        return await load();
      }
      if(action==='history') {
        const history=await api(`${data.kind}/${data.id}/history`);
        closeDialog();dialog=document.createElement('dialog');dialog.className='inv-dialog';
        dialog.innerHTML=`<h3>保留的历史版本</h3>${history.items.map(item=>`<article class="inv-record"><h4>版本 ${item.version} · ${esc(label[item.state] || '')}</h4><p class="inv-preserve">${esc(item.text || item.rationale || item.purpose || item.entry_conditions || item.rule || item.focus || item.reason || item.technical_case || item.title)}</p><small>${esc(item.updated_at)}</small><details><summary>查看完整版本</summary><pre>${esc(JSON.stringify(item,null,2))}</pre></details></article>`).join('')}<button class="btn" type="button">关闭</button>`;
        document.body.append(dialog);dialog.showModal();dialog.querySelector('button').onclick=closeDialog;return;
      }
      openForm(formFor(action));
    } catch(error) {status(error.message,true);}
  }

  async function campaignDialog(id) {
    const result=await api(`accounts/${encodeURIComponent(s.accountId)}/campaigns/${encodeURIComponent(id)}/review`);
    closeDialog();const d=document.createElement('dialog');dialog=d;d.className='inv-dialog';
    d.innerHTML=`<h3>事前依据与实际结果对照</h3><p>净盈亏 ${esc(money(result.campaign.net_realized))} · R ${esc(money(result.campaign.realized_r))}</p>${result.fills.map(row=>`<article class="inv-record"><h4>${row.fill.side==='buy'?'买入':'卖出'} ${esc(row.fill.quantity)} × ${esc(row.fill.price)}</h4><p>${esc(row.fill.executed_at)}</p><p>计划有效期核对：${row.fill.plan_valid_at_execution?'成交时仍在期限内':'无计划、未确认或已过期；不推定遵守规则'}</p><p>计划：${esc(({before_execution:'事前已确认',retrospective:'事后补记或未确认',absent:'无关联计划'})[row.plan_status])}</p>${row.original_plan?`<p>原计划版本 ${row.original_plan.version}：${esc(row.original_plan.title)}</p><p>触发：${esc(row.original_plan.entry_conditions)}<br>失效：${esc(row.original_plan.invalidation)}</p>`:''}${row.original_strategy?`<p>原策略版本 ${row.original_strategy.version}：${esc(row.original_strategy.title)}</p>`:''}<p>备注：${esc(row.fill.note)}</p></article>`).join('')}${result.reviews.map(r=>`<p class="inv-preserve">${esc(r.text)}</p>`).join('')}${result.limitations.map(t=>`<p>${esc(t)}</p>`).join('')}<button class="btn" data-write>写这笔复盘</button><button class="btn" data-close>关闭</button>`;
    document.body.append(d);d.showModal();d.querySelector('[data-close]').onclick=closeDialog;
    d.querySelector('[data-write]').onclick=()=>{const spec=formFor('review');spec.fields.find(f=>f.key==='campaign_id').value=id;spec.fields.find(f=>f.key==='period').value='campaign';openForm(spec);};
  }

  function periodDialog() {
    const account=s.accounts.find(a=>a.id===s.accountId);if(!account)throw new Error('请先选择账户。');
    const aid=account.id;
    closeDialog();const d=document.createElement('dialog');dialog=d;d.className='inv-dialog';
    const start=[today().slice(0,8)+'01',account.baseline_date].sort().at(-1);
    d.innerHTML=`<h3>周期统计与建议跟踪</h3><form class="inv-form"><label>统计开始<input type="date" name="start" value="${start}" required></label><label>统计结束<input type="date" name="end" value="${today()}" required></label><button class="btn" type="submit">查看期间统计</button></form><p role="alert" data-error></p><div data-results aria-live="polite"></div><button class="btn" data-close>关闭</button>`;
    document.body.append(d);d.showModal();d.querySelector('[data-close]').onclick=closeDialog;
    d.querySelector('form').onsubmit=async event=>{
      event.preventDefault();const form=event.target,submit=form.querySelector('button');submit.disabled=true;
      try {
        const values=new URLSearchParams(new FormData(form));const result=await api(`accounts/${encodeURIComponent(aid)}/summary?${values}`);
        if(!d.isConnected)return;
        d.querySelector('[data-results]').innerHTML=`<h4>期间成交已实现净盈亏 ${esc(money(result.net_realized))}</h4><p>入金 ${esc(result.deposit)} · 出金 ${esc(result.withdrawal)} · 分红 ${esc(result.dividend)} · 利息 ${esc(result.interest)} · 独立账户费用 ${esc(result.fee)}</p><p>实际成交 ${result.fill_count} 笔 · 期间平仓 ${result.closed_count} 链 · 期末未平仓 ${result.open_count} 链</p><p>胜率比例 ${esc(money(result.win_rate))}（已知净结果样本 ${result.win_rate_denominator}） · 平均R ${esc(money(result.average_r))}（样本 ${result.r_sample_count}）</p>${result.reconciliation_required?'<p class="inv-notice">账实差异尚未核对，本期净结果无法确认。</p>':''}<p>费用${result.fees_complete?'完整':'不完整，结果待核对'} · 期末现金${result.cash_verified?'':'（暂估）'} ${esc(result.cash_at_end)}</p><h4>策略归组</h4>${result.strategy_groups.map(g=>`<p>${esc(g.strategy_id==='mixed_or_unplanned'?'混合策略或无事前计划':(g.strategy_title+' · 版本 '+g.strategy_version))} · 平仓 ${g.closed_count} · 已知结果 ${g.known_net_count} · 净结果 ${esc(money(g.net_realized))}</p>`).join('') || '<p>尚无期间平仓样本。</p>'}<h4>AI建议处理（含未处理、未采用）</h4>${result.suggestions.map(v=>`<article class="inv-record"><h4>${esc(v.title)}</h4><p>${esc(({pending:'未处理',adopted:'已采用',rejected:'已拒绝',retained:'保留观察',untriggered:'未触发',unfilled:'未成交',modified:'已修改'})[v.state] || v.state)} · 结果尚未核验</p><p>有效截至 ${esc(v.valid_until)}</p></article>`).join('') || '<p>此期间尚无已完成分析产生的建议。</p>'}<details><summary>公式与限制</summary>${[...Object.values(result.formulas),...result.limitations].map(t=>`<p>${esc(t)}</p>`).join('')}</details>`;
        d.querySelector('[data-error]').textContent='';
      }catch(error){d.querySelector('[data-error]').textContent=error.message;}
      finally{submit.disabled=false;}
    };
  }

  function download(name,content,type) {
    const url=URL.createObjectURL(new Blob([content],{type}));
    const link=document.createElement('a');link.href=url;link.download=name;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function importDialog() {
    if(!s.accountId)throw new Error('请先选择账户。');
    const accountId=s.accountId;
    closeDialog();dialog=document.createElement('dialog');dialog.className='inv-dialog';
    dialog.innerHTML=`<h3>预览并导入实际成交</h3><p>使用模板列，先添加相应标的。外部成交编号用于重复核对；每批最多200行。</p><label>CSV文件<input type="file" accept=".csv,text/csv" data-inv-file></label><label>粘贴成交CSV<textarea rows="8" data-inv-csv></textarea></label><p role="alert" data-inv-import-error></p><div data-inv-preview></div><div class="inv-actions"><button type="button" class="btn" data-inv-template>下载模板</button><button type="button" class="btn" data-inv-preview-button>预览</button><button type="button" class="btn" data-inv-commit disabled>确认导入</button><button type="button" class="btn" data-inv-cancel>取消</button></div>`;
    document.body.append(dialog);dialog.showModal();const d=dialog, input=d.querySelector('[data-inv-csv]'), commit=d.querySelector('[data-inv-commit]');
    let preview=null,requestKey=crypto.randomUUID();
    const invalidate=()=>{preview=null;commit.disabled=true;d.querySelector('[data-inv-preview]').replaceChildren();};
    input.oninput=invalidate;
    d.querySelector('[data-inv-file]').onchange=async event=>{
      try {const file=event.target.files[0];if(!file)return;if(file.size>250000)throw new Error('文件超过250KB。');input.value=await file.text();invalidate();}
      catch(error){d.querySelector('[data-inv-import-error]').textContent=error.message;}
    };
    d.querySelector('[data-inv-cancel]').onclick=closeDialog;
    d.querySelector('[data-inv-template]').onclick=()=>download('investment-fills-template.csv','code,market,side,price,quantity,fee,tax,executed_at,external_id,note\n','text/csv');
    d.querySelector('[data-inv-preview-button]').onclick=async event=>{
      event.target.disabled=true;
      try {
        const text=input.value;
        const result=await api('imports/preview',{method:'POST',body:JSON.stringify({account_id:accountId,text})});
        if(text!==input.value)return;
        preview={...result,text};requestKey=crypto.randomUUID();
        d.querySelector('[data-inv-preview]').innerHTML=`<p>${result.rows.length}条可导入，${result.errors.length}条需修正。</p>${result.errors.map(e=>`<p>第${e.line}行：${esc(e.message)}</p>`).join('')}${result.rows.map(r=>`<p>第${r.line}行 · ${r.data.side==='buy'?'买入':'卖出'} · ${esc(r.data.price)} × ${esc(r.data.quantity)}</p>`).join('')}`;
        commit.disabled=!!result.errors.length || !result.rows.length;
      } catch(error){d.querySelector('[data-inv-import-error]').textContent=error.message;}
      finally{event.target.disabled=false;}
    };
    commit.onclick=async()=>{
      if(!preview || preview.text!==input.value)return;
      commit.disabled=true;
      try {await api('imports/commit',{method:'POST',headers:{'Idempotency-Key':requestKey},body:JSON.stringify({account_id:accountId,text:preview.text,token:preview.token})});closeDialog();await load();}
      catch(error){d.querySelector('[data-inv-import-error]').textContent=error.message;commit.disabled=false;}
    };
  }

  function searchDialog() {
    if(!s.accountId)throw new Error('请先选择账户。');
    const accountId=s.accountId;closeDialog();const d=document.createElement('dialog');dialog=d;d.className='inv-dialog';
    d.innerHTML='<h3>查找当前账户的投资记录</h3><p>这里可搜索私人正文、名称与金额。通用搜索和时间线仅显示中性入口，不会自动读取这些正文。</p><form class="inv-form"><label>投资记录关键词<input name="q" maxlength="200" required autocomplete="off"></label><button type="submit" class="btn">查找</button></form><p role="alert" data-error></p><div data-results></div><button class="btn" data-close>关闭</button>';
    document.body.append(d);d.showModal();d.querySelector('[data-close]').onclick=closeDialog;
    d.querySelector('form').onsubmit=async event=>{
      event.preventDefault();const submit=event.target.querySelector('button');submit.disabled=true;
      try {
        const query=new URLSearchParams({account_id:accountId,q:event.target.elements.q.value});
        const result=await api('search?'+query);if(!d.isConnected)return;
        d.querySelector('[data-results]').innerHTML=`<p>找到 ${result.total} 条，当前显示前50条。</p>${result.items.map((r,index)=>`<article class="inv-record"><h4>${esc(r.title)}</h4><p>${esc(r.summary)}</p><button class="btn" type="button" data-open="${index}">查看私有记录</button></article>`).join('')}`;
        d.querySelectorAll('[data-open]').forEach(b=>b.onclick=async()=>{try{await openRecord(result.items[Number(b.dataset.open)]);}catch(error){status(error.message,true);}});
        d.querySelector('[data-error]').textContent='';
      }catch(error){d.querySelector('[data-error]').textContent=error.message;}
      finally{submit.disabled=false;}
    };
  }

  async function openRecord(target) {
    if(!['reviews','trade-plans','period-plans','dossiers','principles','research','policies','instruments','market-snapshots'].includes(target.resource))throw new Error('此投资引用暂不支持打开。');
    const record=await api(`${target.resource}/${encodeURIComponent(target.id)}`);
    s.accountId=record.account_id || s.accountId;s.view=['reviews','principles'].includes(target.resource)?'review':'today';await load();
    closeDialog();dialog=document.createElement('dialog');dialog.className='inv-dialog';
    dialog.innerHTML=`<h3>${esc(record.title || record.name || (target.resource==='market-snapshots'?'盘后行情快照':'投资复盘'))}</h3><p class="inv-preserve">${esc(record.text || record.rule || record.rationale || record.content || record.purpose || record.focus || record.technical_case || '请展开查看本人保存的研究内容。')}</p><p>版本 ${record.version}</p><details><summary>完整私有记录</summary><pre>${esc(JSON.stringify(record,null,2))}</pre></details><button class="btn">关闭</button>`;
    document.body.append(dialog);dialog.showModal();dialog.querySelector('button').onclick=closeDialog;
  }
  let overviewGeneration=0;
  async function refreshOverview() {
    const home=document.getElementById('view-personal');if(!home)return;
    const generation=++overviewGeneration;
    let card=document.getElementById('investmentToday');
    if(!card){card=document.createElement('section');card.id='investmentToday';card.className='section';card.hidden=true;home.querySelector('.day-heading')?.after(card);}
    try {
      const day=document.getElementById('personalDate')?.value || today();
      const result=await api(`overview?as_of=${encodeURIComponent(day)}`);if(generation!==overviewGeneration)return;
      const counts=result.counts;card.hidden=!Object.values(counts).some(n=>n>0);
      card.innerHTML=`<h3>投资记录核对</h3><p>待核对事项 ${Number(counts['ledger-notices'] || 0)} · 计划草稿 ${Number(counts['trade-plans'] || 0)+Number(counts['period-plans'] || 0)} · 所选日复盘 ${Number(counts.reviews || 0)}</p><p class="desc">这里只显示计数，不展示金额或私人正文。</p><button class="btn" type="button">打开投资工作台</button>`;
      card.querySelector('button').onclick=()=>window.goTab?.('stocks');
    }catch(_error){if(generation===overviewGeneration)card.hidden=true;}
  }
  document.getElementById('personalDate')?.addEventListener('change',refreshOverview);
  (window.Account?.ready || Promise.resolve()).then(refreshOverview);
  window.Investments={open:async()=>{if(!root())return;render();await load();},refresh:load,openRecord};
})();
