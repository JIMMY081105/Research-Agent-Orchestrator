/* Actual queued turns; HTMX polling only reads state and never invokes a model. */
function syncGoalSettings(){
  const source=document.querySelector('#next-worker-goal-objective'),field=document.querySelector('#prompt-form [name=goal_objective]');
  if(!source||!field)return;
  field.value=source.value;field.readOnly=true;field.dispatchEvent(new Event('input',{bubbles:true}));
  const state=document.querySelector('#next-worker-goal-state')?.value,mode=document.querySelector('#prompt-form [name=mode]');
  if(state==='complete'&&mode?.value==='Goal'){mode.value='Task';mode.dispatchEvent(new Event('change',{bubbles:true}));}
}
function syncAnalysisPermission(){
  const analysis=document.querySelector('[name=channel]')?.value==='analysis';
  const delivery=document.querySelector('[name=publish_result]');
  const mode=document.querySelector('[name=mode]')?.value||'Task';
  const goal=mode==='Goal';
  if(delivery){
    if(analysis&&!delivery.disabled){delivery.dataset.saved=String(delivery.checked);delivery.checked=false;}
    if(!analysis&&delivery.disabled&&delivery.dataset.saved){delivery.checked=delivery.dataset.saved==='true';}
    if(mode!=='Task')delivery.checked=false;
    delivery.disabled=analysis||mode!=='Task'||delivery.dataset.available!=='yes';
  }
  const group=document.querySelector('[data-setting=permission]');if(!group)return;
  const input=group.querySelector('input'),button=group.querySelector('button');
  if(analysis)input.value='Approval needed';
  button.disabled=analysis;button.querySelector('.setting-value').textContent=analysis?'Read-only':input.value;
  button.setAttribute('aria-label',analysis?'文本分析：只读':'执行权限：'+input.value);
  const objective=document.querySelector('.goal-objective');if(objective)objective.hidden=!goal;
  const hint=document.querySelector('#mode-hint');if(hint)hint.textContent=goal?'持久目标 · 每轮经 Claude 审核后继续 · 此模式暂不自动发布最终 PR':mode==='Plan'?'原生 Plan · 只读规划，确认后选择 Task 执行':'';
  const form=document.querySelector('#prompt-form');
  let models={};try{models=JSON.parse(form?.dataset.modelDetails||'{}');}catch(_){}
  const model=document.querySelector('[name=model]')?.value,details=models[model];
  if(details){
    const effortNames={low:'Low',medium:'Medium',high:'High',xhigh:'Extra high',max:'Max'};
    const values=details.efforts?.map(x=>effortNames[x]).filter(Boolean)||[];
    document.querySelectorAll('#menu-effort [data-option]').forEach(x=>{x.disabled=values.length>0&&!values.includes(x.dataset.option);});
    document.querySelectorAll('#menu-speed [data-option]').forEach(x=>{x.disabled=x.dataset.option==='Fast'&&!details.service_tiers?.includes('priority');});
  }
}
document.addEventListener('change',event=>{if(['channel','mode','model'].includes(event.target.name))syncAnalysisPermission();});
syncAnalysisPermission();
document.addEventListener('htmx:beforeSwap',event=>{
  if(event.target.id==='messages' && event.detail.xhr.status>=400) event.detail.shouldSwap=true;
});
document.addEventListener('htmx:sendError',event=>{
  if(event.target.id==='prompt-form'){
    const target=document.querySelector('#messages'),notice=document.createElement('p');
    notice.setAttribute('role','alert');notice.textContent='连接失败，本轮未确认提交。输入已保留；请先刷新状态，避免重复派发。';target?.append(notice);
  }
});
document.addEventListener('htmx:afterSwap',()=>{
  syncGoalSettings();
  syncAnalysisPermission();
  const session=document.querySelector('#next-worker-session')?.value;
  const input=document.querySelector('#prompt-form [name=session]');
  if(session&&input) input.value=session;
  const id=document.querySelector('#next-worker-request')?.value;
  const idInput=document.querySelector('#prompt-form [name=request_id]');if(id&&idInput)idInput.value=id;
  const feed=document.querySelector('#conversation');if(feed)feed.scrollTop=feed.scrollHeight;
});
