// The real loading component, rather than a stub that assumes start() exists.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.attributes={};this.className='';this.text='';this.parentElement=null;}
  append(...items){for(const item of items){if(typeof item==='object')item.parentElement=this;this.children.push(item);}}
  prepend(item){item.parentElement=this;this.children.unshift(item);}
  remove(){if(this.parentElement){const p=this.parentElement;p.children=p.children.filter(item=>item!==this);this.parentElement=null;}}
  replaceChildren(...items){for(const item of this.children)if(typeof item==='object')item.parentElement=null;this.children=[];this.append(...items);}
  set textContent(value){this.replaceChildren();this.text=String(value);}
  get textContent(){return this.text+this.children.map(item=>typeof item==='object'?item.textContent:item).join('');}
  setAttribute(key,value){this.attributes[key]=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];}
  querySelector(selector){const cls=selector.slice(1);for(const item of this.children){if(typeof item!=='object')continue;if(item.className.split(' ').includes(cls))return item;const found=item.querySelector(selector);if(found)return found;}return null;}
}
const context={window:{},document:{createElement:tag=>new Element(tag)},setTimeout,WeakMap};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/loading-state.js'),'utf8'),context);
const loading=context.window.LoadingState;

test('start immediately shows accessible progress/detail and finish preserves existing content',()=>{
  assert.equal(typeof loading.start,'function','callers need a real start API, not a test-only stub');
  const container=new Element('section'),saved=new Element('article');saved.textContent='saved input';container.append(saved);
  const handle=loading.start(container,'Loading lesson','Reading saved notes');
  assert.equal(typeof handle.finish,'function');assert(container.textContent.includes('Loading lesson'));assert(container.textContent.includes('Reading saved notes'));
  assert.equal(container.getAttribute('aria-busy'),'true');assert.equal(container.querySelector('.loading-state').getAttribute('role'),'status');
  handle.finish();handle.finish();assert.equal(container.textContent,'saved input');assert.equal(container.getAttribute('aria-busy'),null);
});

test('an old finish handle cannot clear a newer request indicator or busy state',()=>{
  assert.equal(typeof loading.start,'function');
  const container=new Element('section'),old=loading.start(container,'Old');const latest=loading.start(container,'Latest');
  old.finish();assert(container.textContent.includes('Latest'));assert.equal(container.getAttribute('aria-busy'),'true');
  latest.finish();assert.equal(container.getAttribute('aria-busy'),null);assert.equal(container.querySelector('.loading-state'),null);
});

test('finish is safe after reader replacement and missing optional containers',()=>{
  assert.equal(typeof loading.start,'function');
  const container=new Element('section'),handle=loading.start(container,'Loading');const lesson=new Element('article');lesson.textContent='new lesson';container.replaceChildren(lesson);
  handle.finish();assert.equal(container.textContent,'new lesson');assert.doesNotThrow(()=>loading.start(null).finish());
});

test('legacy show, update, hide and error remain compatible',()=>{
  const container=new Element('section');loading.show(container,'First');loading.update(container,'Updated');assert.equal(container.textContent,'Updated');
  loading.hide(container);assert.equal(container.querySelector('.loading-state'),null);
  loading.error(container,'Offline');assert.equal(container.querySelector('.loading-state').getAttribute('role'),'alert');
  loading.show(container,'Retrying');assert.equal(container.textContent,'Retrying');loading.hide(container);
});
