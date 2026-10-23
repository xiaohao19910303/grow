/* Use the actual loading component, including overlapping request completion. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element{constructor(){this.children=[];this.attributes={};}setAttribute(k,v){this.attributes[k]=v;}removeAttribute(k){delete this.attributes[k];}append(...items){for(const item of items){if(item&&typeof item==='object')item.parent=this;this.children.push(item);}}prepend(item){item.parent=this;this.children.unshift(item);}querySelector(){return this.children.find(e=>e.className?.split(' ').includes('loading-state'));}remove(){if(this.parent)this.parent.children=this.parent.children.filter(e=>e!==this);}}
const context={window:{},document:{createElement:()=>new Element()},setTimeout};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/loading-state.js'),'utf8'),context);
const root=new Element(),first=context.window.LoadingState.start(root,'First','Hint'),second=context.window.LoadingState.start(root,'Second');
first.finish();assert(root.querySelector());assert.equal(root.attributes['aria-busy'],'true');second.finish();assert.equal(root.querySelector(),undefined);assert.equal(root.attributes['aria-busy'],undefined);
const detached=context.window.LoadingState.start(root,'Detached');root.children=[];detached.finish();assert.equal(root.attributes['aria-busy'],undefined);
console.log('Actual loading component start/finish contract and stale completion passed.');
