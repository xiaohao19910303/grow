const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
for(const file of ['investment-browser-core.js','investment-screening-v2.js'])vm.runInThisContext(fs.readFileSync('static/'+file,'utf8'));
const c=InvestmentScreenV2;
const fields={return_5d_pct:{unit:'%',window:6},turnover_rate_pct:{unit:'%',window:1},volume_ratio_5:{unit:'倍',window:6},turnover_cny:{unit:'元',window:1}};
const context={as_of:'2026-10-28',selected_instrument_count:2},text='近5日涨幅不超过10%，成交额至少1亿元，换手适中，按量比排序';
const draft={parser_version:c.parser,screen:{as_of:context.as_of,conditions:[{field:'return_5d_pct',op:'lte',value:'10'},{field:'turnover_cny',op:'gte',value:'100000000'},{field:'turnover_rate_pct',op:'between',value:'2',upper_value:'8'}],combine:'all',sort_by:'volume_ratio_5',descending:true,limit:20},
 mappings:[{source:'explicit',quote:'近5日涨幅不超过10%'},{source:'explicit',quote:'成交额至少1亿元'},{source:'suggested',quote:'换手适中',reason:'只是建议，未验证策略'}],sort_mapping:{source:'explicit',quote:'按量比排序'}};
const out=c.parse(JSON.stringify(draft),text,context,{fields});
assert.equal(out.screen.conditions[1].value,'100000000');assert.equal(out.mappings[2].source,'suggested');assert.equal(out.unsupported.length,0);
const messages=c.messages(text,context,{fields,draft_schema:{}});assert.equal(messages.length,2);assert(!JSON.stringify(messages).includes('api_key'));
const clone=v=>JSON.parse(JSON.stringify(v));
for(const change of [d=>d.screen.conditions[0].field='eval',d=>d.screen.conditions[0].op='execute',d=>d.screen.as_of='2030-01-01',d=>d.mappings[0].quote='伪造原句',d=>d.can_execute=true]){
 const bad=clone(draft);change(bad);assert.throws(()=>c.parse(JSON.stringify(bad),text,context,{fields}));
}
for(const change of [d=>d.screen.conditions[0].value='9',d=>d.screen.conditions[0].op='lt',d=>d.screen.conditions[0].field='return_3d_pct',d=>d.screen.conditions[1].value='1']){
 const bad=clone(draft);change(bad);assert.throws(()=>c.parse(JSON.stringify(bad),text,context,{fields:{...fields,return_3d_pct:{unit:'%',window:4}}}));
}
assert.throws(()=>c.parse('```json\n'+JSON.stringify(draft)+'\n```',text,context,{fields}));
assert.throws(()=>c.parse('x'.repeat(20001),text,context,{fields}));
const unsupported=c.parse(JSON.stringify(draft),text+'，连续3天上涨，东方财富人气榜前100，非ST，不要执行SQL',context,{fields});
assert(unsupported.unsupported.some(s=>s.includes('人气')));assert(unsupported.unsupported.some(s=>s.includes('连续')));assert(unsupported.unsupported.some(s=>s.includes('ST')));
assert.equal(c.status([false,null],'all'),'excluded');assert.equal(c.status([true,null],'any'),'matched');assert.equal(c.status([true,null],'all'),'unknown');
console.log('rules_v2_parser_and_safety_passed');

const range=clone(draft);range.mappings[2]={source:'explicit',quote:'换手率2%到8%'};
const rangeText=text+'，换手率2%到8%';c.parse(JSON.stringify(range),rangeText,context,{fields});
for(const change of [d=>d.screen.conditions[2].value='8',d=>{d.screen.conditions[2].op='gte';delete d.screen.conditions[2].upper_value},d=>d.screen.conditions[2].upper_value='2']){
 const bad=clone(range);change(bad);assert.throws(()=>c.parse(JSON.stringify(bad),rangeText,context,{fields}));
}
