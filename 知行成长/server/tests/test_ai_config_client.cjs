/* Browser-only credentials: validation matches the request contract without side effects. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/ai-config.js'),'utf8');
function environment(){
 const saved=new Map(),events=[];let denied=false;
 const localStorage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>{if(denied)throw Error('denied');saved.set(k,v);},removeItem:k=>{if(denied)throw Error('denied');saved.delete(k);}};
 const window={Account:{user:{id:'alice',is_owner:false}},dispatchEvent:event=>events.push(event.type)};
 const c={window,localStorage,URL,Event};vm.createContext(c);vm.runInContext(source,c);
 return {config:window.AIConfig,window,saved,events,deny:()=>denied=true};
}
const valid={api_base_url:'https://model.example/v1',api_key:'TEST_SETUP_PRIVATE_KEY',model_name:'test-model'};
const e=environment();
assert.equal(typeof e.config.validate,'function');
assert.equal(e.config.validate({...valid,model_name:' test-model '}).model_name,'test-model');
assert.equal(e.config.address('https://model.example/v1'),'https://model.example/v1');
for(const url of ['http://model.example','https://user:pass@example.org','https://example.org/?key=x','https://example.org/#x','https://example.org:bad','https://example.org/\npath'])assert.throws(()=>e.config.validate({...valid,api_base_url:url}));
for(const [key,limit] of [['api_base_url',2048],['api_key',4096],['model_name',100]]){
 assert.throws(()=>e.config.validate({...valid,[key]:'x'.repeat(limit+1)}));
 assert.throws(()=>e.config.validate({...valid,[key]:'PRIVATE\nSECRET'}),error=>!error.message.includes('PRIVATE'));
 assert.throws(()=>e.config.validate({...valid,[key]:{secret:'PRIVATE'}}));
}
assert.equal(e.saved.size,0);e.config.save(valid);assert.equal(e.saved.size,1);assert.equal(e.config.require().api_key,valid.api_key);
e.window.Account.user.id='bob';assert.equal(e.config.read().api_key,'');assert.throws(()=>e.config.require());
e.config.save({...valid,api_key:'TEST_SETUP_BOB_KEY'});e.config.clear();assert.equal(e.config.read().api_key,'');
e.window.Account.user.id='alice';assert.equal(e.config.read().api_key,valid.api_key);
e.deny();assert.throws(()=>e.config.save({...valid,model_name:'new-model'}),/存储|保存/);assert.equal(e.config.read().model_name,'test-model');
const owner=environment();owner.window.Account.user={id:'owner',is_owner:true};owner.saved.set('zhixing-ai-config-v1',JSON.stringify(valid));assert.equal(owner.config.read().model_name,'test-model');assert(!owner.saved.has('zhixing-ai-config-v1'));
console.log('AI config client passed: safe address/length/control validation, no side effects, account isolation, denied storage and owner migration.');
