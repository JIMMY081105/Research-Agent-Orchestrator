"""Conversation-first presentation of public, owned execution/review records."""

CSS = r'''
#scene-cyber-deck .cy-mission>.cy-mission-layout{display:flex;flex-direction:column;gap:4px;min-height:0;flex:1}
#scene-cyber-deck .cy-mission-input{display:flex;flex-direction:column;flex:1;min-height:0;overflow:hidden;padding:0}
#scene-cyber-deck .cy-infra-drawer{flex:none;font-size:10px;color:var(--cy-muted)}
#scene-cyber-deck .cy-infra-drawer>summary{cursor:pointer;display:flex;gap:12px;align-items:center;min-height:20px}
#scene-cyber-deck .cy-infra-drawer>summary::before{content:'▸';color:var(--cy-cyan)}
#scene-cyber-deck .cy-infra-drawer[open]>summary::before{content:'▾'}
#scene-cyber-deck .cy-infra-drawer[open]{max-height:90px;overflow:auto}
#scene-cyber-deck .cy-infra-drawer .cy-mission-sidebar{display:block;padding:5px 0}
#scene-cyber-deck .cy-infra-drawer .cy-budget{margin:0;font-size:10px}
#scene-cyber-deck .cy-chat-feed{flex:1 1 0;min-height:42px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;padding:7px 8px 8px 0;display:flex;flex-direction:column;gap:9px}
#scene-cyber-deck .cy-chat-placeholder{margin:auto;max-width:420px;text-align:center;color:var(--cy-muted);font-size:12px;line-height:1.7}
#scene-cyber-deck .cy-chat-placeholder strong{display:block;font:16px Consolas,monospace;color:var(--cy-cyan);letter-spacing:2px;margin-bottom:7px}
#scene-cyber-deck .cy-chat-message{max-width:95%;padding:7px 10px;border:1px solid var(--cy-line);border-radius:8px;background:#0a101b;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.45;margin:0}
#scene-cyber-deck .cy-chat-message[data-speaker="you"]{align-self:flex-end;background:#6ceee609;border-color:#6ceee634}
#scene-cyber-deck .cy-chat-message[data-speaker="claude"]{border-color:#e8a1ff45}
#scene-cyber-deck .cy-chat-message>header{font:10px Consolas,monospace;letter-spacing:1px;color:var(--cy-muted);margin-bottom:4px}
#scene-cyber-deck .cy-chat-message>p{margin:0;white-space:pre-wrap}
#scene-cyber-deck .cy-chat-thread{display:flex;flex-direction:column;gap:9px}
#scene-cyber-deck .cy-channel-row{margin:3px 0;padding-top:4px;flex:none}
#scene-cyber-deck .cy-mission-input>.cy-composer{flex:0 0 auto;max-height:70%;min-height:0;overflow:auto;scrollbar-gutter:auto;padding:0;gap:3px}
#scene-cyber-deck .cy-composer .cy-composer-policy{font-size:10px}
#scene-cyber-deck .cy-chat-entry{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:5px;border:1px solid #6ceee64d;border-radius:9px;background:var(--cy-deep);align-items:end}
#scene-cyber-deck .cy-chat-entry textarea{border:0;background:transparent;height:54px;min-height:44px;max-height:90px;resize:vertical;padding:5px!important;box-shadow:none}
#scene-cyber-deck .cy-chat-entry>.cy-composer-actions{display:flex;flex-direction:column;align-items:stretch;justify-content:end;padding-bottom:1px;max-width:130px}
#scene-cyber-deck .cy-chat-entry .cy-primary{border-radius:5px;min-height:31px;white-space:nowrap}
#scene-cyber-deck .cy-compose-settings{display:flex;align-items:center;flex-wrap:wrap;gap:4px 10px;font-size:10px}
#scene-cyber-deck .cy-compose-settings>.cy-composer-role{flex:1 1 160px;margin:0}
#scene-cyber-deck .cy-compose-settings select{font-size:10px;min-height:24px}
#scene-cyber-deck .cy-compose-materials{display:flex;align-items:start;gap:14px;flex-wrap:wrap}
#scene-cyber-deck .cy-compose-materials>.cy-materials[open]{flex:1 1 250px}
#scene-cyber-deck .cy-compose-materials textarea{height:60px;min-height:45px;max-height:95px}
#scene-cyber-deck .cy-visually-hidden{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
#scene-cyber-deck .cy-duo .cy-agent-hero{display:flex;align-items:center;gap:15px;min-height:0;flex:none}
#scene-cyber-deck .cy-duo .cy-code .cy-agent-hero{flex-direction:row}
#scene-cyber-deck .cy-duo .cy-claude .cy-agent-hero{flex-direction:row-reverse}
#scene-cyber-deck .cy-duo .cy-character{width:var(--cy-avatar);height:var(--cy-avatar)}
#scene-cyber-deck .cy-duo .cy-avatar-wrap{width:calc(var(--cy-avatar) + 6px);height:calc(var(--cy-avatar) + 8px);flex:none}
#scene-cyber-deck .cy-duo .cy-agent-title{flex:1;min-width:0}
#scene-cyber-deck .cy-duo .cy-agent-state{font:21px/1.25 Consolas,monospace;letter-spacing:1px}
#scene-cyber-deck .cy-duo .cy-agent-sub{font-size:10px;max-height:30px;overflow:auto;margin:3px 0}
#scene-cyber-deck .cy-agent-specs{display:grid;grid-template-columns:auto minmax(0,1fr);gap:3px 12px;margin:7px 0 0;font-size:11px;line-height:1.3}
#scene-cyber-deck .cy-agent-specs dt{color:var(--cy-muted);font:9px/1.6 Consolas,monospace;letter-spacing:1px}
#scene-cyber-deck .cy-agent-specs dd{margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#scene-cyber-deck .cy-claude .cy-agent-specs{text-align:left}
#scene-cyber-deck .cy-public-rail{display:flex;gap:4px;list-style:none;margin:5px 0;padding:0;flex:none}
#scene-cyber-deck .cy-public-rail li{flex:1;min-width:0;font-size:9px;padding:4px 3px;border-top:2px solid var(--cy-line);color:var(--cy-muted)}
#scene-cyber-deck .cy-public-rail li[data-current="true"]{border-color:var(--cy-panel-accent);color:var(--cy-panel-accent);background:#ffffff04}
#scene-cyber-deck .cy-stage-history{flex:1 1 0!important;min-height:28px;display:flex;flex-direction:column;border-top:1px solid var(--cy-line);padding-top:5px}
#scene-cyber-deck .cy-stage-history>header{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:var(--cy-muted);letter-spacing:1px;flex:none}
#scene-cyber-deck .cy-stage-history button{font-size:9px;min-height:18px;padding:0 4px;background:none;border:0;cursor:pointer;color:var(--cy-cyan)}
#scene-cyber-deck .cy-stage-log{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;list-style:none;padding:0 7px 0 0;margin:4px 0 0;font-size:10px;line-height:1.5}
#scene-cyber-deck .cy-stage-log li{border-left:1px solid #6ceee62e;padding:3px 0 3px 8px;white-space:pre-wrap;overflow-wrap:anywhere}
#scene-cyber-deck .cy-stage-log time{color:var(--cy-muted);margin-right:7px;font:9px Consolas,monospace}
#scene-cyber-deck .cy-duo .cy-bridge{width:84px;left:calc(50% - 42px);top:55px;z-index:3}
#scene-cyber-deck .cy-duo .cy-bridge-label{font-size:8px;white-space:nowrap}
#scene-cyber-deck [data-progress="executing"] .cy-agent-state::before,#scene-cyber-deck [data-progress="reviewing"] .cy-agent-state::before{content:'';display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:9px;vertical-align:middle;background:var(--cy-panel-accent);animation:cy-public-thinking 2.2s ease-in-out infinite}
@keyframes cy-public-thinking{0%,100%{opacity:.22;box-shadow:0 0 0 0 transparent}52%{opacity:1;box-shadow:0 0 14px 3px var(--cy-panel-accent)}}
#scene-cyber-deck.cy-paused .cy-agent-state::before,#scene-cyber-deck.cy-motion-off .cy-agent-state::before,#scene-cyber-deck.cy-progress-hidden .cy-agent-state::before{animation:none;box-shadow:none}
@media(min-width:1000px) and (min-height:540px){.desktop-dashboard #scene-cyber-deck{--cy-avatar:clamp(112px,16vh,150px);--cy-avatar-half:calc(var(--cy-avatar)/2)}.desktop-dashboard #scene-cyber-deck .cy-grid{grid-template-rows:minmax(0,1.12fr) minmax(0,1fr)}.desktop-dashboard #scene-cyber-deck .cy-mission-input>.cy-composer textarea{height:54px;min-height:44px}.desktop-dashboard #scene-cyber-deck .cy-mission-input>.cy-chat-feed{min-height:42px}.desktop-dashboard #scene-cyber-deck .cy-stage-history{flex:1 1 0!important}}
@media(max-width:999px){#scene-cyber-deck{--cy-avatar:112px}#scene-cyber-deck .cy-chat-feed{min-height:160px;max-height:360px}#scene-cyber-deck .cy-stage-log{max-height:180px}#scene-cyber-deck .cy-stage-history{min-height:100px}}
@media(prefers-reduced-motion:reduce){#scene-cyber-deck .cy-agent-state::before{animation:none!important;box-shadow:none!important}}
'''

