/* Search must reveal its progress before awaiting results and ignore older queries. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const elements={},requests=[],navigations=[];let allow=true;
const element=id=>elements[id]||=( {innerHTML:'',textContent:'',replaceChildren(){this.innerHTML='';},querySelectorAll:()=>[]} );
const context={window:{LoadingState:{start:(container)=>{container.innerHTML='正在搜索资料';return {finish:()=>{}};}}},
  document:{getElementById:element,readyState:'loading',addEventListener:()=>{}},console,URLSearchParams,AbortController,
  goTab:name=>{if(!allow)return false;navigations.push(name);},esc:value=>value,toast:()=>{},
  fetch:async(url,options)=>new Promise(resolve=>requests.push({url,options,resolve:data=>resolve({ok:true,json:async()=>data})}))};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/search.js'),'utf8'),context);
(async()=>{
  const first=context.window.Search.performSearch('旧查询');assert.deepEqual(navigations,['search']);
  assert(element('searchResults').innerHTML.includes('正在搜索资料'));
  const latest=context.window.Search.performSearch('新查询');assert(requests[0].options.signal.aborted);
  requests[1].resolve({results:[],total_count:0});await latest;const expected=element('searchResults').innerHTML;
  requests[0].resolve({results:[{module:'learning',id:'old',title:'过期结果'}],total_count:1});await first;
  assert.equal(element('searchResults').innerHTML,expected);assert.equal(navigations.length,2,'results never navigate the user back after leaving');
  allow=false;await context.window.Search.performSearch('未保存输入阻止跳转');assert.equal(requests.length,2);
  console.log('Search loading checks passed: immediate visible progress, abort older queries, no late navigation and leave-guard support.');
})().catch(error=>{console.error(error);process.exitCode=1;});
