"""Native worker form and approvals; textContent only, same-origin CSRF, no browser tool access."""

FORM = r'''<div class="cy-channel-row"><button type="button" id="workerTab" class="cy-pause">Codex 工作</button><button type="button" id="analysisTab" class="cy-pause">文本分析</button></div>
<form id="workerForm" class="cy-composer" aria-label="Codex 任务与批准" hidden novalidate>
<label for="workerPrompt">任务指令 / 对话</label><textarea id="workerPrompt" maxlength="20000" rows="3" placeholder="说明要完成的任务；点击发送后开始执行。可以使用已有 skills。"></textarea>
<div class="cy-composer-role"><label for="workerMode">执行权限</label><select id="workerMode" aria-label="Codex 执行权限"><option value="approval">需要批准 · Approval needed</option><option value="full">Full Access · 无本地沙箱</option></select></div>
<p class="cy-worker-note" id="workerModeNote">工作区内操作可执行；不受信任的命令或越界访问会请求批准。权限设置用于下一轮。</p>
<div class="cy-composer-role"><label for="workerEffort">思考力度</label><select id="workerEffort"><option value="high">高 · High</option><option value="medium">中 · Medium</option><option value="xhigh">更高 · Extra high</option></select><button id="workerNew" type="button" class="cy-pause">新任务</button></div>
<div class="cy-composer-actions"><button id="workerSubmit" type="submit" class="cy-primary" disabled>发送给 Codex</button><button id="workerCancel" type="button" class="cy-pause" disabled>停止本轮</button><span class="cy-small" id="workerState">执行服务未连接</span></div>
<details class="cy-materials"><summary>规则与 skills / 工作区</summary><p class="cy-small" id="workerWorkspace">新任务使用独立工作区，不接管旧会话。</p><label for="workerSkills">选用 skills（可选，最多 8 项）</label><select id="workerSkills" multiple size="3" aria-label="选用 Codex skills"></select><p class="cy-small">沿用现有 Codex 规则。连接服务器前读取 INFRA；Full Access 不自动批准 GPU、发布或接管旧任务。</p></details>
<div id="workerApprovals" class="cy-worker-approvals" aria-live="polite"></div>
<details id="workerTranscript" class="cy-composer-result" open><summary>执行回复与审核</summary><p class="cy-small" id="workerReplyLabel">尚未开始</p><pre id="workerReply" class="cy-worker-reply"></pre><details><summary>命令与执行记录</summary><pre id="workerEvents" class="cy-worker-reply"></pre></details></details>
</form>'''

CSS = r'''
#scene-cyber-deck .cy-mission-input{min-width:0;min-height:0;overflow:auto;padding-right:3px}
#scene-cyber-deck .cy-channel-row{display:flex;gap:18px;border-bottom:1px solid var(--cy-line);margin-bottom:5px}
#scene-cyber-deck .cy-channel-row button[aria-selected="true"]{color:var(--cy-cyan);border-bottom:2px solid var(--cy-cyan)}
#scene-cyber-deck .cy-worker-note{font-size:10px;color:var(--cy-muted);margin:0;line-height:1.3}
#scene-cyber-deck .cy-worker-reply{font:12px/1.45 "Segoe UI","Microsoft YaHei",sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;max-height:130px;overflow:auto;margin:4px 0;color:var(--cy-text)}
#scene-cyber-deck .cy-worker-approval{border:1px solid var(--cy-gold);padding:6px;margin:5px 0;background:#f2d77d09}
#scene-cyber-deck .cy-worker-approval pre{max-height:90px;font-size:11px;white-space:pre-wrap;overflow:auto;overflow-wrap:anywhere}
#scene-cyber-deck .cy-worker-approval button{margin-right:10px}
#scene-cyber-deck #workerSkills{width:100%;font-size:11px}
#scene-cyber-deck #workerPrompt{min-height:50px;height:62px}
#scene-cyber-deck #workerState{color:var(--cy-cyan)}
'''

