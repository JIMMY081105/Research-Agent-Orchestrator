/* Presentation only. HTMX and Jinja render all pages/messages; no model or task API. */
(() => {
  'use strict';
  const draft = new Map();
  let fresh = false;
  const q = s => document.querySelector(s);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function remember() {
    document.querySelectorAll('[data-draft]').forEach(e => draft.set(e.name, e.value));
  }
  function motion() {
    document.documentElement.classList.toggle('page-hidden', document.hidden);
    const paused = document.hidden || reduced.matches || document.documentElement.classList.contains('motion-off');
    document.querySelectorAll('video').forEach(v => { if (paused) v.pause(); else v.play().catch(() => {}); });
  }
  function refresh() {
    const page = q('[data-view]')?.dataset.view || 'prompt';
    document.documentElement.dataset.page = page;
    q('#page-name').textContent = page === 'prompt' ? 'Prompt' : 'Progress';
    document.querySelectorAll('[data-nav]').forEach(e => e.setAttribute('aria-current', e.dataset.nav === page ? 'page' : 'false'));
    q('#page-switch').open = false;
    document.querySelectorAll('[data-draft]').forEach(e => { if (draft.has(e.name)) e.value = draft.get(e.name); });
    motion();
  }
  document.addEventListener('input', e => { if (e.target.matches('[data-draft]')) remember(); });
  document.addEventListener('change', e => {
    if (!e.target.matches('[data-draft]')) return;
    remember();
    if (q('#mode-note')) q('#mode-note').textContent = e.target.name === 'mode' ?
      ({ Task:'Task：展示任务执行交互。', Plan:'Plan：展示先规划、再实施的交互。', Goal:'Goal：展示持续目标的交互。' }[e.target.value] + ' 当前仅预览。') :
      '所有设置仅作交互预览，没有改变真实模型或权限。';
  });
  document.addEventListener('htmx:beforeSwap', e => { if (e.target.id === 'workspace' && !fresh) remember(); });
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
    if (!e.target.closest('#page-switch')) q('#page-switch').open = false;
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') q('#page-switch').open = false;
    if (e.target.id === 'prompt' && e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); q('#prompt-form').requestSubmit(); }
  });
  q('#new-chat').addEventListener('click', () => { fresh = true; draft.set('prompt',''); draft.set('references',''); });
  q('#motion-toggle').onclick = () => {
    const paused = document.documentElement.classList.toggle('motion-off');
    q('#motion-toggle').textContent = paused ? '◌ 动效暂停' : '◌ 动效开启';
    q('#motion-toggle').setAttribute('aria-pressed', String(paused)); motion();
  };
  reduced.addEventListener('change',motion);
  document.addEventListener('visibilitychange',motion);
  refresh();
})();
