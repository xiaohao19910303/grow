/* A slow or failed login keeps its input and cannot be submitted twice. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const elements={},requests=[],redirects=[],sessions=[];
const get=id=>elements[id]||={value:'',textContent:'',attributes:{},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},replaceChildren(){this.textContent='';},addEventListener(name,fn){this[name]=fn;},focus(){}};
const context={window:{addEventListener:()=>{},LoadingState:{start:()=>({finish:()=>{}})}},document:{getElementById:get},
  location:{hash:'',replace:value=>redirects.push(value)},URLSearchParams,
  localStorage:{setItem:(key,value)=>sessions.push({key,value})},
  fetch:async(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/login.js'),'utf8'),context);
(async()=>{
  get('username').value='fixture-user';get('password').value='test-only-password';const event={preventDefault:()=>{}};
  const first=get('authForm').submit(event);assert.equal(get('authSubmit').disabled,true);
  assert.equal(get('authSubmit').textContent,'正在登录…');await get('authForm').submit(event);assert.equal(requests.length,1);
  requests[0].reject(Error('Failed to fetch'));await first;
  assert.equal(get('authSubmit').disabled,false);assert(get('authMessage').textContent.includes('连接中断'));
  assert.equal(get('username').value,'fixture-user');assert.equal(get('password').value,'test-only-password');
  assert.equal(get('authForm').attributes['aria-busy'],undefined);
  assert.equal(sessions.length,0,'failed login does not announce a changed session');
  const retry=get('authForm').submit(event);requests[1].resolve({ok:true,json:async()=>({ok:true})});await retry;
  assert.deepEqual(redirects,['/']);assert(get('authMessage').textContent.includes('登录成功'));
  assert.equal(sessions.length,1);assert.equal(sessions[0].key,'grow-account-session');
  assert.doesNotMatch(sessions[0].value,/fixture-user|test-only-password/);
  console.log('Login loading checks passed: immediate progress, duplicate-submit protection, failed-request recovery and successful navigation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