JS = r'''(() => {
 'use strict';
 const q = s => document.querySelector(s), worker = q('#workerForm');
 if (!worker) return;
 let session = null, csrf = null, enabled = false, current = null, busy = false, sending = false, draft = null, capsKey = '', channel = 'analysis', newSession=false, approvalsKey=null;
 try { const saved=localStorage.getItem('bgv.worker.session'); if (/^[0-9a-f-]{36}$/.test(saved||'')) session=saved; } catch (_) {}
 const states = {QUEUED:'等待执行',STARTING:'正在启动',RUNNING:'Codex 执行中',WAITING_APPROVAL:'等待你批准',WAITING_INPUT:'等待你回答',REVIEWING:'Claude 审核中',REVIEW_PASS:'Claude 工作区检查通过',NEEDS_REWORK:'Claude 要求返工',CANCELLED:'已取消',CANCELLING:'正在停止本轮',INTERRUPTED:'本轮已停止'};
 const running = new Set(['QUEUED','STARTING','RUNNING','WAITING_APPROVAL','WAITING_INPUT','REVIEWING','CANCELLING']);
 function showChannel(next){channel=next;worker.hidden=next!=='worker';q('#composerForm').hidden=next!=='analysis';q('#workerTab').setAttribute('aria-selected',String(next==='worker'));q('#analysisTab').setAttribute('aria-selected',String(next==='analysis'));}
 q('#workerTab').onclick=()=>showChannel('worker');q('#analysisTab').onclick=()=>showChannel('analysis');
 function modeNote(){q('#workerModeNote').textContent=q('#workerMode').value==='full'?'Full Access：不使用本地沙箱，执行命令时不逐次请求批准。任务规则和原有禁止事项仍有效；下一轮生效。':'工作区内操作可执行；不受信任的命令或越界访问会请求批准。权限设置用于下一轮。';}
 q('#workerMode').onchange=modeNote;
 async function request(path, options={}){
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),8000);
  try{const response=await fetch(path,{cache:'no-store',credentials:'same-origin',...options,headers:{Accept:'application/json',...options.headers},signal:controller.signal});let body={};try{body=await response.json();}catch(_){} if(!response.ok)throw new Error(body.error||'服务读取失败');return body;}finally{clearTimeout(timer);}
 }
 function buttons(){q('#workerSubmit').disabled=!enabled||sending||busy||!q('#workerPrompt').value.trim();q('#workerNew').disabled=busy||sending;q('#workerCancel').disabled=!current||!running.has(current.state)||current.state==='REVIEWING';}
 function status(text){q('#workerState').textContent=text;}
 async function post(path,value){if(!csrf)throw new Error('提交能力未确认');return request(path,{method:'POST',headers:{'Content-Type':'application/json','X-BGV-CSRF':csrf},body:JSON.stringify(value)});}
 async function decide(row,decision,answers){
  try{await post('/api/worker/approval',{id:row.id,turn:row.turn,decision,...(answers?{answers}: {})});await refresh();}
  catch(error){status(error.message);}
 }
 function approvals(rows){
  const key=JSON.stringify(rows);if(key===approvalsKey)return;approvalsKey=key;
  const container=q('#workerApprovals');container.replaceChildren();
  for(const row of rows){
   const box=document.createElement('div');box.className='cy-worker-approval';const label=document.createElement('strong');label.textContent=row.method==='item/tool/requestUserInput'?'Codex 需要你回答':'需要你批准这一次操作';box.append(label);
   const detail=document.createElement('pre');detail.textContent=JSON.stringify(row.params,null,2);box.append(detail);
   if(row.method==='item/tool/requestUserInput'){
    const answers={};for(const question of row.params.questions||[]){const field=document.createElement('textarea');field.maxLength=2000;field.placeholder=question.question||question.id;field.setAttribute('aria-label',question.question||question.id);box.append(field);answers[question.id]=field;}
    const send=document.createElement('button');send.type='button';send.textContent='发送回答';send.onclick=()=>decide(row,'answer',Object.fromEntries(Object.entries(answers).map(([k,v])=>[k,v.value])));box.append(send);
   } else {
    const allow=document.createElement('button');allow.type='button';allow.textContent='允许这一次';allow.className='cy-primary';allow.onclick=()=>decide(row,'accept');box.append(allow);
   }
   const deny=document.createElement('button');deny.type='button';deny.textContent='拒绝';deny.onclick=()=>decide(row,'decline');box.append(deny);container.append(box);
  }
 }
 function render(value){
  if(newSession)value={...value,session:null,turns:[],approvals:[],events:[]};
  const sessions=value.sessions||[];if(!newSession&&!session&&value.session){session=value.session;try{localStorage.setItem('bgv.worker.session',session);}catch(_){}}
  current=(value.turns||[])[0]||null;busy=!!current&&running.has(current.state);
  status(current?(states[current.state]||current.state):enabled?'可发送任务':'执行服务未连接');
  const row=sessions.find(x=>x.id===session);q('#workerWorkspace').textContent=row?'工作区：'+row.workspace+' · 会话 '+(row.thread||'尚未启动'):'新任务使用独立工作区，不接管旧会话。';
  q('#workerReplyLabel').textContent=current?(states[current.state]||current.state)+' · 本轮权限 '+(current.mode==='full'?'Full Access':'需要批准')+(current.reason?' · '+current.reason:''):'尚未开始';
  q('#workerReply').textContent=current&&current.response||'';
  q('#workerEvents').textContent=(value.events||[]).map(v=>v.kind+' · '+v.body).join('\n');
  approvals(value.approvals||[]);
  buttons();
 }
 let refreshing=false;
 async function refresh(){
  if(refreshing)return;refreshing=true;
  try{
   const c=await request('/api/worker/capabilities');enabled=c.enabled===true;csrf=c.csrf_token||null;
   const key=JSON.stringify(c.skills||[]);if(key!==capsKey){capsKey=key;const picker=q('#workerSkills');const selected=new Set(Array.from(picker.selectedOptions).map(v=>v.value));picker.replaceChildren();for(const skill of c.skills||[]){const option=document.createElement('option');option.value=skill.id;option.textContent=skill.name;option.title=skill.description;option.selected=selected.has(skill.id);picker.append(option);}}
   const value=await request('/api/worker/status'+(session?'/'+encodeURIComponent(session):''));render(value);
   if(!worker.dataset.loaded&&enabled){worker.dataset.loaded='true';showChannel('worker');}
  }catch(error){enabled=false;status('执行服务未连接 · '+error.message);buttons();}finally{refreshing=false;}
 }
 worker.addEventListener('submit',async event=>{
  event.preventDefault();if(sending||busy||!enabled)return;
  const payload={session,prompt:q('#workerPrompt').value,mode:q('#workerMode').value,effort:q('#workerEffort').value,skills:Array.from(q('#workerSkills').selectedOptions).map(v=>v.value)};
  const key=JSON.stringify(payload);if(!draft||draft.key!==key)draft={key,body:{id:crypto.randomUUID(),...payload}};
  sending=true;buttons();status('正在登记任务…');
  try{const result=await post('/api/worker/turns',draft.body);session=result.session;newSession=false;try{localStorage.setItem('bgv.worker.session',session);}catch(_){}q('#workerPrompt').value='';draft=null;await refresh();}
  catch(error){status(error.message+'；输入保留，重试沿用同一任务 ID。');}finally{sending=false;buttons();}
 });
 q('#workerPrompt').addEventListener('input',buttons);
 q('#workerNew').onclick=()=>{if(busy)return;session=null;current=null;draft=null;newSession=true;try{localStorage.removeItem('bgv.worker.session');}catch(_){}q('#workerReply').textContent='';q('#workerEvents').textContent='';q('#workerWorkspace').textContent='新任务将创建独立工作区，不接管旧会话。';status('新任务 · 将创建独立工作区');buttons();};
 q('#workerCancel').onclick=async()=>{if(!current)return;try{await post('/api/worker/cancel',{id:current.id});await refresh();}catch(error){status(error.message);}};
 q('[data-refresh]').addEventListener('click',()=>void refresh());
 showChannel('analysis');modeNote();refresh();setInterval(refresh,2000);
})();'''
