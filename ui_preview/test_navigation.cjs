/* Run with Node; no browser, server, model or task mutation. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const handlers=new Map(),aborted=[];
const element={dataset:{},style:{},value:'',textContent:'',classList:{toggle(){},contains(){return false}},
  addEventListener(){},setAttribute(){},querySelector(){return this},querySelectorAll(){return []}};
const doc={hidden:false,documentElement:{dataset:{page:'prompt'},classList:element.classList},
  addEventListener(name,fn){if(!handlers.has(name))handlers.set(name,[]);handlers.get(name).push(fn)},
  querySelector(selector){return selector==='[data-view]'?{dataset:{view:'prompt'}}:element},
  querySelectorAll(selector){return selector==='[hx-get^="/execution/"]'?[{id:'old-display-get'}]:[]}};
vm.runInNewContext(fs.readFileSync(__dirname+'/static/ui.js','utf8'),{
  document:doc,matchMedia:()=>({matches:false,addEventListener(){}}),setInterval(){},
  htmx:{trigger(elt,event){aborted.push([elt.id,event])}},Map,WeakMap,
});
function request(path,target='display'){
 const e={target:{id:target},detail:{requestConfig:{path},target:{id:target},xhr:{}},preventDefault(){this.prevented=true}};
 for(const fn of handlers.get('htmx:beforeRequest'))fn(e);
 return e;
}
function swap(request){
 const e={target:{id:'display'},detail:{xhr:request.detail.xhr,shouldSwap:true}};
 for(const fn of handlers.get('htmx:beforeSwap'))fn(e);
 return e.detail.shouldSwap;
}
const oldPromptPoll=request('/execution/status/owned');
const goProgress=request('/view/progress','workspace');
assert.equal(oldPromptPoll.prevented,undefined);
assert.equal(swap(oldPromptPoll),false,'late Prompt response must not replace Progress');
assert.equal(swap(goProgress),true);
assert.deepEqual(aborted,[['old-display-get','htmx:abort']]);
const oldPromptStillPolling=request('/execution/status/owned');
assert.equal(oldPromptStillPolling.prevented,true);
const progressPoll=request('/execution/progress/owned');
assert.equal(progressPoll.prevented,undefined);assert.equal(swap(progressPoll),true);
const goPrompt=request('/view/prompt','workspace');
assert.equal(swap(progressPoll),false,'late Progress response must not replace Prompt');
assert.equal(swap(goPrompt),true);
assert.equal(request('/execution/progress/owned').prevented,true);
assert.equal(request('/execution/status/owned').prevented,undefined);
assert.equal(request('/execute','prompt-form').prevented,undefined,'navigation must not cancel an actual task submission');
console.log('PASS: late response isolation in both directions, wrong-page GET suppression, and no task-submission cancellation');
