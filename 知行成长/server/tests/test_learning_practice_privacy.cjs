const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Node{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};this.isConnected=true;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(){}addEventListener(){}showModal(){}close(){}remove(){this.isConnected=false;}}
const roots=[],document={body:new Node('body'),createElement:tag=>new Node(tag)};let current=true,listResolve,sourceResolve,immediate=false;
const p={id:'action-private',title:'PRIVATE_LATE_TITLE',status:'active',start_date:null,practice_source:{kind:'record',id:'record-private'},practice_feedback:[]};
const client={read:async route=>route==='/practices'?(immediate?{practices:[p]}:await new Promise(r=>listResolve=r)):await new Promise(r=>sourceResolve=r)};
const account={user:{id:'alice'},isCurrent:()=>current},context={window:{Account:account,ActionPlans:{practiceClient:async()=>client},toast:()=>{}},document,Intl,Date,console};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/learning-practices.js'),'utf8'),context);
const all=node=>[node,...node.children.filter(v=>v&&typeof v==='object').flatMap(all)],text=()=>all(document.body).map(n=>n.textContent).join(' '),turn=()=>new Promise(setImmediate);
(async()=>{
 const opening=context.window.LearningPractices.open('action-private');while(!listResolve)await turn();current=false;listResolve({practices:[p]});await opening;assert(!text().includes('PRIVATE_LATE_TITLE'),'changed account must not render a late private list even when user.id remains alice');
 current=true;immediate=true;document.body.replaceChildren();await context.window.LearningPractices.open('action-private');const source=all(document.body).find(n=>n.tag==='button'&&n.textContent==='查看当前来源');const reading=source.onclick();while(!sourceResolve)await turn();current=false;sourceResolve({available:true,title:'Source',text:'PRIVATE_DELAYED_SOURCE'});await reading;assert(!text().includes('PRIVATE_DELAYED_SOURCE'),'late source body must not be appended after account switch');
 current=true;document.body.replaceChildren();account.ready=Promise.resolve({id:'alice'});context.Account=account;context.location={hash:''};context.window.addEventListener=()=>{};
 let clientResolve;context.ActionPlans={practiceClient:()=>new Promise(r=>clientResolve=r)};
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/practice-follow-up.js'),'utf8'),context);
 const restore=context.window.PracticeFollowUp.open('action-private','feedback-private');while(!clientResolve)await turn();current=false;
 const draft={draft_id:'private',context:{flow:'create-day',origin_key:'practice-followup:action-private:feedback-private'},values:{title:'PRIVATE_PENDING_TITLE'}};
 clientResolve({get:key=>key==='draft.index'?['private']:draft,pending:()=>({key:'pending-private'})});await restore;
 assert(!text().includes('PRIVATE_PENDING_TITLE'),'late controller initialization must not show an old account pending draft');
 console.log('Practice privacy: late list and source responses respect Account.isCurrent and page lifecycle.');
})().catch(e=>{console.error(e);process.exitCode=1;});