JS = r'''
(() => {
 'use strict';
 const root=document.querySelector('#scene-cyber-deck'); if(!root)return;
 const q=s=>root.querySelector(s), all=s=>Array.from(root.querySelectorAll(s));
 const make=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e;};
 const set=(node,text)=>{text=String(text??'未上报');if(node.textContent!==text)node.textContent=text;};
 const short=(v,n=220)=>typeof v==='string'?v.slice(0,n):'';
 const pretty={QUEUED:'WAITING · 已登记',STARTING:'STARTING · 启动中',RUNNING:'EXECUTING · 执行中',WAITING_APPROVAL:'WAITING · 等待你批准',WAITING_INPUT:'WAITING · 等待你回答',REVIEWING:'WAITING · 等待 Claude 审核',REVIEW_PASS:'COMPLETED · 审核通过',NEEDS_REWORK:'REWORK · 需要修改',CANCELLING:'WAITING · 正在停止',CANCELLED:'STOPPED · 已取消',INTERRUPTED:'STOPPED · 已中断',STALLED:'STALLED · 后台已报告停滞'};
 const phaseLabels=['登记','执行','审核','结果'];
 const time=value=>{const d=new Date(value);return Number.isFinite(d.getTime())?new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d):'—';};
 const host=q('.cy-mission-input'), feed=make('div','cy-chat-feed');feed.id='missionConversation';feed.setAttribute('aria-label','对话与可见执行回复');
 const placeholder=make('div','cy-chat-placeholder'), title=make('strong','', 'ONE MISSION. TWO AGENTS.'), hint=make('span','','在下方输入任务；执行回复与审核意见会显示在这里。');placeholder.append(title,hint);
 const thread=make('div','cy-chat-thread');feed.append(placeholder,thread);host.prepend(feed);
 const approvals=q('#workerApprovals');feed.append(approvals);
 const result=q('#composerTaskDetails');feed.append(result);
 q('#workerTranscript').hidden=true;
 const sidebar=q('.cy-mission-sidebar'), drawer=make('details','cy-infra-drawer'), summary=make('summary','','系统与历史记录');
 summary.append(q('[data-budget]'),q('[data-observed]'));drawer.append(summary,sidebar);
 const layout=q('.cy-mission-layout');layout.prepend(drawer);
 const alert=q('[data-observer-alert]');layout.insertBefore(alert,host);
 sidebar.querySelectorAll('[data-roomy-details]').forEach(e=>{e.removeAttribute('data-roomy-details');e.open=false;});
 function dock(form,promptId){
   const input=q('#'+promptId), label=form.querySelector('label[for="'+promptId+'"]');if(label)label.classList.add('cy-visually-hidden');
   const settings=make('div','cy-compose-settings');Array.from(form.querySelectorAll(':scope>.cy-composer-role')).forEach(e=>settings.append(e));
   const materials=make('div','cy-compose-materials');Array.from(form.querySelectorAll(':scope>.cy-materials')).forEach(e=>materials.append(e));
   const actions=form.querySelector(':scope>.cy-composer-actions'), entry=make('div','cy-chat-entry');entry.append(input,actions);
   if(promptId==='workerPrompt'){settings.append(entry.querySelector('#workerCancel'),entry.querySelector('#workerState'));}
   form.append(settings,materials,entry);
 }
 dock(q('#composerForm'),'composerPrompt');dock(q('#workerForm'),'workerPrompt');
 const panels={};
 for(const [engine,key] of [['codex','code'],['claude','claude']]){
   const panel=q(engine==='codex'?'.cy-code':'.cy-claude'), specs=make('dl','cy-agent-specs'), values={};
   for(const [name,label] of [['model','MODEL'],['effort','EFFORT'],['mode','PERMISSIONS']]){const term=make('dt','',label), value=make('dd','','未上报');specs.append(term,value);values[name]=value;}
   panel.querySelector('.cy-agent-title').append(specs);
   const rail=make('ol','cy-public-rail');rail.setAttribute('aria-label',engine==='codex'?'Codex 工作阶段':'Claude 审核阶段');
   for(const label of engine==='codex'?['接收任务','执行','提交审核','等待结果']:['等待交接','独立审核','审核结论','回传结果'])rail.append(make('li','',label));
   const history=make('div','cy-stage-history'), head=make('header'), follow=make('button','','跟随最新');follow.type='button';head.append(make('span','','PUBLIC PROGRESS · 公开阶段记录'),follow);
   const log=make('ol','cy-stage-log');log.setAttribute('aria-label',engine+'公开阶段历史');log.dataset.follow='true';
   follow.onclick=()=>{log.dataset.follow='true';log.scrollTop=log.scrollHeight;set(follow,'跟随最新');};
   log.onscroll=()=>{log.dataset.follow=String(log.scrollHeight-log.clientHeight-log.scrollTop<18);set(follow,log.dataset.follow==='true'?'跟随最新':'回到最新 ↓');};
   history.append(head,log);panel.append(rail,history);
   const old=panel.querySelector('.cy-history');old.removeAttribute('data-roomy-details');old.open=false;old.hidden=true;
   panels[engine]={panel,key,values,rail,log,follow,state:panel.querySelector('[data-'+key+'-state]'),phase:panel.querySelector('[data-'+key+'-phase]')};
 }
 let worker=null, observation=null, channel='analysis', threadKey='', transition=null, transferTimer=null;
 function statusFresh(){const age=Date.now()-Date.parse(observation?.value?.observed_at);return observation?.fresh===true&&Number.isFinite(age)&&age>=-60000&&age<15000;}
 function isFresh(){const workerAge=Date.now()-(worker?.receivedAt||0);return statusFresh()&&worker?.fresh===true&&workerAge>=-60000&&workerAge<15000;}
 function rows(log,items){
   const key=JSON.stringify(items);if(log.dataset.key===key)return;const follow=log.dataset.follow==='true',top=log.scrollTop;
   log.dataset.key=key;log.replaceChildren(...items.map(item=>{const li=make('li'), stamp=make('time','',time(item.created));li.append(stamp,document.createTextNode(item.text));return li;}));
   log.scrollTop=follow?log.scrollHeight:top;
 }
 function chat(value){
   const stages=value.workflow?.stages||[], turns=value.turns||[], reviews=new Map(stages.map(s=>[s.id,s.review]));
   const key=JSON.stringify([value.session,turns.map(t=>[t.id,t.prompt,t.response,t.state]),stages.map(s=>[s.id,s.review])]);if(key===threadKey)return;
   const follow=feed.scrollHeight-feed.clientHeight-feed.scrollTop<22,top=feed.scrollTop;threadKey=key;
   const nodes=[];
   function bubble(speaker,text,label){if(!text)return;const e=make('article','cy-chat-message');e.dataset.speaker=speaker;e.append(make('header','',label),make('p','',text));nodes.push(e);}
   for(const turn of turns.slice().reverse()){
     bubble('you',short(turn.prompt,20000),'YOU · '+time(turn.created));
     const review=reviews.get(turn.id);
     const label=turn.state==='REVIEW_PASS'&&review?.status!=='PASS'?'UNVERIFIED · 审核记录待确认':pretty[turn.state]||short(turn.state);
     bubble('codex',short(turn.response,64000),'CODEX · '+label);
     if(review&&(review.status==='PASS'||review.status==='REWORK'))bubble('claude',review.status==='PASS'?'当前工作区审核通过。此结论不等于科研场景或物理验收通过。':('需要修改：\n'+(review.issues||[]).join('\n')),'CLAUDE · '+review.status);
   }
   thread.replaceChildren(...nodes);placeholder.hidden=nodes.length>0&&channel==='worker';
   feed.scrollTop=follow?feed.scrollHeight:top;
 }
 function animate(direction){
   if(!isFresh()||!worker?.enabled||document.hidden||root.classList.contains('cy-paused')||root.classList.contains('cy-motion-off')||matchMedia('(prefers-reduced-motion: reduce)').matches)return;
   clearTimeout(transferTimer);root.classList.remove('cy-transfer');root.dataset.transfer=direction;
   void q('.cy-packet').offsetWidth;root.classList.add('cy-transfer');set(q('.cy-bridge-label'),direction==='forward'?'送审 →':'← 审核回执');
   transferTimer=setTimeout(()=>root.classList.remove('cy-transfer'),1800);
 }
 function refresh(){
   const value=worker?.value||{}, turn=(value.turns||[])[0], workflow=value.workflow||{}, stage=(workflow.stages||[]).find(s=>s.id===turn?.id), review=stage?.review;
   const fresh=isFresh(), enabled=worker?.enabled===true;
   if(!fresh||!enabled||document.hidden){clearTimeout(transferTimer);root.classList.remove('cy-transfer');}
   if(turn){
     const next=turn.id+':'+turn.state+':'+(review?.id||'');
     if(transition&&transition.id===turn.id&&transition.key!==next){if(turn.state==='REVIEWING')animate('forward');else if(['REVIEW_PASS','NEEDS_REWORK'].includes(turn.state)&&review&&['PASS','REWORK'].includes(review.status))animate('reverse');}
     transition={id:turn.id,key:next};
   }else transition=null;
   const isBusy=turn&&['STARTING','RUNNING','REVIEWING','WAITING_APPROVAL','WAITING_INPUT','CANCELLING'].includes(turn.state);
   for(const engine of ['codex','claude']){
     const p=panels[engine], observed=observation?.value?.engines?.[engine]||{}, live=fresh&&enabled&&observed.state==='RUNNING';
     p.panel.dataset.progress=live&&isBusy?(engine==='claude'&&turn.state==='REVIEWING'?'reviewing':engine==='codex'&&turn.state==='RUNNING'?'executing':'waiting'):'idle';
     const model=engine==='codex'?(stage?.model||value.sessions?.find(s=>s.id===turn?.session)?.model||value.capability?.default_model):review?.model;
     set(p.values.model,model||(engine==='claude'?'CLI 默认 · 未上报':'未上报'));p.values.model.title=model||'后台没有上报实际模型，不推测。';
     set(p.values.effort,engine==='codex'?(turn?.effort||'未上报'):(review?.effort||'未上报'));
     set(p.values.mode,engine==='codex'?(turn?.mode==='full'?'Full Access':turn?.mode==='approval'?'Approval needed':'未上报'):(review?.tools_disabled===true&&review?.permission_mode==='dontAsk'?'自动审核 · 工具禁用':'未上报'));
     if(turn&&fresh&&enabled){
       let label=pretty[turn.state]||(turn.state?.startsWith('PAUSED')||turn.state?.includes('RECONCILIATION')?'BLOCKED · 已暂停':short(turn.state));
       if(turn.state==='REVIEW_PASS'&&review?.status!=='PASS')label='UNVERIFIED · 审核记录待确认';
       if(engine==='claude')label=turn.state==='REVIEWING'?'REVIEWING · 独立审核中':turn.state==='PAUSED_REVIEW'?'BLOCKED · 审核已暂停':turn.state==='REVIEW_PASS'?(review?.status==='PASS'?'PASS · 可继续下一步':'UNVERIFIED · 审核记录待确认'):turn.state==='NEEDS_REWORK'?'REWORK · 意见已回传':'WAITING · 等待交接';
       const phaseIndex=['registered','execute','review','result'].indexOf(stage?.phase);
       set(p.state,label);set(p.phase,(phaseIndex>=0?'本轮阶段 '+(phaseIndex+1)+'/4 · '+phaseLabels[phaseIndex]:'当前阶段：待上报')+(turn.reason?' · '+short(turn.reason,120):''));
       set(p.panel.querySelector('[data-'+p.key+'-sub]'),engine==='codex'?(turn.state==='REVIEWING'?'已交给 Claude，等待独立审核回执。':'当前登记轮次；下方只显示公开执行记录。'):(turn.state==='REVIEWING'?'审核固定内容；结论与意见会回传到当前轮次。':'当前轮次的审核状态；不代表科研场景验收。'));
     }else if(turn){set(p.state,!fresh?'STALE · 状态待确认':'OFFLINE · 执行服务未连接');set(p.phase,'历史记录 · '+(pretty[turn.state]||short(turn.state)));}
     else if(observation){set(p.state,observation.fresh?(observed.state||'UNKNOWN'):'STALE · 状态待确认');}
     const phase=stage?.phase;let index=-1;
     if(engine==='codex')set(p.rail.lastElementChild,turn?.state==='REVIEW_PASS'?(review?.status==='PASS'?'审核通过':'待核实'):turn?.state==='NEEDS_REWORK'?'待返工':'等待结果');
     else set(p.rail.lastElementChild,turn?.state==='NEEDS_REWORK'?'意见回传':'回传结果');
     if(turn&&['registered','execute','review','result'].includes(phase)){if(engine==='codex')index=phase==='registered'?0:phase==='execute'?1:phase==='review'?2:3;else index=phase==='review'?1:phase==='result'&&review?3:0;}
     Array.from(p.rail.children).forEach((e,i)=>e.dataset.current=String(i===index));
     const entries=[];
     for(const s of (workflow.stages||[])){
       const relevant=engine==='codex'?s.state:s.review?.status;if(!relevant)continue;
       entries.push({created:engine==='claude'?s.review?.completed_at||s.review?.created_at:s.updated,text:(engine==='codex'?'执行轮次 ':'审核 ')+s.id.slice(0,8)+' · '+(pretty[relevant]||relevant)});
       if(engine==='claude')for(const issue of s.review?.issues||[])entries.push({created:s.review.completed_at,text:'意见 · '+short(issue,350)});
     }
     for(const event of value.events||[]){
       if((engine==='claude')!==(event.kind==='REVIEW'))continue;
       if(!['STATUS','COMMAND','FILE_CHANGE','APPROVAL','REVIEW'].includes(event.kind))continue;
       let detail='';try{const body=JSON.parse(event.body);detail=body.command||body.status||body.verdict||body.decision||'';}catch(_){detail=event.body;}
       entries.push({created:event.created,text:event.kind+' · '+short(detail,240)});
     }
     if(!entries.length){
       for(const a of observed.active_attempts||[])entries.push({created:a.created,text:'已登记 · '+short(a.stage||'阶段未上报')});
       if(!entries.length)entries.push({created:null,text:'尚无已登记阶段记录；不会推测其他交互会话。'});
     }
     entries.sort((a,b)=>(Date.parse(a.created)||0)-(Date.parse(b.created)||0));rows(p.log,entries.slice(-60));
     if(statusFresh()&&observed.state==='RUNNING'&&(!fresh||!enabled||!isBusy)){
       p.panel.dataset.progress=engine==='codex'?'executing':'reviewing';
       set(p.state,engine==='codex'?'EXECUTING · 受限队列':'REVIEWING · 受限队列');
       set(p.values.model,'未上报');set(p.values.effort,'未上报');set(p.values.mode,'受限队列 · 工具禁用');
       p.values.model.title='当前登记队列没有上报实际模型，不使用历史 worker 模型代替。';
       set(p.phase,'当前登记阶段：'+(observed.active_attempts||[]).map(a=>short(a.stage,60)).filter(Boolean).join(' / '));
       set(p.panel.querySelector('[data-'+p.key+'-sub]'),'已登记队列的实际运行观测；与原生 worker 的连接状态分开。');
       Array.from(p.rail.children).forEach((e,i)=>e.dataset.current=String(i===1));
       rows(p.log,(observed.active_attempts||[]).map(a=>({created:a.created,text:'受限队列 · '+short(a.stage||'阶段未上报',120)})));
     }
   }
 }
 document.addEventListener('bgv:status',event=>{observation=event.detail;refresh();});
 document.addEventListener('bgv:worker',event=>{worker=event.detail.fresh?{...event.detail,receivedAt:Date.now()}:{...worker,fresh:false,enabled:false};if(worker.value)chat(worker.value);refresh();});
 document.addEventListener('bgv:channel',event=>{channel=event.detail;thread.hidden=channel!=='worker';result.hidden=channel!=='analysis';placeholder.hidden=channel==='worker'&&thread.children.length>0;set(hint,channel==='worker'?'在下方输入任务；执行回复与审核意见会显示在这里。':'在下方输入分析问题；引用材料就在输入框上方。');});
 document.addEventListener('visibilitychange',()=>{root.classList.toggle('cy-progress-hidden',document.hidden);refresh();});
 refresh();
})();
'''
