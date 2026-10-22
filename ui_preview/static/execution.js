/* Actual queued turns; HTMX polling only reads state and never invokes a model. */
function syncAnalysisPermission(){
  const analysis=document.querySelector('[name=channel]')?.value==='analysis';
  const group=document.querySelector('[data-setting=permission]');if(!group)return;
  const input=group.querySelector('input'),button=group.querySelector('button');
  if(analysis)input.value='Approval needed';
  button.disabled=analysis;button.querySelector('.setting-value').textContent=analysis?'Read-only':input.value;
  button.setAttribute('aria-label',analysis?'文本分析：只读':'执行权限：'+input.value);
}
document.addEventListener('change',event=>{if(event.target.name==='channel')syncAnalysisPermission();});
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
  syncAnalysisPermission();
  const session=document.querySelector('#next-worker-session')?.value;
  const input=document.querySelector('#prompt-form [name=session]');
  if(session&&input) input.value=session;
  const id=document.querySelector('#next-worker-request')?.value;
  const idInput=document.querySelector('#prompt-form [name=request_id]');if(id&&idInput)idInput.value=id;
  const feed=document.querySelector('#conversation');if(feed)feed.scrollTop=feed.scrollHeight;
});
