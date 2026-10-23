/* Presentation only. HTMX and Jinja render all pages/messages; no model or task API. */
(() => {
  'use strict';
  const draft = new Map();
  let fresh = false;
  const q = s => document.querySelector(s);
  let viewEpoch=0,intendedView=document.documentElement.dataset.page||'prompt';
  const requestEpoch=new WeakMap();
  document.addEventListener('htmx:beforeRequest',event=>{
    const detail=event.detail,path=detail.requestConfig?.path||'',navigation=path.match(/^\/view\/(prompt|progress)(?:\?|$)/);
    if(navigation&&detail.target?.id==='workspace'){
      intendedView=navigation[1];viewEpoch++;
      // Abort only display GETs. A submitted task/decision is never cancelled.
      document.querySelectorAll('[hx-get^="/execution/"]').forEach(elt=>htmx.trigger(elt,'htmx:abort'));
    }
    if((path.startsWith('/execution/status/')&&intendedView!=='prompt')||(path.startsWith('/execution/progress/')&&intendedView!=='progress')){event.preventDefault();return;}
    if(detail.xhr)requestEpoch.set(detail.xhr,viewEpoch);
  });
  document.addEventListener('htmx:beforeSwap',event=>{
    const detail=event.detail;
    if(detail.xhr&&requestEpoch.has(detail.xhr)&&requestEpoch.get(detail.xhr)!==viewEpoch)detail.shouldSwap=false;
  });
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function remember() {
    document.querySelectorAll('[data-draft]').forEach(e => draft.set(e.name, e.type==='checkbox'?e.checked:e.value));
  }
  function motion() {
    document.documentElement.classList.toggle('page-hidden', document.hidden);
    const paused = document.hidden || reduced.matches || document.documentElement.classList.contains('motion-off');
    document.querySelectorAll('video').forEach(v => { if (paused) v.pause(); else v.play().catch(() => {}); });
  }
  function syncPickers() {
    document.querySelectorAll('[data-setting]').forEach(group => {
      const value = group.querySelector('input').value, button = group.querySelector('.setting-trigger');
      button.querySelector('.setting-value').textContent = value;
      button.setAttribute('aria-label', button.dataset.settingLabel+'：'+value);
      group.querySelectorAll('[data-option]').forEach(option => option.setAttribute('aria-selected', String(option.dataset.option === value)));
    });
  }
  function refresh() {
    const page = q('[data-view]')?.dataset.view || 'prompt';
    document.documentElement.dataset.page = page;
    q('#page-name').textContent = page === 'prompt' ? 'Prompt' : 'Progress';
    document.querySelectorAll('[data-nav]').forEach(e => e.setAttribute('aria-current', e.dataset.nav === page ? 'page' : 'false'));
    document.querySelectorAll('[data-draft]').forEach(e => {
      if (!draft.has(e.name)) return;
      const group=e.closest('[data-setting]'),value=draft.get(e.name);
      if(group&&!Array.from(group.querySelectorAll('[data-option]')).some(o=>o.dataset.option===value)){draft.set(e.name,e.value);return;}
      if(e.type==='checkbox')e.checked=Boolean(value);else e.value=value;
    });
    syncPickers();
    motion();
  }
  document.addEventListener('input', e => { if (e.target.matches('[data-draft]')) remember(); });
  document.addEventListener('change', e => {
    if (!e.target.matches('[data-draft]')) return;
    remember();
    syncPickers();
  });
  document.addEventListener('htmx:beforeSwap', e => {
    document.querySelectorAll('.setting-menu:popover-open').forEach(menu => menu.hidePopover());
    if (e.target.id === 'workspace' && !fresh) remember();
  });
  document.addEventListener('htmx:afterSwap', e => {
    if (e.target.id === 'workspace') { refresh(); fresh = false; }
    if (e.target.id === 'messages') { const feed = q('#conversation'); feed.scrollTop = feed.scrollHeight; }
  });
  document.addEventListener('htmx:afterRequest', e => {
    if (e.target.id === 'prompt-form' && e.detail.successful) { q('#prompt').value = ''; draft.set('prompt',''); }
  });
  document.addEventListener('click', e => {
    const starter = e.target.closest('[data-starter]');
    if (starter) { q('#prompt').value = starter.dataset.starter; remember(); q('#prompt').focus(); }
    const decision = e.target.closest('[data-preview-decision]');
    if (decision) decision.closest('.approval-demo').querySelector('.decision-note').textContent = '已演示“'+decision.dataset.previewDecision+'”；未发送真实批准。';
    const option = e.target.closest('[data-option]');
    if (option) {
      const menu = option.closest('.setting-menu'), group = q('[data-setting="'+menu.dataset.field+'"]');
      const input = group.querySelector('input');input.value = option.dataset.option;
      input.dispatchEvent(new Event('change',{bubbles:true}));menu.hidePopover();group.querySelector('.setting-trigger').focus();
    }
    if(e.target.closest('[data-task]')){fresh=true;draft.clear();}
  });
  document.addEventListener('keydown', e => {
    if (e.target.id === 'prompt' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); q('#prompt-form').requestSubmit(); }
    const menu = e.target.closest('.setting-menu');
    if (menu && e.key === 'Escape') { e.preventDefault();menu.hidePopover();q('[popovertarget="'+menu.id+'"]').focus(); }
    if (menu && ['ArrowDown','ArrowUp','Home','End'].includes(e.key)) {
      e.preventDefault();const options = Array.from(menu.querySelectorAll('[data-option]')), index = options.indexOf(document.activeElement);
      options[e.key === 'Home' ? 0 : e.key === 'End' ? options.length-1 : (index+(e.key === 'ArrowDown' ? 1 : options.length-1))%options.length].focus();
    }
    if (e.target.closest('.setting-trigger') && ['ArrowDown','ArrowUp'].includes(e.key)) { e.preventDefault();q('#'+e.target.closest('.setting-trigger').getAttribute('popovertarget')).showPopover(); }
  });
  document.addEventListener('beforetoggle', e => {
    const menu = e.target;if (!menu.matches('.setting-menu') || e.newState !== 'open') return;
    const trigger = q('[popovertarget="'+menu.id+'"]'), r = trigger.getBoundingClientRect(), width = Math.min(270,innerWidth-24);
    menu.style.width = width+'px';menu.style.left = Math.max(12,Math.min(r.left,innerWidth-width-12))+'px';
    menu.style.bottom = (innerHeight-r.top+10)+'px';menu.style.maxHeight = Math.max(80,r.top-22)+'px';
  },true);
  document.addEventListener('toggle', e => {
    const menu = e.target;if (!menu.matches('.setting-menu')) return;
    const open = e.newState === 'open';q('[popovertarget="'+menu.id+'"]').setAttribute('aria-expanded',String(open));
    if (open) (menu.querySelector('[aria-selected=true]') || menu.querySelector('[data-option]')).focus({preventScroll:true});
  },true);
  q('#new-chat').addEventListener('click', () => { fresh = true; draft.set('prompt',''); draft.set('references',''); });
  q('#motion-toggle').onclick = () => {
    const paused = document.documentElement.classList.toggle('motion-off');
    q('#motion-toggle').textContent = paused ? '◌ 动效暂停' : '◌ 动效开启';
    q('#motion-toggle').setAttribute('aria-pressed', String(paused)); motion();
  };
  reduced.addEventListener('change',motion);
  document.addEventListener('visibilitychange',motion);
  let checkingReadiness=false;
  async function checkReadiness(){
    if(checkingReadiness||document.hidden)return;checkingReadiness=true;
    try{
      const response=await fetch('/preview-health',{cache:'no-store'});if(!response.ok)return;
      const state=await response.json();if(state.owner!=='BGV.SceneControl.UI.v1'||typeof state.ui_only!=='boolean')return;
      const online=!state.ui_only,previous=document.documentElement.dataset.worker==='online';if(online===previous)return;
      document.documentElement.dataset.worker=online?'online':'offline';
      q('#worker-status-label').textContent=online?'WORKER ONLINE':'WORKER OFFLINE';
      q('#worker-status-copy').textContent=online?'真实 Codex 执行 · Claude 审核':'执行服务未就绪或已暂停，输入已保留';
      q('#worker-badge').textContent=online?'执行服务在线':'执行服务未就绪或暂停';
      const send=q('#prompt-form .send');if(send)send.disabled=!online;
      // Preserve an active task and its approvals. A composer-only reconnect
      // refreshes actual CLI choices through HTMX; beforeSwap retains the draft.
      if(!q('#live-execution')){
        const page=q('[data-view]')?.dataset.view||'prompt';remember();
        await htmx.ajax('GET','/view/'+page,{target:'#workspace',swap:'innerHTML'});
      }
    }catch(_){}finally{checkingReadiness=false;}
  }
  setInterval(checkReadiness,3000);
  refresh();
})();
