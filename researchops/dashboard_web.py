"""Dashboard assets: read-only status plus explicit, bounded text-analysis submissions."""

PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><title>SCENE CONTROL · 监控与文本分析</title>
<link rel="stylesheet" href="/assets/dashboard.css"><script src="/assets/dashboard.js" defer></script></head>
<body class="desktop-dashboard"><p class="cy-window-hint" role="status">窗口较小，关键状态将按内容显示。请放大窗口；详细记录可在各区展开滚动。</p><div id="scene-cyber-deck" data-phase="unknown" aria-label="科研状态监控与受限文本分析">
<header class="cy-header"><div class="cy-brand"><div class="cy-logo" aria-hidden="true"></div><div><h1>SCENE<span>//</span>CONTROL</h1><div class="cy-subtitle cy-mono">HUMANOID RESEARCH TERMINAL</div></div></div><div class="cy-live cy-mono" data-connection>状态采集 / 只读 · UNKNOWN</div></header>
<div class="cy-toolbar"><span class="cy-mono" data-controller>控制器：UNKNOWN</span><div class="cy-toolbar-controls"><button type="button" class="cy-pause" data-pause aria-pressed="false">暂停动效</button><label class="cy-motion-label"><input type="checkbox" data-motion checked><span data-motion-label>动态效果</span></label></div></div>
<main class="cy-grid">
<section class="cy-panel cy-mission" aria-label="文本分析输入与已登记任务">
<div class="cy-panel-head"><div><span class="cy-section-id cy-mono">01 / MISSION</span><h2>任务与指令</h2></div><div class="cy-mission-header-tools"><div class="cy-runtime">当前阶段用时<output data-runtime>—</output></div><button type="button" class="cy-pause" data-refresh aria-label="刷新监控状态与提交能力">刷新状态</button></div></div>
<div class="cy-mission-layout"><form class="cy-composer" id="composerForm" aria-label="提交受限文本分析" novalidate>
<p class="cy-composer-policy">仅文本分析与交叉审核 · 不执行代码、SSH 或文件修改。</p>
<label for="composerPrompt">分析问题（Prompt）</label><textarea id="composerPrompt" name="prompt" aria-label="分析问题 Prompt" aria-readonly="false" rows="3" maxlength="2000" placeholder="输入希望分析的问题。未提交前不会调用模型。"></textarea>
<div class="cy-composer-role"><label for="composerWriter">执行 / 审核</label><select id="composerWriter" name="writer" aria-label="执行与审核角色"><option value="codex">Codex 执行 · Claude 审核</option><option value="claude">Claude 执行 · Codex 审核</option></select></div>
<div class="cy-composer-actions"><button id="composerSubmit" type="submit" class="cy-primary" aria-label="提交文本分析" disabled>提交文本分析</button><a data-composer-link href="#composerTaskDetails" hidden>查看任务状态 / 结果</a></div>
<p class="cy-composer-feedback" id="composerFeedback" aria-label="任务提交状态" data-composer-status role="status" aria-live="polite">正在读取提交能力；可以先输入草稿。</p>
<details class="cy-materials"><summary>引用材料（可选，展开粘贴）</summary><label for="composerContext">引用材料</label><textarea id="composerContext" name="context" aria-label="引用材料，可选" aria-readonly="false" rows="3" maxlength="12000" placeholder="粘贴参考文本；留空时分析问题本身。不读取本地文件。"></textarea></details>
<details id="composerTaskDetails" class="cy-composer-result"><summary id="composerReceipt" aria-label="本次任务回执" data-composer-receipt>本次提交：尚未登记</summary><p data-composer-receipt-info>只有主动提交才会创建任务。</p><p class="cy-result-summary" data-composer-result></p><ul class="cy-agent-log" data-composer-citations></ul></details>
</form><div class="cy-mission-sidebar"><p class="cy-task-current" data-task-current>登记任务：UNKNOWN</p>
<p class="cy-budget" data-budget>当日审核：UNKNOWN · UTC 账本日 UNKNOWN</p>
<p class="cy-observer-summary" data-observer-summary>观察器：UNKNOWN</p>
<p class="cy-observer-alert" data-observer-alert role="alert" hidden></p>
<div class="cy-mission-actions"><span class="cy-small" data-observed>实际采集：UNKNOWN</span></div>
<details class="cy-history" data-roomy-details><summary>登记任务与执行详情</summary><label class="cy-task-label" for="cy-task">登记任务概览（只读）</label><textarea id="cy-task" rows="2" data-task readonly aria-readonly="true">UNKNOWN · 尚未取得任务缓存</textarea><p class="cy-small" data-observer>研究观察器：UNKNOWN</p><ul class="cy-agent-log" data-observer-signals></ul><div class="cy-activity-title"><span class="cy-activity-dot" aria-hidden="true"></span><span>ACTIVITY · 可见执行摘要</span></div><ul class="cy-activity" data-activity><li>UNKNOWN · 等待后台缓存观测。</li></ul><ul class="cy-agent-log" data-task-history><li>UNKNOWN</li></ul><div class="cy-attachments"><label class="cy-file-label" for="cy-files">附件不可用 · 本次为监控视图，不上传文件</label><input id="cy-files" type="file" disabled aria-disabled="true"></div></details></div></div></section>
<section class="cy-panel cy-gpu" data-status="unknown" aria-label="SQZ GPU 实际采集状态">
<div class="cy-panel-head"><div><span class="cy-section-id cy-mono">02 / COMPUTE</span><h2>SQZ GPU</h2></div><span class="cy-gpu-badge cy-mono" data-gpu-state>UNKNOWN</span></div>
<div class="cy-gpu-overview"><div class="cy-reactor" aria-hidden="true"><span class="cy-wire cy-wire-left"></span><span class="cy-wire cy-wire-right"></span><div class="cy-core"><div class="cy-energy-ring"></div><div class="cy-chip"><strong>GPU</strong><span class="cy-mono">SQZ / STATUS</span></div></div></div><div class="cy-metrics">
<div><span class="cy-metric-label">利用率</span><span class="cy-metric-value"><span data-gpu-util>—</span><small> %</small></span></div>
<div><span class="cy-metric-label">显存占用</span><span class="cy-metric-value"><span data-gpu-memory>—</span><small> GiB</small></span></div>
<div><span class="cy-metric-label">温度</span><span class="cy-metric-value"><span data-gpu-temp>—</span><small> °C</small></span></div></div></div><p class="cy-gpu-note" data-gpu-note>尚未取得有效读数。</p>
<div class="cy-gpu-times"><span data-gpu-observed>末次成功：UNKNOWN</span><span data-gpu-checked>最近检查：UNKNOWN</span></div>
<div class="cy-gpu-footer"><span data-gpu-total>总显存：UNKNOWN</span><span>GPU 活动不代表科研验收通过</span></div><details class="cy-history"><summary>全部 GPU 与已观测进程</summary><ul class="cy-agent-log" data-gpu-list><li>UNKNOWN</li></ul></details></section>
<div class="cy-duo">
<section class="cy-panel cy-code" data-active="false" data-engine-state="UNKNOWN" aria-label="Codex 实际状态">
<div class="cy-panel-head"><div><span class="cy-section-id cy-mono">03 / EXECUTOR</span><h2>Codex · David</h2></div><span class="cy-agent-badge" data-code-badge>UNKNOWN</span></div>
<div class="cy-agent-hero"><div class="cy-avatar-wrap" role="img" aria-label="David Martinez 动态头像，待机动作不代表推理"><div class="cy-character cy-david" data-avatar="david"><img class="cy-sprite" data-avatar-source="david" src="/assets/david.jpg" alt=""></div></div><div class="cy-agent-title"><strong class="cy-agent-state" data-code-state>UNKNOWN</strong><p class="cy-agent-sub" data-code-sub>尚未取得状态观测。</p></div></div>
<p class="cy-agent-phase" data-code-phase>当前阶段：UNKNOWN</p><div class="cy-agent-footer"><span class="cy-mono" data-code-session>SESSION: UNKNOWN</span><span>额度：未知</span></div><details class="cy-history" data-roomy-details><summary>Codex 尝试与会话详情</summary><ul class="cy-agent-log" data-code-log><li>UNKNOWN · 等待后台缓存。</li></ul></details></section>
<div class="cy-bridge" aria-hidden="true"><div class="cy-bridge-rail"></div><span class="cy-packet"></span><span class="cy-bridge-label cy-mono">STAGE CHANGE</span></div>
<section class="cy-panel cy-claude" data-active="false" data-engine-state="UNKNOWN" aria-label="Claude 实际状态">
<div class="cy-panel-head"><div><span class="cy-section-id cy-mono">04 / REVIEWER</span><h2>Claude · Lucy</h2></div><span class="cy-agent-badge" data-claude-badge>UNKNOWN</span></div>
<div class="cy-agent-hero"><div class="cy-avatar-wrap" role="img" aria-label="Lucy Kushinada 动态头像，待机动作不代表推理"><div class="cy-character cy-lucy" data-avatar="lucy"><img class="cy-sprite" data-avatar-source="lucy" src="/assets/lucy.jpg" alt=""></div></div><div class="cy-agent-title"><strong class="cy-agent-state" data-claude-state>UNKNOWN</strong><p class="cy-agent-sub" data-claude-sub>尚未取得状态观测。</p></div></div>
<p class="cy-agent-phase" data-claude-phase>当前阶段：UNKNOWN</p><div class="cy-agent-footer"><span class="cy-mono" data-claude-session>SESSION: UNKNOWN</span><span>额度：未知</span></div><details class="cy-history" data-roomy-details><summary>Claude 尝试与会话详情</summary><ul class="cy-agent-log" data-claude-log><li>UNKNOWN · 等待后台缓存。</li></ul></details></section></div></main>
<footer class="cy-footer"><p class="cy-caption" role="status" aria-live="polite" aria-atomic="true" data-caption>UNKNOWN · 正在读取后台状态缓存。</p><span>状态刷新不派任务 · 提交仅入队文本分析</span></footer>
<noscript>需要启用 JavaScript 才能读取后台状态缓存；当前状态为 UNKNOWN。</noscript>
</div></body></html>'''

from .worker_web import FORM as WORKER_FORM
PAGE = PAGE.replace('<link rel="stylesheet" href="/assets/dashboard.css">', '<link rel="stylesheet" href="/assets/dashboard.css"><link rel="stylesheet" href="/assets/worker.css">')
PAGE = PAGE.replace('<script src="/assets/dashboard.js" defer></script>', '<script src="/assets/dashboard.js" defer></script><script src="/assets/worker.js" defer></script>')
PAGE = PAGE.replace('<form class="cy-composer" id="composerForm"', '<div class="cy-mission-input">' + WORKER_FORM + '<form class="cy-composer" id="composerForm"')
PAGE = PAGE.replace('</form><div class="cy-mission-sidebar">', '</form></div><div class="cy-mission-sidebar">')
PAGE = PAGE.replace('SCENE CONTROL · 监控与文本分析', 'SCENE CONTROL · Codex 执行与审核')
PAGE = PAGE.replace('状态刷新不派任务 · 提交仅入队文本分析', 'Codex 工作即时派发 · 文本分析沿用原队列')

CSS = r'''
    #scene-cyber-deck {
      --cy-bg:#080c17; --cy-panel:#101725; --cy-deep:#0a101c; --cy-line:#263449;
      --cy-text:#edf5ff; --cy-muted:#9baec5; --cy-cyan:#6ceee6; --cy-pink:#e8a1ff;
      --cy-gold:#f2d77d; --cy-green:#a5f4be; --cy-glow: .28;
      background:radial-gradient(ellipse at 90% 0%,#23213e80,transparent 44%),repeating-linear-gradient(0deg,transparent 0 39px,#6ceee606 39px 40px),repeating-linear-gradient(90deg,transparent 0 39px,#6ceee606 39px 40px),var(--cy-bg);
      color:var(--cy-text); font:400 13px/1.5 "Segoe UI","Microsoft YaHei",sans-serif;
      padding:22px; min-width:0; border:1px solid var(--cy-line); border-radius:12px;
      color-scheme:dark;
    }
    #scene-cyber-deck *,#scene-cyber-deck *::before,#scene-cyber-deck *::after {box-sizing:border-box;}
    #scene-cyber-deck [hidden] {display:none!important;}
    #scene-cyber-deck button,#scene-cyber-deck textarea,#scene-cyber-deck input {font:inherit;}
    #scene-cyber-deck button {color:inherit;}
    #scene-cyber-deck .cy-mono {font-family:"Cascadia Code",Consolas,monospace;font-weight:400;}
    #scene-cyber-deck .cy-header {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;padding:0 92px 18px 1px;}
    #scene-cyber-deck .cy-brand {display:flex;align-items:center;gap:11px;}
    #scene-cyber-deck .cy-logo {width:24px;height:24px;border:1px solid var(--cy-cyan);position:relative;transform:rotate(-8deg);box-shadow:0 0 12px #6ceee61a;}
    #scene-cyber-deck .cy-logo::before,#scene-cyber-deck .cy-logo::after {content:'';position:absolute;background:var(--cy-cyan);}
    #scene-cyber-deck .cy-logo::before {width:11px;height:2px;left:5px;top:7px;}
    #scene-cyber-deck .cy-logo::after {width:6px;height:2px;left:5px;top:13px;}
    #scene-cyber-deck h1 {font:500 19px/1.3 "Cascadia Code",Consolas,monospace;letter-spacing:-.5px;margin:0;}
    #scene-cyber-deck h1 span {color:var(--cy-cyan);}
    #scene-cyber-deck .cy-subtitle {font-size:11px;letter-spacing:1.2px;color:var(--cy-muted);margin-top:3px;}
    #scene-cyber-deck .cy-live {color:var(--cy-gold);font-size:11px;border:1px solid #f2d77d45;background:#f2d77d08;padding:5px 9px;white-space:nowrap;}
    #scene-cyber-deck .cy-toolbar {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;border-top:1px solid var(--cy-line);padding:10px 0 14px;color:var(--cy-muted);font-size:11px;}
    #scene-cyber-deck .cy-toolbar-controls {display:flex;align-items:center;gap:18px;flex-wrap:wrap;}
    #scene-cyber-deck .cy-motion-label {display:flex;align-items:center;gap:6px;}
    #scene-cyber-deck input[type="checkbox"] {accent-color:var(--cy-cyan);margin:0;width:13px;height:13px;}
    #scene-cyber-deck .cy-pause {background:transparent;border:0;padding:2px 0;color:var(--cy-text);font-size:11px;min-height:28px;}
    #scene-cyber-deck button:disabled {opacity:.42;cursor:default;}
    #scene-cyber-deck .cy-grid {display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px;}
    #scene-cyber-deck .cy-panel {position:relative;min-width:0;background:var(--cy-panel);border:1px solid var(--cy-line);padding:18px;}
    #scene-cyber-deck .cy-panel::before,#scene-cyber-deck .cy-panel::after {content:'';position:absolute;width:18px;height:3px;top:-1px;background:var(--cy-panel-accent,var(--cy-cyan));}
    #scene-cyber-deck .cy-panel::before {left:-1px;}
    #scene-cyber-deck .cy-panel::after {right:-1px;}
    #scene-cyber-deck .cy-panel-head {display:flex;align-items:flex-start;justify-content:space-between;gap:9px;flex-wrap:wrap;margin-bottom:15px;}
    #scene-cyber-deck .cy-section-id {color:var(--cy-panel-accent,var(--cy-cyan));font-size:11px;letter-spacing:1px;}
    #scene-cyber-deck h2 {font-size:16px;font-weight:500;margin:2px 0 0;}
    #scene-cyber-deck .cy-runtime {color:var(--cy-muted);font-size:11px;text-align:right;}
    #scene-cyber-deck .cy-runtime output {display:block;color:var(--cy-cyan);font:400 21px/1.3 "Cascadia Code",Consolas,monospace;font-variant-numeric:tabular-nums;}
    #scene-cyber-deck .cy-task-label {font-size:11px;letter-spacing:.8px;color:var(--cy-muted);display:block;margin-bottom:7px;}
    #scene-cyber-deck textarea {color:var(--cy-text);background:var(--cy-deep);border:1px solid var(--cy-line);width:100%;min-height:79px;display:block;padding:10px 11px;resize:vertical;font-size:16px;line-height:1.55;border-radius:0;}
    #scene-cyber-deck .cy-attachments {padding:10px 0;}
    #scene-cyber-deck .cy-file-label {color:var(--cy-muted);display:block;font-size:11px;margin-bottom:5px;}
    #scene-cyber-deck input[type="file"] {display:block;max-width:100%;width:100%;min-width:0;color:var(--cy-muted);font-size:11px;}
    #scene-cyber-deck input[type="file"]::file-selector-button {border:1px solid var(--cy-line);background:#182435;color:var(--cy-text);padding:5px 9px;margin-right:8px;font:inherit;}
    #scene-cyber-deck .cy-files-summary {color:var(--cy-muted);font-size:11px;overflow-wrap:anywhere;margin-top:6px;}
    #scene-cyber-deck .cy-activity-title {display:flex;align-items:center;gap:7px;font-size:11px;color:var(--cy-muted);margin:4px 0 8px;}
    #scene-cyber-deck .cy-activity-dot {width:5px;height:5px;background:var(--cy-cyan);box-shadow:0 0 7px #6ceee650;}
    #scene-cyber-deck .cy-activity {margin:0;padding:0;list-style:none;min-height:44px;display:grid;align-content:start;gap:5px;font-size:12px;}
    #scene-cyber-deck .cy-activity li {display:flex;gap:7px;overflow-wrap:anywhere;}
    #scene-cyber-deck .cy-activity li::before {content:'›';color:var(--cy-cyan);}
    #scene-cyber-deck .cy-mission-actions {display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding-top:13px;margin-top:9px;border-top:1px solid var(--cy-line);}
    #scene-cyber-deck .cy-small {font-size:11px;color:var(--cy-muted);}
    #scene-cyber-deck .cy-primary {border:1px solid var(--cy-cyan);background:var(--cy-cyan);color:var(--cy-bg);font-weight:500;min-height:37px;padding:7px 15px;box-shadow:0 0 15px #6ceee615;}
    #scene-cyber-deck .cy-gpu {--cy-panel-accent:var(--cy-gold);display:flex;flex-direction:column;}
    #scene-cyber-deck .cy-gpu-badge {font-size:11px;color:var(--cy-gold);border:1px solid #f2d77d40;padding:3px 6px;}
    #scene-cyber-deck .cy-reactor {height:171px;position:relative;display:grid;place-items:center;margin:0 0 2px;isolation:isolate;}
    #scene-cyber-deck .cy-reactor::before {content:'';position:absolute;inset:12px 0;background:radial-gradient(ellipse at center,#6ceee610,transparent 65%);}
    #scene-cyber-deck .cy-core {width:116px;height:116px;border:1px solid #6ceee64d;display:grid;place-items:center;position:relative;border-radius:50%;background:var(--cy-deep);}
    #scene-cyber-deck .cy-core::before {content:'';position:absolute;inset:-12px;border:1px dashed #6ceee630;border-radius:50%;}
    #scene-cyber-deck .cy-energy-ring {position:absolute;inset:-5px;border-radius:50%;background:conic-gradient(from 30deg,transparent 0 56%,#6ceee638 78%,var(--cy-cyan) 93%,transparent 94%);mask:radial-gradient(transparent 66%,#000 67%);opacity:.35;}
    #scene-cyber-deck .cy-chip {width:62px;height:62px;background:#112b34;border:1px solid #6ceee680;display:grid;place-content:center;text-align:center;position:relative;box-shadow:0 0 20px #6ceee610;}
    #scene-cyber-deck .cy-chip::before,#scene-cyber-deck .cy-chip::after {content:'';position:absolute;inset:6px -6px;background:repeating-linear-gradient(0deg,transparent 0 5px,#6ceee650 5px 7px);z-index:-1;}
    #scene-cyber-deck .cy-chip::after {inset:-6px 6px;background:repeating-linear-gradient(90deg,transparent 0 5px,#6ceee650 5px 7px);}
    #scene-cyber-deck .cy-chip strong {font-size:20px;font-weight:500;letter-spacing:2px;color:var(--cy-cyan);}
    #scene-cyber-deck .cy-chip span {font-size:11px;color:var(--cy-muted);}
    #scene-cyber-deck .cy-wire {position:absolute;height:2px;width:calc(50% - 68px);top:84px;background:#6ceee620;}
    #scene-cyber-deck .cy-wire-left {left:0;transform:skewY(-15deg);transform-origin:right;}
    #scene-cyber-deck .cy-wire-right {right:0;transform:skewY(15deg);transform-origin:left;}
    #scene-cyber-deck .cy-wire::after {content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent 0 40%,var(--cy-cyan) 50%,transparent 60%);background-size:200% 100%;opacity:.2;}
    #scene-cyber-deck .cy-gpu-note {font-size:11px;color:var(--cy-muted);text-align:center;margin:0 0 14px;}
    #scene-cyber-deck .cy-metrics {display:grid;grid-template-columns:1fr 1.3fr 1fr;gap:10px;padding:13px 0;border-top:1px solid var(--cy-line);}
    #scene-cyber-deck .cy-metric-label {font-size:11px;color:var(--cy-muted);display:block;}
    #scene-cyber-deck .cy-metric-value {font:400 18px/1.5 "Cascadia Code",Consolas,monospace;white-space:nowrap;display:block;margin-top:3px;}
    #scene-cyber-deck .cy-metric-value small {font:400 11px/1.5 "Segoe UI",sans-serif;color:var(--cy-muted);}
    #scene-cyber-deck .cy-gpu-footer {display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:auto;padding-top:12px;border-top:1px solid var(--cy-line);font-size:11px;color:var(--cy-muted);}
    #scene-cyber-deck .cy-duo {grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;position:relative;}
    #scene-cyber-deck .cy-code {--cy-panel-accent:var(--cy-cyan);}
    #scene-cyber-deck .cy-claude {--cy-panel-accent:var(--cy-pink);}
    #scene-cyber-deck .cy-agent-badge {font-size:11px;color:var(--cy-muted);border:1px solid var(--cy-line);padding:3px 7px;}
    #scene-cyber-deck .cy-agent-hero {display:flex;align-items:center;gap:18px;min-height:95px;margin-top:15px;}
    #scene-cyber-deck .cy-code .cy-agent-hero {flex-direction:row-reverse;}
    #scene-cyber-deck .cy-agent-title {flex:1;min-width:0;}
    #scene-cyber-deck .cy-claude .cy-agent-title {text-align:right;}
    #scene-cyber-deck .cy-agent-state {font:400 21px/1.2 "Cascadia Code",Consolas,monospace;letter-spacing:.5px;color:var(--cy-panel-accent);display:block;overflow-wrap:anywhere;}
    #scene-cyber-deck .cy-agent-sub {font-size:12px;color:var(--cy-muted);margin:6px 0 0;}
    #scene-cyber-deck .cy-avatar-wrap {width:104px;height:110px;display:grid;place-items:center;position:relative;flex-shrink:0;}
    #scene-cyber-deck .cy-avatar-wrap::before,#scene-cyber-deck .cy-avatar-wrap::after {content:'';position:absolute;width:12px;height:12px;border-color:var(--cy-panel-accent);opacity:.5;}
    #scene-cyber-deck .cy-avatar-wrap::before {border-top:1px solid;border-left:1px solid;top:0;left:0;}
    #scene-cyber-deck .cy-avatar-wrap::after {border-bottom:1px solid;border-right:1px solid;bottom:0;right:0;}
    #scene-cyber-deck .cy-character {--cy-frame-x:0%;--cy-frame-y:0%;width:80px;height:80px;aspect-ratio:1;position:relative;flex-shrink:0;overflow:clip;border:1px solid var(--cy-line);border-radius:11px;transform-origin:center 80%;animation:cy-character-breathe 5.6s ease-in-out infinite,cy-character-blink 6.1s steps(1,end) infinite;}
    #scene-cyber-deck .cy-sprite {position:absolute;left:0;top:0;display:block;width:300%;height:200%;max-width:none;max-height:none;object-fit:contain;transform:translate(var(--cy-frame-x),var(--cy-frame-y));pointer-events:none;}
    #scene-cyber-deck .cy-lucy {animation-delay:-1.2s,-2.6s;}
    #scene-cyber-deck .cy-running [data-active="true"] .cy-character {animation-name:cy-character-breathe,cy-character-focus;animation-duration:4.2s,5.2s;}
    #scene-cyber-deck.cy-motion-off .cy-character {animation:none!important;transform:none;--cy-frame-x:0%;--cy-frame-y:0%;}
    @keyframes cy-character-breathe {0%,100%{transform:translateY(0) scale(1);}50%{transform:translateY(-2px) scale(1.012);}}
    @keyframes cy-character-blink {0%,73%,78%,100%{--cy-frame-x:0%;--cy-frame-y:0%;}74%,77%{--cy-frame-x:-33.333333%;--cy-frame-y:0%;}75%,76%{--cy-frame-x:-66.666667%;--cy-frame-y:0%;}}
    @keyframes cy-character-focus {0%,62%,100%{--cy-frame-x:-33.333333%;--cy-frame-y:-50%;}64%,68%,85%,96%{--cy-frame-x:0%;--cy-frame-y:-50%;}72%,80%{--cy-frame-x:0%;--cy-frame-y:0%;}81%,84%{--cy-frame-x:-33.333333%;--cy-frame-y:0%;}82%,83%{--cy-frame-x:-66.666667%;--cy-frame-y:0%;}}
    #scene-cyber-deck .cy-agent-log {list-style:none;margin:16px 0 0;padding:11px 0 0;border-top:1px solid var(--cy-line);display:grid;gap:6px;min-height:64px;color:var(--cy-muted);font-size:11px;}
    #scene-cyber-deck .cy-agent-log li {display:flex;gap:8px;overflow-wrap:anywhere;}
    #scene-cyber-deck .cy-agent-log li::before {content:'>';color:var(--cy-panel-accent);}
    #scene-cyber-deck .cy-agent-footer {display:flex;justify-content:space-between;gap:6px;flex-wrap:wrap;border-top:1px solid var(--cy-line);padding-top:10px;margin-top:10px;color:var(--cy-muted);font-size:11px;}
    #scene-cyber-deck .cy-bridge {position:absolute;z-index:2;left:calc(50% - 27px);width:54px;top:124px;height:38px;pointer-events:none;}
    #scene-cyber-deck .cy-bridge-rail {height:1px;background:linear-gradient(90deg,#6ceee620,#6ceee680,#e8a1ff80,#e8a1ff20);position:absolute;inset:12px 0 auto;}
    #scene-cyber-deck .cy-packet {width:8px;height:8px;transform:rotate(45deg);position:absolute;left:calc(50% - 4px);top:8px;background:var(--cy-cyan);box-shadow:0 0 10px #6ceee680;opacity:.35;}
    #scene-cyber-deck .cy-bridge-label {display:none;position:absolute;top:24px;left:-10px;right:-10px;text-align:center;font-size:11px;color:var(--cy-muted);}
    #scene-cyber-deck .cy-footer {display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding:15px 1px 0;color:var(--cy-muted);font-size:11px;}
    #scene-cyber-deck .cy-caption {color:var(--cy-cyan);margin:0;font-size:12px;}
    #scene-cyber-deck.cy-gpu-active:not(.cy-motion-off) .cy-energy-ring {animation:cy-current 2.8s linear infinite;opacity:.9;}
    #scene-cyber-deck.cy-gpu-active:not(.cy-motion-off) .cy-wire::after {animation:cy-wire-flow 1.7s linear infinite;opacity:.8;}
    #scene-cyber-deck.cy-running [data-active="true"] .cy-avatar-wrap {filter:drop-shadow(0 0 10px rgb(108 238 230 / var(--cy-glow)));}
    #scene-cyber-deck.cy-running [data-active="true"].cy-claude .cy-avatar-wrap {filter:drop-shadow(0 0 10px rgb(232 161 255 / var(--cy-glow)));}
    #scene-cyber-deck.cy-paused *,#scene-cyber-deck.cy-paused *::before,#scene-cyber-deck.cy-paused *::after {animation-play-state:paused!important;}
    @keyframes cy-current {to{transform:rotate(360deg);}}
    @keyframes cy-wire-flow {from{background-position:200% 0;}to{background-position:0% 0;}}
    @keyframes cy-deliver {from{left:0;}to{left:calc(100% - 8px);}}
    @keyframes cy-return {from{left:calc(100% - 8px);}to{left:0;}}
    @media(prefers-reduced-motion:reduce){#scene-cyber-deck *,#scene-cyber-deck *::before,#scene-cyber-deck *::after{animation:none!important;}}
    @media(min-width:681px) and (max-width:850px){
      #scene-cyber-deck .cy-metrics{grid-template-columns:1fr;gap:6px;}
      #scene-cyber-deck .cy-metrics > div{display:flex;justify-content:space-between;align-items:baseline;gap:8px;}
      #scene-cyber-deck .cy-reactor{height:125px;}
      #scene-cyber-deck .cy-core{width:92px;height:92px;}
      #scene-cyber-deck .cy-wire{top:62px;}
    }
    @media(max-width:680px){
      #scene-cyber-deck{padding:14px;}
      #scene-cyber-deck .cy-header{padding-right:85px;}
      #scene-cyber-deck h1{font-size:16px;}
      #scene-cyber-deck .cy-subtitle{font-size:11px;letter-spacing:0;}
      #scene-cyber-deck .cy-live{white-space:normal;}
      #scene-cyber-deck .cy-grid,#scene-cyber-deck .cy-duo{grid-template-columns:minmax(0,1fr);}
      #scene-cyber-deck .cy-panel{padding:15px;}
      #scene-cyber-deck .cy-mission-actions{align-items:stretch;}
      #scene-cyber-deck .cy-primary{flex:1;}
      #scene-cyber-deck .cy-metric-value{font-size:18px;}
      #scene-cyber-deck .cy-metrics{gap:8px;}
      #scene-cyber-deck .cy-agent-state{font-size:20px;}
      #scene-cyber-deck .cy-agent-hero{gap:12px;}
      #scene-cyber-deck .cy-code{grid-row:1;}
      #scene-cyber-deck .cy-bridge{position:relative;grid-row:2;left:auto;top:auto;width:100%;height:34px;}
      #scene-cyber-deck .cy-bridge-rail{inset-inline:15px;}
      #scene-cyber-deck .cy-bridge-label{display:block;top:19px;}
      #scene-cyber-deck .cy-claude{grid-row:3;}
    }
    @media(pointer:coarse){#scene-cyber-deck .cy-pause,#scene-cyber-deck .cy-motion-label,#scene-cyber-deck .cy-primary{min-height:44px;}}

html{color-scheme:dark;background:#050910}body{margin:0;padding:16px;font-family:"Segoe UI","Microsoft YaHei",sans-serif}#scene-cyber-deck{width:100%;max-width:1440px;margin:0 auto;box-sizing:border-box}#scene-cyber-deck .cy-header{padding-right:0}
#scene-cyber-deck .cy-live{white-space:normal;overflow-wrap:anywhere}#scene-cyber-deck[data-phase="live"] .cy-live{color:var(--cy-cyan);border-color:#6ceee64d}#scene-cyber-deck[data-phase="stale"] .cy-live{color:var(--cy-gold);background:#f2d77d12}
#scene-cyber-deck .cy-gpu-times{display:grid;gap:4px;font-size:11px;color:var(--cy-muted);padding:0 0 12px;overflow-wrap:anywhere}#scene-cyber-deck .cy-history{margin:10px 0;color:var(--cy-muted);font-size:11px}#scene-cyber-deck .cy-history summary{cursor:pointer;min-height:28px;padding:5px 0}#scene-cyber-deck .cy-history .cy-agent-log{margin-top:4px;min-height:0;max-height:300px;overflow:auto}
#scene-cyber-deck .cy-agent-log li,#scene-cyber-deck .cy-small,#scene-cyber-deck .cy-gpu-note{min-width:0;overflow-wrap:anywhere}#scene-cyber-deck .cy-agent-footer span{min-width:0;max-width:100%;overflow-wrap:anywhere}#scene-cyber-deck input:disabled{opacity:.55;cursor:not-allowed}#scene-cyber-deck textarea[readonly]{cursor:text}
#scene-cyber-deck .cy-observer-alert{margin:10px 0 0;padding:10px;border:1px solid #f2d77d70;background:#f2d77d0d;color:var(--cy-gold);font-size:12px;overflow-wrap:anywhere}
#scene-cyber-deck .cy-panel[data-engine-state="UNKNOWN"] .cy-agent-state,#scene-cyber-deck .cy-panel[data-engine-state="IDLE"] .cy-agent-state{color:var(--cy-muted)}#scene-cyber-deck .cy-panel[data-engine-state="STALE"] .cy-agent-state,#scene-cyber-deck .cy-panel[data-engine-state="PAUSED"] .cy-agent-state,#scene-cyber-deck .cy-panel[data-engine-state="STARTING"] .cy-agent-state{color:var(--cy-gold)}
#scene-cyber-deck .cy-gpu[data-status="ok"] .cy-gpu-badge{color:var(--cy-cyan);border-color:#6ceee64d}#scene-cyber-deck .cy-gpu[data-status="unknown"] .cy-gpu-badge{color:var(--cy-muted)}#scene-cyber-deck .cy-gpu[data-status="stale"] .cy-gpu-badge,#scene-cyber-deck .cy-gpu[data-status="degraded"] .cy-gpu-badge,#scene-cyber-deck .cy-gpu[data-status="unavailable"] .cy-gpu-badge{color:var(--cy-gold);background:#f2d77d12}#scene-cyber-deck .cy-gpu:not([data-status="ok"]) .cy-metric-value{color:var(--cy-muted)}
#scene-cyber-deck .cy-packet{opacity:0}#scene-cyber-deck.cy-transfer:not(.cy-motion-off)[data-transfer="forward"] .cy-packet{animation:cy-deliver 1.4s ease-in-out 1 both;opacity:1}#scene-cyber-deck.cy-transfer:not(.cy-motion-off)[data-transfer="reverse"] .cy-packet{animation:cy-return 1.4s ease-in-out 1 both;opacity:1;background:var(--cy-pink)}#scene-cyber-deck.cy-transfer:not(.cy-motion-off)[data-transfer="change"] .cy-packet{animation:cy-stage-pulse 1.4s ease-in-out 1 both}
@keyframes cy-stage-pulse{0%,100%{opacity:0;transform:rotate(45deg) scale(.8)}45%{opacity:1;transform:rotate(45deg) scale(1.5)}}
#scene-cyber-deck button:focus-visible,#scene-cyber-deck input:focus-visible,#scene-cyber-deck textarea:focus-visible,#scene-cyber-deck summary:focus-visible{outline:2px solid var(--cy-cyan);outline-offset:3px}
@media(max-width:680px){body{padding:0}#scene-cyber-deck{border-radius:0}#scene-cyber-deck .cy-footer>span{overflow-wrap:anywhere}}
.cy-window-hint{display:none}#scene-cyber-deck .cy-budget{margin:6px 0;color:var(--cy-cyan);font-size:12px;overflow-wrap:anywhere}#scene-cyber-deck .cy-agent-phase{margin:6px 0;color:var(--cy-muted);font-size:12px;overflow-wrap:anywhere}#scene-cyber-deck .cy-observer-summary{margin:3px 0;color:var(--cy-muted);font-size:10.5px;line-height:1.3;overflow-wrap:anywhere}#scene-cyber-deck .cy-observer-summary[data-stale="true"]{color:var(--cy-gold)}
/* Native WebView client area: critical summaries remain in flow; only details scroll. */
@media(min-width:1000px) and (min-height:540px){
 body.desktop-dashboard{height:100dvh;box-sizing:border-box;padding:8px}
 .desktop-dashboard #scene-cyber-deck{--cy-gap:clamp(6px,.9vh,10px);--cy-panel-pad:clamp(8px,1.25vh,12px);--cy-avatar:clamp(64px,10.5vh,96px);--cy-avatar-half:clamp(32px,5.25vh,48px);height:100%;max-width:none;padding:var(--cy-panel-pad);display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-rows:auto minmax(0,1fr) auto;gap:var(--cy-gap);font-size:12px;line-height:1.35}
 .desktop-dashboard #scene-cyber-deck .cy-header{grid-column:1;grid-row:1;padding:0;gap:8px;min-width:0}
 .desktop-dashboard #scene-cyber-deck .cy-brand{gap:8px}.desktop-dashboard #scene-cyber-deck .cy-logo{width:22px;height:22px}.desktop-dashboard #scene-cyber-deck h1{font-size:17px}.desktop-dashboard #scene-cyber-deck .cy-subtitle{font-size:9.5px;line-height:1.2;letter-spacing:.6px}
 .desktop-dashboard #scene-cyber-deck .cy-live{font-size:10.5px;padding:4px 7px}
 .desktop-dashboard #scene-cyber-deck .cy-toolbar{grid-column:2;grid-row:1;align-self:center;border:0;padding:0;gap:10px;font-size:10.5px}
 .desktop-dashboard #scene-cyber-deck .cy-toolbar-controls{gap:10px}.desktop-dashboard #scene-cyber-deck .cy-pause{min-height:26px;font-size:10.5px}
 .desktop-dashboard #scene-cyber-deck .cy-grid{grid-column:1/-1;grid-row:2;min-height:0;grid-template-rows:minmax(0,1.16fr) minmax(0,1fr);gap:var(--cy-gap)}
 .desktop-dashboard #scene-cyber-deck .cy-duo{min-height:0;grid-template-rows:minmax(0,1fr);gap:var(--cy-gap)}
 .desktop-dashboard #scene-cyber-deck .cy-panel{min-height:0;padding:var(--cy-panel-pad);display:flex;flex-direction:column}
 .desktop-dashboard #scene-cyber-deck .cy-panel>:not(.cy-history){flex:0 0 auto}
 .desktop-dashboard #scene-cyber-deck .cy-panel-head{margin:0 0 4px;gap:6px;align-items:center}
 .desktop-dashboard #scene-cyber-deck .cy-panel-head>div:first-child{display:flex;align-items:baseline;flex-wrap:wrap;gap:7px}
 .desktop-dashboard #scene-cyber-deck .cy-section-id{font-size:10px;letter-spacing:.5px}.desktop-dashboard #scene-cyber-deck h2{font-size:14px;line-height:1.3;margin:0}
 .desktop-dashboard #scene-cyber-deck .cy-runtime{display:flex;align-items:baseline;gap:5px;font-size:10px}.desktop-dashboard #scene-cyber-deck .cy-runtime output{font-size:18px;line-height:1.2}
 .desktop-dashboard #scene-cyber-deck .cy-task-label{font-size:10px;line-height:1.2;margin:0 0 2px}
 .desktop-dashboard #scene-cyber-deck textarea{height:40px;min-height:40px;max-height:40px;padding:4px 7px;font-size:12px;line-height:1.3;resize:none;overflow:auto}
 .desktop-dashboard #scene-cyber-deck .cy-budget{margin:4px 0;font-size:11px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-observer-alert{margin:3px 0;padding:4px 6px;font-size:10.5px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-mission-actions{padding-top:4px;margin-top:3px;gap:6px;align-items:center}.desktop-dashboard #scene-cyber-deck .cy-primary{min-height:26px;padding:3px 9px;font-size:11px}.desktop-dashboard #scene-cyber-deck .cy-small{font-size:10.5px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-history{flex:0 0 auto;min-height:20px;margin:4px 0 0;font-size:11px}
 .desktop-dashboard #scene-cyber-deck .cy-history summary{min-height:20px;padding:3px 0;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-history[open]{flex:1 1 0;min-height:20px;overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable}
 .desktop-dashboard #scene-cyber-deck .cy-history .cy-agent-log{min-height:0;max-height:none;overflow:visible;margin:5px 0 0;padding-top:5px;font-size:11px;gap:4px}
 .desktop-dashboard #scene-cyber-deck .cy-history .cy-activity{min-height:0}.desktop-dashboard #scene-cyber-deck .cy-history .cy-attachments{padding:5px 0}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-overview{display:grid;grid-template-columns:clamp(72px,12vh,100px) minmax(0,1fr);align-items:center;gap:8px}
 .desktop-dashboard #scene-cyber-deck .cy-reactor{height:clamp(72px,12vh,100px);margin:0}.desktop-dashboard #scene-cyber-deck .cy-core{width:56px;height:56px}.desktop-dashboard #scene-cyber-deck .cy-core::before{inset:-8px}.desktop-dashboard #scene-cyber-deck .cy-chip{width:38px;height:38px}.desktop-dashboard #scene-cyber-deck .cy-chip strong{font-size:14px;line-height:1.2}.desktop-dashboard #scene-cyber-deck .cy-chip span{font-size:8px;line-height:1.1}.desktop-dashboard #scene-cyber-deck .cy-wire{top:50%;width:calc(50% - 33px)}
 .desktop-dashboard #scene-cyber-deck .cy-metrics{grid-template-columns:1fr;gap:3px;padding:3px 0;border:0}
 .desktop-dashboard #scene-cyber-deck .cy-metrics>div{display:flex;align-items:baseline;justify-content:space-between;gap:6px}.desktop-dashboard #scene-cyber-deck .cy-metric-label{font-size:11px}.desktop-dashboard #scene-cyber-deck .cy-metric-value{margin:0;font-size:18px;line-height:1.2}.desktop-dashboard #scene-cyber-deck .cy-metric-value small{font-size:10px}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-note{font-size:10.5px;line-height:1.3;margin:0 0 4px;text-align:left}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-times{font-size:10px;line-height:1.3;gap:1px;padding:0 0 3px}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-footer{margin-top:0;padding-top:4px;gap:3px 8px;font-size:10px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-agent-badge{font-size:10px;padding:2px 5px}
 .desktop-dashboard #scene-cyber-deck .cy-agent-hero{min-height:0;margin-top:0;gap:10px}
 .desktop-dashboard #scene-cyber-deck .cy-avatar-wrap{width:calc(var(--cy-avatar) + 4px);height:calc(var(--cy-avatar) + 6px)}.desktop-dashboard #scene-cyber-deck .cy-character{width:var(--cy-avatar);height:var(--cy-avatar)}
 .desktop-dashboard #scene-cyber-deck .cy-agent-state{font-size:21px;line-height:1.15}.desktop-dashboard #scene-cyber-deck .cy-agent-sub{font-size:11px;line-height:1.3;margin:4px 0 0}
 .desktop-dashboard #scene-cyber-deck .cy-agent-phase{margin:4px 0;font-size:11px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-agent-footer{padding-top:4px;margin-top:0;gap:3px 6px;font-size:10px;line-height:1.3}
 .desktop-dashboard #scene-cyber-deck .cy-bridge{width:28px;left:calc(50% - 14px);top:calc(var(--cy-panel-pad) + 18px + var(--cy-avatar-half));height:30px}
 .desktop-dashboard #scene-cyber-deck .cy-footer{grid-column:1/-1;grid-row:3;padding:0;gap:3px 8px;font-size:10px;line-height:1.3}.desktop-dashboard #scene-cyber-deck .cy-caption{font-size:10.5px;line-height:1.3}
}
@media(min-width:1000px) and (min-height:540px) and (max-height:700px){
 .desktop-dashboard #scene-cyber-deck{--cy-avatar:64px;--cy-avatar-half:32px;font-size:11.5px}.desktop-dashboard #scene-cyber-deck h1{font-size:15px}.desktop-dashboard #scene-cyber-deck .cy-subtitle{font-size:9px}.desktop-dashboard #scene-cyber-deck .cy-agent-state{font-size:19px}.desktop-dashboard #scene-cyber-deck .cy-bridge{width:22px;left:calc(50% - 11px)}
}
@media(min-width:1000px) and (min-height:540px) and (max-height:620px){
 body.desktop-dashboard{padding:6px}
 .desktop-dashboard #scene-cyber-deck{--cy-gap:4px;--cy-panel-pad:7px}
 .desktop-dashboard #scene-cyber-deck .cy-panel-head{margin-bottom:3px}
 .desktop-dashboard #scene-cyber-deck .cy-budget{margin:3px 0}
 .desktop-dashboard #scene-cyber-deck .cy-observer-summary{margin:2px 0}
 .desktop-dashboard #scene-cyber-deck .cy-observer-alert{padding:3px 6px}
 .desktop-dashboard #scene-cyber-deck .cy-mission-actions{padding-top:3px;margin-top:2px}
 .desktop-dashboard #scene-cyber-deck .cy-history{margin-top:3px}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-overview{grid-template-columns:64px minmax(0,1fr)}
 .desktop-dashboard #scene-cyber-deck .cy-reactor{height:64px}.desktop-dashboard #scene-cyber-deck .cy-core{width:48px;height:48px}.desktop-dashboard #scene-cyber-deck .cy-chip{width:36px;height:36px}
 .desktop-dashboard #scene-cyber-deck .cy-metric-value{font-size:16px}
 .desktop-dashboard #scene-cyber-deck .cy-gpu-times{padding-bottom:2px}
 .desktop-dashboard #scene-cyber-deck .cy-agent-phase{margin:3px 0}
 .desktop-dashboard #scene-cyber-deck .cy-agent-footer{padding-top:3px}
}
@media(max-width:999px),(max-height:539px){.desktop-dashboard .cy-window-hint{display:block;margin:0;padding:8px 12px;color:#f2d77d;background:#18202d;font-size:12px;line-height:1.4}.desktop-dashboard #scene-cyber-deck{height:auto}.desktop-dashboard #scene-cyber-deck .cy-history{max-height:none}}
#scene-cyber-deck .cy-mission-header-tools{display:flex;align-items:center;flex-wrap:wrap;gap:8px}#scene-cyber-deck .cy-mission-layout{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:10px;min-width:0;min-height:0}
#scene-cyber-deck .cy-composer{display:flex;flex-direction:column;gap:4px;min-width:0;min-height:0}#scene-cyber-deck .cy-composer>label,#scene-cyber-deck .cy-materials label{font-size:11px;color:var(--cy-muted)}#scene-cyber-deck .cy-composer-policy{margin:0;font-size:10.5px;line-height:1.3;color:var(--cy-muted)}
#scene-cyber-deck .cy-composer textarea{height:48px;min-height:48px;max-height:none;padding:5px 7px;font-size:12px;line-height:1.35;resize:vertical}#scene-cyber-deck .cy-materials{font-size:11px;line-height:1.3}#scene-cyber-deck .cy-materials summary,#scene-cyber-deck .cy-composer-result summary{cursor:pointer;min-height:19px;padding:2px 0}#scene-cyber-deck .cy-materials textarea{height:56px;min-height:56px}
#scene-cyber-deck .cy-composer-role{display:flex;align-items:center;gap:7px;font-size:11px}#scene-cyber-deck .cy-composer-role label{flex:0 0 auto;color:var(--cy-muted)}#scene-cyber-deck select{min-width:0;max-width:100%;flex:1;color:var(--cy-text);background:var(--cy-deep);border:1px solid var(--cy-line);padding:3px 5px;font:inherit;min-height:25px}#scene-cyber-deck select:focus-visible{outline:2px solid var(--cy-cyan);outline-offset:2px}
#scene-cyber-deck .cy-composer-actions{display:flex;align-items:center;flex-wrap:wrap;gap:5px 9px}#scene-cyber-deck .cy-composer-actions a{color:var(--cy-cyan);font-size:11px}#scene-cyber-deck .cy-composer-feedback{margin:0;min-height:14px;font-size:10.5px;line-height:1.3;overflow-wrap:anywhere;color:var(--cy-muted)}#scene-cyber-deck .cy-composer-feedback[data-level="error"]{color:var(--cy-gold)}#scene-cyber-deck .cy-composer-feedback[data-level="success"]{color:var(--cy-cyan)}
#scene-cyber-deck .cy-composer-result{margin:0;font-size:11px;overflow-wrap:anywhere}#scene-cyber-deck .cy-composer-result p{margin:4px 0;line-height:1.4}#scene-cyber-deck .cy-result-summary{white-space:pre-wrap}#scene-cyber-deck .cy-composer-result .cy-agent-log{margin-top:4px;padding-top:4px;min-height:0}
#scene-cyber-deck .cy-mission-sidebar{display:flex;flex-direction:column;min-width:0;min-height:0}#scene-cyber-deck .cy-task-current{margin:0 0 3px;font-size:11px;line-height:1.35;overflow-wrap:anywhere}
@media(min-width:1000px) and (min-height:540px){
 .desktop-dashboard #scene-cyber-deck{--cy-avatar:80px;--cy-avatar-half:40px}
 .desktop-dashboard #scene-cyber-deck .cy-mission>.cy-mission-layout{flex:1 1 0;min-height:0;gap:8px}
 .desktop-dashboard #scene-cyber-deck .cy-composer{overflow:auto;overscroll-behavior:contain;padding-right:3px;scrollbar-gutter:stable}
 .desktop-dashboard #scene-cyber-deck .cy-composer>*{flex:0 0 auto}.desktop-dashboard #scene-cyber-deck .cy-composer textarea{height:48px;min-height:48px;max-height:none}
 .desktop-dashboard #scene-cyber-deck .cy-mission-sidebar>:not(.cy-history){flex:0 0 auto}
 .desktop-dashboard #scene-cyber-deck .cy-mission-sidebar .cy-budget{font-size:10.5px;line-height:1.3;margin:3px 0}.desktop-dashboard #scene-cyber-deck .cy-mission-sidebar .cy-observer-summary{font-size:10px}.desktop-dashboard #scene-cyber-deck .cy-mission-sidebar .cy-observer-alert{font-size:10px;line-height:1.25;padding:3px 5px}
 .desktop-dashboard #scene-cyber-deck .cy-mission-sidebar .cy-mission-actions{padding-top:3px;margin-top:2px}.desktop-dashboard #scene-cyber-deck .cy-mission-sidebar .cy-small{font-size:10px}
 .desktop-dashboard #scene-cyber-deck.cy-roomy .cy-composer textarea{height:62px;min-height:62px}.desktop-dashboard #scene-cyber-deck.cy-roomy .cy-composer{gap:6px}
}
@media(min-width:1000px) and (min-height:540px) and (max-height:700px){.desktop-dashboard #scene-cyber-deck{--cy-avatar:64px;--cy-avatar-half:32px}}
@media(max-width:999px){#scene-cyber-deck .cy-mission-layout{grid-template-columns:minmax(0,1fr)}}
'''

JS = r'''(() => {
  'use strict';
  const root = document.getElementById('scene-cyber-deck');
  if (!root) return;
  const q = selector => root.querySelector(selector);
  const obj = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const arr = value => Array.isArray(value) ? value : [];
  const text = (value, fallback = 'UNKNOWN', limit = 240) => {
    if (typeof value !== 'string' && typeof value !== 'number') return fallback;
    const result = String(value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim();
    return result ? result.slice(0, limit) : fallback;
  };
  const brief = (value, fallback = 'UNKNOWN', limit = 60) => {
    const full = text(value, fallback, 800);
    return full.length > limit ? full.slice(0, limit) + '…（详情）' : full;
  };
  const num = value => {
    if (typeof value !== 'number' && !(typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value))) return null;
    const result = Number(value); return Number.isFinite(result) && result >= 0 ? result : null;
  };
  const stamp = value => {
    if (value === null || value === undefined || value === '') return null;
    let result;
    if (typeof value === 'number') result = value > 1e12 ? value : value * 1000;
    else if (typeof value === 'string') result = Date.parse(value);
    return Number.isFinite(result) && result > 0 && result <= 8640000000000000 ? result : null;
  };
  const ukTimeFormat = new Intl.DateTimeFormat('en-GB', {
    timeZone:'Europe/London', year:'numeric', month:'2-digit', day:'2-digit',
    hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23', timeZoneName:'short'
  });
  const time = value => {
    const result = stamp(value); if (result === null) return 'UNKNOWN';
    const parts = ukTimeFormat.formatToParts(new Date(result));
    const zone = parts.find(part => part.type === 'timeZoneName').value;
    const local = parts.filter(part => part.type !== 'timeZoneName').map(part => part.value).join('').trim();
    return local + ' UK / ' + zone;
  };
  const set = (selector, value) => {
    const element = q(selector); const next = String(value);
    if (element && element.textContent !== next) element.textContent = next;
  };
  const list = (selector, lines) => {
    const target = q(selector); if (!target) return;
    const items = lines.slice(0, 60).map(line => { const item = document.createElement('li'); item.textContent = String(line); return item; });
    target.replaceChildren(...items);
  };
  const engineState = value => ['IDLE', 'RUNNING', 'STARTING', 'PAUSED', 'UNKNOWN'].includes(String(value).toUpperCase()) ? String(value).toUpperCase() : 'UNKNOWN';
  const labels = {IDLE:'空闲', RUNNING:'运行中', STARTING:'启动中', PAUSED:'已暂停', UNKNOWN:'未知', STALE:'观测已过期'};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const state = {data:null, transport:'unknown', receivedAt:null, lastGpu:null, busy:false, stages:new Map(), transferTimer:null, motion:true, visualPaused:false};
  const GPU_MAX_AGE_MS = 90000;
  function applyMotion() {
    root.classList.toggle('cy-motion-off', !state.motion || reduced.matches);
    root.classList.toggle('cy-paused', state.visualPaused);
    q('[data-motion]').disabled = reduced.matches;
    q('[data-motion]').checked = state.motion && !reduced.matches;
    set('[data-motion-label]', reduced.matches ? '系统已减少动效' : '动态效果');
    set('[data-pause]', state.visualPaused ? '继续动效' : '暂停动效');
    q('[data-pause]').setAttribute('aria-pressed', String(state.visualPaused));
    if (!state.motion || reduced.matches) clearTransfer();
  }
  function clearTransfer() {
    clearTimeout(state.transferTimer); root.classList.remove('cy-transfer'); delete root.dataset.transfer;
  }
  function stageChanges(data, fresh) {
    if (!fresh) { state.stages.clear(); clearTransfer(); return; }
    const next = new Map();
    for (const engine of ['codex', 'claude']) {
      for (const attempt of arr(obj(obj(data.engines)[engine]).active_attempts)) {
        const a = obj(attempt), key = text(obj(a.task).id ?? a.task, '', 100), stage = text(a.stage, '', 100);
        if (key && stage) next.set(key, {stage, engine});
      }
    }
    for (const [key, value] of next) {
      const previous = state.stages.get(key);
      if (previous && previous.stage !== value.stage && state.motion && !reduced.matches && !state.visualPaused) {
        clearTransfer();
        root.dataset.transfer = previous.engine !== value.engine ? (value.engine === 'claude' ? 'forward' : 'reverse') : 'change';
        void q('.cy-packet').offsetWidth;
        root.classList.add('cy-transfer');
        state.transferTimer = setTimeout(clearTransfer, 1500); break;
      }
    }
    state.stages = next;
  }
  function attemptsFor(data, engine) { return arr(obj(obj(data.engines)[engine]).active_attempts).map(obj).slice(0, 12); }
  function renderEngine(data, engine, fresh) {
    const key = engine === 'codex' ? 'code' : 'claude', e = obj(obj(data.engines)[engine]);
    const raw = engineState(e.state ?? e.status), shown = fresh ? raw : state.data ? 'STALE' : 'UNKNOWN';
    const attempts = attemptsFor(data, engine), attemptCount = arr(e.active_attempts).length, target = q(engine === 'codex' ? '.cy-code' : '.cy-claude');
    target.dataset.active = String(fresh && raw === 'RUNNING'); target.dataset.engineState = shown;
    set('[data-' + key + '-state]', shown);
    set('[data-' + key + '-badge]', labels[shown]);
    const controller = obj(data.controller);
    const pauseReason = text(e.paused_reason ?? e.reason ?? obj(controller.paused).reason ?? controller.pause_reason, '后台未提供原因');
    const description = !fresh ? (state.data ? '保留末次观测，当前运行情况未知。' : '尚未取得状态观测。') :
      raw === 'IDLE' ? '登记任务空闲；其他交互会话未知。头像待机不代表推理。' : raw === 'PAUSED' ? '暂停原因：' + brief(pauseReason, '后台未提供原因', 64) :
      raw === 'RUNNING' ? '后台观测到运行状态；阶段见下方。' : raw === 'STARTING' ? '后台报告启动中，尚不表示完成。' : '后台尚不能确认引擎状态。';
    set('[data-' + key + '-sub]', description);
    const stages = [...new Set(attempts.map(a => text(a.stage, 'UNKNOWN', 100)))];
    set('[data-' + key + '-phase]', (fresh ? '当前阶段：' : state.data ? '末次阶段：' : '当前阶段：') + (stages.length ? brief(stages.join(' / '), 'UNKNOWN', 48) + ' · ' + attemptCount + ' 项尝试' : fresh && raw === 'IDLE' ? '无登记活动' : 'UNKNOWN'));
    const lines = [];
    if (!fresh && state.data) lines.push('以下为末次缓存，不代表当前运行。');
    if (attemptCount > attempts.length) lines.push('列出前 ' + attempts.length + ' / ' + attemptCount + ' 项尝试。');
    if (raw === 'PAUSED') lines.push('完整暂停原因：' + pauseReason);
    for (const a of attempts) {
      lines.push('任务 ' + text(obj(a.task).id ?? a.task) + ' · 阶段 ' + text(a.stage, 'UNKNOWN', 80));
      lines.push('PID ' + text(a.pid, 'UNKNOWN', 24) + ' · 阶段起点 ' + time(a.started ?? a.started_at ?? a.created));
      if (a.birth !== undefined) lines.push('进程出生标识：' + (stamp(a.birth) !== null ? time(a.birth) : text(a.birth, 'UNKNOWN', 100)));
    }
    const last = obj(e.last_attempt);
    if (!attempts.length && Object.keys(last).length) lines.push('末次任务 ' + text(obj(last.task).id ?? last.task) + ' · ' + text(last.state ?? last.stage, 'UNKNOWN', 80));
    if (!lines.length) lines.push(fresh && raw === 'IDLE' ? '本次缓存未列出活动尝试。' : '活动尝试：UNKNOWN');
    const sessions = [...new Set(attempts.map(a => text(a.session_id ?? a.session, '', 80)).filter(Boolean))];
    const historicalSession = text(last.session_id ?? last.session, '', 80);
    const session = sessions.length ? sessions.join(' / ') : historicalSession || 'UNKNOWN';
    if (session !== 'UNKNOWN') lines.push((sessions.length ? '活动会话：' : '历史会话：') + session);
    list('[data-' + key + '-log]', lines);
    set('[data-' + key + '-session]', (sessions.length ? 'SESSION: ' : historicalSession ? 'LAST SESSION: ' : 'SESSION: ') + brief(session, 'UNKNOWN', 36));
    return raw;
  }
  function runtime(data, fresh) {
    const starts = [];
    for (const engine of ['codex', 'claude']) {
      const engineView = obj(obj(data.engines)[engine]);
      if (!['RUNNING', 'STARTING'].includes(engineState(engineView.state ?? engineView.status))) continue;
      for (const a of attemptsFor(data, engine)) { const value = stamp(a.started ?? a.started_at ?? a.created); if (value !== null) starts.push(value); }
    }
    const now = fresh ? Date.now() : stamp(data.observed_at) ?? state.receivedAt;
    if (!starts.length || now === null || Math.min(...starts) > now) return '—';
    const seconds = Math.floor((now - Math.min(...starts)) / 1000);
    const components = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
    if (!components[0]) components.shift(); return components.map(n => String(n).padStart(2, '0')).join(':');
  }
  function taskLine(task) {
    const t = obj(task); return '#' + text(t.id, '?', 60) + ' · ' + text(t.state, 'UNKNOWN', 60) + ' · ' + text(t.action, '已登记任务', 260);
  }
  function renderMission(data, fresh) {
    const mission = obj(data.mission), tasks = arr(mission.tasks).map(obj).slice(0, 100), known = Array.isArray(mission.tasks);
    const ids = new Set(arr(mission.active_task_ids).map(value => String(value)));
    const active = Array.isArray(mission.active_task_ids) ? tasks.filter(t => ids.has(String(t.id))) : tasks.filter(t => /^(RUNNING|STARTING|ACTIVE|EXECUTING|REVIEWING|IN_PROGRESS)$/i.test(String(t.state)));
    const first = active[0];
    const overview = !known ? 'UNKNOWN · 尚未取得任务缓存' : first ? text(first.state, 'UNKNOWN', 40) + ' · #' + brief(first.id, '?', 32) + ' · ' + brief(first.action, '已登记任务', 24) + (active.length > 1 ? '\n另有 ' + (active.length - 1) + ' 项登记活动，完整状态见下方详情。' : '') : tasks.length ? '当前缓存无活跃任务；登记历史见下方。' : '当前缓存未登记任务。';
    q('[data-task]').value = (!fresh && state.data ? '【末次观测，当前情况未知】\n' : '') + overview;
    set('[data-task-current]', (!fresh && state.data ? '末次登记：' : '登记任务：') + (!known ? 'UNKNOWN' : first ? text(first.state, 'UNKNOWN', 32) + ' · #' + brief(first.id, '?', 16) + (active.length > 1 ? ' · 活跃 ' + active.length + ' 项' : '') : '无活跃登记 · 历史 ' + tasks.length + ' 项'));
    const lines = [];
    if (!fresh) lines.push(state.data ? '状态未同步；下列信息仅为末次有效缓存。' : 'UNKNOWN · 等待后台状态缓存。');
    if (known) lines.push('登记任务 ' + tasks.length + ' 项 · 活跃标识 ' + (Array.isArray(mission.active_task_ids) ? mission.active_task_ids.length : 'UNKNOWN'));
    for (const t of active.slice(0, 3)) { lines.push(taskLine(t)); if (t.reason) lines.push('登记说明：' + text(t.reason)); }
    const controller = obj(data.controller);
    const pauseValue = controller.paused, pauseReason = text(obj(pauseValue).reason ?? controller.pause_reason, '后台未提供原因');
    const paused = pauseValue === true || pauseValue !== null && typeof pauseValue === 'object' && !Array.isArray(pauseValue) ? '调度已暂停：' + pauseReason + '；已启动任务以引擎观测为准' : pauseValue === false || pauseValue === null ? '调度未暂停' : '调度状态 UNKNOWN';
    set('[data-controller]', '控制器：' + (!fresh ? state.data ? 'STALE' : 'UNKNOWN' : paused.startsWith('调度已暂停') ? '调度已暂停' : paused));
    lines.push(paused);
    const counts = Object.entries(obj(controller.task_counts)).filter(([, value]) => num(value) !== null).slice(0, 8).map(([key, value]) => text(key, '?', 40) + ' ' + num(value));
    if (counts.length) lines.push('任务计数：' + counts.join(' · '));
    const reviewView = obj(controller.daily_reviews), reviews = num(controller.daily_reviews);
    set('[data-budget]', (!fresh && state.data ? '末次审核预算：' : '当日审核：') + (Object.keys(reviewView).length ? (num(reviewView.used) ?? 'UNKNOWN') + ' / ' + (num(reviewView.limit) ?? 'UNKNOWN') + (num(reviewView.remaining) !== null ? ' · 剩余 ' + num(reviewView.remaining) : '') : reviews !== null ? reviews + ' / UNKNOWN' : 'UNKNOWN') + ' · UTC 账本日 ' + text(reviewView.day, 'UNKNOWN', 24));
    if (Object.keys(reviewView).length) lines.push('当日审核（UTC账本）：' + (num(reviewView.used) ?? 'UNKNOWN') + ' / ' + (num(reviewView.limit) ?? 'UNKNOWN') + (num(reviewView.remaining) !== null ? ' · 剩余 ' + num(reviewView.remaining) : '') + (reviewView.day ? ' · UTC 账本日 ' + text(reviewView.day, '', 24) : ''));
    else if (reviews !== null) lines.push('当日审核计数（UTC账本）：' + reviews);
    if (controller.source_sha256) lines.push('控制器源码：' + text(controller.source_sha256, 'UNKNOWN', 16));
    list('[data-activity]', lines.length ? lines : ['UNKNOWN · 尚无可见执行摘要。']);
    const history = tasks.map(t => taskLine(t) + ' · 创建 ' + time(t.created) + ' · 更新 ' + time(t.updated) + ' · 返工 ' + (num(t.reworks) ?? 'UNKNOWN') + (t.reason ? ' · ' + text(t.reason, '', 160) : ''));
    list('[data-task-history]', history.length ? history : [known ? '本次缓存无登记任务。' : 'UNKNOWN']);
    set('[data-observed]', '实际采集：' + time(data.observed_at));
    const observer = obj(data.research_observer);
    set('[data-observer-summary]', (!fresh && state.data ? '末次观察器：' : '观察器：') + brief(observer.transport, 'UNKNOWN', 24) + ' · ' + (observer.stale === true ? '缓存已过期' : observer.stale === false ? '缓存未过期' : '时效 UNKNOWN'));
    q('[data-observer-summary]').dataset.stale = String(observer.stale === true);
    set('[data-observer]', '研究观察器：' + (!fresh && state.data ? '末次缓存 / ' : '') + text(observer.transport) + ' · ' + (observer.stale === true ? '缓存已过期' : observer.stale === false ? '缓存未过期' : '时效 UNKNOWN') + ' · 采集 ' + time(observer.observed_at) + (num(observer.age_seconds) !== null ? ' · 距采集 ' + num(observer.age_seconds) + ' 秒' : ''));
    const rawSignals = observer.progress_signals;
    const signalName = value => text(typeof value === 'object' && value !== null ? value.code ?? value.signal ?? value.name ?? value.type ?? value.kind : value, '', 100);
    const signals = Array.isArray(rawSignals) ? rawSignals.map(signalName).filter(Boolean) : signalName(rawSignals) ? [signalName(rawSignals)] : Object.entries(obj(rawSignals)).filter(([, value]) => value !== false && value !== null && value !== undefined).map(([key]) => text(key, '', 100));
    q('[data-observer-alert]').hidden = signals.length === 0;
    set('[data-observer-alert]', signals.length ? '研究记录需检查（缓存信号，非独立确认） · ' + signals.length + ' 项 · ' + brief(signals[0], '', 48) : '');
    list('[data-observer-signals]', signals.map(signal => '缓存信号（非独立确认）：' + signal));
    set('[data-runtime]', runtime(data, fresh));
  }
  function renderGpu(data, fresh) {
    const incoming = obj(data.gpu), givenRows = arr(incoming.gpus).map(obj);
    const hasReadings = givenRows.some(g => [g.utilization_percent, g.memory_used_mib, g.memory_total_mib, g.temperature_c].some(v => num(v) !== null));
    const useIncoming = hasReadings && stamp(incoming.observed_at) !== null;
    if (useIncoming) state.lastGpu = {gpus:givenRows, processes:arr(incoming.processes).map(obj), observed_at:incoming.observed_at};
    const saved = state.lastGpu || {}, rows = useIncoming ? givenRows : arr(saved.gpus), processes = useIncoming ? arr(incoming.processes).map(obj) : arr(saved.processes);
    const observed = useIncoming ? incoming.observed_at : saved.observed_at, observedMs = stamp(observed);
    let status = ['OK', 'DEGRADED', 'STALE', 'UNAVAILABLE', 'UNKNOWN'].includes(incoming.status) ? incoming.status : 'UNKNOWN';
    if (!fresh || !useIncoming || status === 'UNAVAILABLE' || observedMs === null || Date.now() - observedMs > GPU_MAX_AGE_MS || observedMs - Date.now() > 60000) status = rows.length ? 'STALE' : fresh && incoming.status === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'UNKNOWN';
    const primary = obj(rows[0]), utilization = num(primary.utilization_percent), used = num(primary.memory_used_mib), total = num(primary.memory_total_mib), temperature = num(primary.temperature_c);
    const active = fresh && status === 'OK' && (utilization !== null && utilization > 0 || processes.length > 0);
    root.classList.toggle('cy-gpu-active', active);
    q('.cy-gpu').dataset.status = status.toLowerCase();
    set('[data-gpu-state]', status);
    set('[data-gpu-util]', utilization === null ? '—' : String(utilization));
    set('[data-gpu-memory]', used === null ? '—' : (used / 1024).toFixed(1));
    set('[data-gpu-temp]', temperature === null ? '—' : String(temperature));
    set('[data-gpu-total]', '总显存：' + (total === null ? 'UNKNOWN' : (total / 1024).toFixed(1) + ' GiB'));
    set('[data-gpu-observed]', '末次成功：' + time(observed));
    set('[data-gpu-checked]', '最近检查：' + time(incoming.last_checked_at));
    const notes = {OK:'有效采集；电流仅表示已观测活动。', DEGRADED:'采集失败 · 保留末次成功读数，当前遥测已降级。', STALE:'STALE · 读数已过期或采集连接失败，保留末次观测。', UNAVAILABLE:'当前无法取得 GPU 遥测，无有效读数。', UNKNOWN:'尚不能确认 GPU 状态。'};
    set('[data-gpu-note]', (rows.length ? text(primary.name, 'GPU', 80) + ' · ' : '') + notes[status]);
    const lines = rows.map(g => 'GPU ' + text(g.index, '?', 8) + ' · ' + text(g.name, 'UNKNOWN', 80) + ' · 利用率 ' + (num(g.utilization_percent) ?? 'UNKNOWN') + '% · 显存 ' + (num(g.memory_used_mib) ?? 'UNKNOWN') + ' / ' + (num(g.memory_total_mib) ?? 'UNKNOWN') + ' MiB');
    for (const p of processes.slice(0, 12)) lines.push('已观测进程 · PID ' + text(p.pid, 'UNKNOWN', 24) + ' · ' + text(p.name ?? p.process_name, '名称未知', 80) + ' · ' + (num(p.memory_used_mib ?? p.used_gpu_memory_mib) ?? 'UNKNOWN') + ' MiB');
    list('[data-gpu-list]', lines.length ? lines : ['UNKNOWN · 没有可显示的 GPU 或进程读数。']);
  }
  function isFresh() {
    const observed = stamp(obj(state.data).observed_at), now = Date.now();
    return state.transport === 'fresh' && state.receivedAt !== null && now - state.receivedAt < 10000 && observed !== null && now - observed < 15000 && observed - now < 60000;
  }
  function render() {
    const data = obj(state.data), fresh = isFresh();
    root.dataset.phase = fresh ? 'live' : state.data ? 'stale' : 'unknown';
    const codex = renderEngine(data, 'codex', fresh), claude = renderEngine(data, 'claude', fresh);
    root.classList.toggle('cy-running', fresh && (codex === 'RUNNING' || claude === 'RUNNING'));
    renderMission(data, fresh); renderGpu(data, fresh);
    set('[data-connection]', '状态采集 / 只读 · ' + (fresh ? '已同步' : state.data ? 'STALE' : state.transport === 'failed' ? '无法读取' : 'UNKNOWN'));
    set('[data-caption]', fresh ? '状态缓存已同步；刷新不派任务。文本分析仅在点击提交后入队。' : state.data ? 'STALE · 无法确认当前状态；保留末次观测，运行标识与工作动效已停止。' : state.transport === 'failed' ? '无法读取后台状态缓存 · 当前状态 UNKNOWN。' : 'UNKNOWN · 正在读取后台状态缓存。');
    if (!fresh) { state.stages.clear(); clearTransfer(); }
  }
  async function refresh() {
    if (state.busy) return;
    state.busy = true; q('[data-refresh]').disabled = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/status', {method:'GET', credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}, signal:controller.signal});
      if (!response.ok) throw new Error('status unavailable');
      const data = await response.json();
      if (!data || typeof data !== 'object' || data.schema !== 1 || data.read_only !== true) throw new Error('invalid read-only snapshot');
      state.data = data; state.transport = 'fresh'; state.receivedAt = Date.now();
      render(); stageChanges(data, isFresh());
    } catch (_) { state.transport = 'failed'; render(); }
    finally { clearTimeout(timeout); state.busy = false; q('[data-refresh]').disabled = false; }
  }
  const composer = {caps:null, capBusy:false, busy:false, pollBusy:false, request:null, receipt:null, currentId:null, pollFailed:false};
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const receiptStorageKey = 'bgv.dashboard.lastTaskId';
  const terminalStates = new Set(['ACCEPTED', 'FAILED', 'REJECTED', 'CANCELLED', 'CANCELED', 'ERROR']);
  const composerFields = () => ({prompt:q('#composerPrompt').value, context:q('#composerContext').value, writer:q('#composerWriter').value});
  const fingerprint = values => JSON.stringify([values.prompt, values.context, values.writer]);
  const byteLength = value => new TextEncoder().encode(value).length;
  function feedback(message, level = '') {
    set('[data-composer-status]', message); q('[data-composer-status]').dataset.level = level;
  }
  function composerProblem(values) {
    const caps = obj(composer.caps), limits = obj(caps.limits);
    if (!composer.caps) return '提交能力尚未确认；草稿仅保留在当前页面。';
    if (caps.enabled !== true) return '提交未启用：' + text(caps.reason, '当前服务仅提供状态监控。', 160);
    if (caps.action !== 'analyze_text' || typeof caps.csrf_token !== 'string' || !caps.csrf_token || !['prompt_chars', 'context_chars', 'input_bytes', 'request_bytes'].every(key => num(limits[key]) > 0)) return '提交能力契约不完整，请刷新状态后重试。';
    if (!values.prompt.trim()) return '请输入分析问题；引用材料可留空。';
    if (!['codex', 'claude'].includes(values.writer) || !arr(caps.writers).includes(values.writer)) return '所选执行角色当前不可用。';
    if (values.prompt.length > limits.prompt_chars || values.context.length > limits.context_chars) return '输入超过字符限制：问题 ' + limits.prompt_chars + '，材料 ' + limits.context_chars + '。';
    if (byteLength(JSON.stringify({question:values.prompt, text:values.context || values.prompt})) > limits.input_bytes) return '分析输入超过服务允许的 UTF-8 字节数，请缩短文本。';
    if (byteLength(JSON.stringify({id:'00000000-0000-4000-8000-000000000000', ...values})) > limits.request_bytes) return '请求超过服务允许的字节数，请缩短文本。';
    return '';
  }
  function updateComposer(showHint = false) {
    const values = composerFields(), key = fingerprint(values), problem = composerProblem(values);
    const alreadySubmitted = composer.request && composer.request.fingerprint === key && composer.request.accepted;
    q('#composerSubmit').disabled = composer.busy || !!problem || !!alreadySubmitted;
    set('#composerSubmit', composer.busy ? '正在登记…' : alreadySubmitted ? '该输入已有回执' : composer.request && composer.request.fingerprint === key ? '重试提交（相同 ID）' : '提交文本分析');
    q('#composerForm').setAttribute('aria-busy', String(composer.busy));
    if (showHint && !composer.busy) feedback(problem || (alreadySubmitted ? '该输入已有回执；请查看任务状态，修改输入后可提交新任务。' : '可提交：仅分析所提供文本；材料留空时分析问题本身，不会自动查新或核验外部事实。'));
  }
  async function getJson(path, options = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, {credentials:'same-origin', cache:'no-store', ...options, headers:{Accept:'application/json', ...options.headers}, signal:controller.signal});
      let data = null; try { data = await response.json(); } catch (_) { /* An invalid response cannot establish acceptance. */ }
      return {ok:response.ok, status:response.status, data:obj(data)};
    } finally { clearTimeout(timeout); }
  }
  async function loadComposer() {
    if (composer.capBusy) return;
    composer.capBusy = true;
    try {
      const response = await getJson('/api/composer', {method:'GET'});
      if (!response.ok) throw new Error('capabilities unavailable');
      composer.caps = response.data;
      const limits = obj(response.data.limits);
      for (const [selector, key] of [['#composerPrompt', 'prompt_chars'], ['#composerContext', 'context_chars']]) {
        const limit = num(limits[key]); if (limit > 0 && Number.isInteger(limit)) q(selector).maxLength = limit;
      }
      updateComposer(!composer.receipt && !composer.busy);
    } catch (_) { composer.caps = null; updateComposer(); if (!composer.busy) feedback('无法读取提交能力；提交已禁用，输入草稿保留。', 'error'); }
    finally { composer.capBusy = false; }
  }
  function newUuid() {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
  }
  function showReceipt(receipt) {
    const taskState = text(receipt.state, 'UNKNOWN', 60).toUpperCase();
    const bound = taskState === 'ACCEPTED' && receipt.result_state === 'ACCEPTED_BOUND_RESULT' && receipt.result !== null && typeof receipt.result === 'object' && !Array.isArray(receipt.result);
    const unverified = taskState === 'ACCEPTED' && !bound;
    const title = unverified ? '已登记 ACCEPTED；产物未核验' : bound ? '已验收，结果绑定已核对' : '任务状态：' + taskState;
    set('[data-composer-receipt]', title + ' · #' + text(receipt.id, 'UNKNOWN', 36));
    set('[data-composer-receipt-info]', '执行 ' + text(receipt.writer, 'UNKNOWN', 16) + ' / 审核 ' + text(receipt.reviewer, 'UNKNOWN', 16) + ' · 创建 ' + time(receipt.created) + ' · 更新 ' + time(receipt.updated) + (receipt.reason ? ' · ' + text(receipt.reason, '', 400) : '') + (composer.pollFailed ? ' · STALE：任务状态读取失败，保留末次回执。' : ''));
    set('[data-composer-result]', bound ? text(obj(receipt.result).summary, '已核验结果未提供可显示摘要。', 16000) : unverified ? '产物未核验：暂不展示输出；ACCEPTED 状态本身不等于结果绑定已通过。' : '等待已验收且绑定核对通过的结果；此处不显示原始模型输出或隐藏推理。');
    list('[data-composer-citations]', bound ? arr(obj(receipt.result).citations).slice(0, 24).map(citation => {
      const c = obj(citation); return '引用 [' + (num(c.start) ?? '?') + ', ' + (num(c.end) ?? '?') + ']：' + text(c.quote, '引用文本缺失', 2000);
    }) : []);
    const link = q('[data-composer-link]'); link.hidden = false; link.href = '/api/tasks/' + receipt.id;
    q('#composerTaskDetails').dataset.level = unverified || composer.pollFailed || ['FAILED', 'REJECTED', 'CANCELLED', 'CANCELED', 'ERROR'].includes(taskState) ? 'error' : bound ? 'success' : '';
    if (root.classList.contains('cy-roomy')) q('#composerTaskDetails').open = true;
    const submissionUnverified = taskState.startsWith('SUBMISSION_') || taskState === 'UNKNOWN';
    feedback(composer.pollFailed ? '任务回执 STALE；无法确认当前进展，可点击查看任务状态重试。' : unverified ? '任务标记 ACCEPTED，但产物未核验；尚无可展示的验收结果。' : bound ? '文本分析已验收；可展开查看绑定核对通过的摘要与引用。' : '提交回执 · ' + taskState + (submissionUnverified ? ' · 是否成功入队尚未确认，请核对回执说明。' : ['QUEUED', 'REGISTERED'].includes(taskState) ? ' · 已登记，等待原有队列派发与审核。' : ' · 以登记状态与回执说明为准。') + (receipt.duplicate === true ? ' · 相同 ID 已有回执。' : ''), composer.pollFailed || unverified || submissionUnverified ? 'error' : bound ? 'success' : '');
  }
  async function pollReceipt(force = false) {
    const id = composer.currentId;
    if (!id || !uuidPattern.test(id) || composer.pollBusy || composer.busy || !force && terminalStates.has(text(obj(composer.receipt).state, '', 60).toUpperCase())) return;
    composer.pollBusy = true;
    try {
      const response = await getJson('/api/tasks/' + id, {method:'GET'});
      if (!response.ok || response.data.id !== id || typeof response.data.state !== 'string') throw new Error('receipt unavailable');
      if (composer.currentId !== id) return;
      composer.receipt = response.data; composer.pollFailed = false; showReceipt(response.data);
    } catch (_) { if (composer.currentId === id) { composer.pollFailed = true; if (composer.receipt) showReceipt(composer.receipt); else feedback('任务状态读取失败；登记是否成功尚未确认，请使用相同 ID 重试。', 'error'); } }
    finally { composer.pollBusy = false; }
  }
  async function submitComposer(event) {
    event.preventDefault(); if (composer.busy) return;
    const values = composerFields(), problem = composerProblem(values), key = fingerprint(values);
    if (problem) { updateComposer(); feedback(problem, 'error'); return; }
    if (composer.request && composer.request.fingerprint === key && composer.request.accepted) { feedback('该输入已有回执；请查看任务状态。'); return; }
    if (!composer.request || composer.request.fingerprint !== key) composer.request = {fingerprint:key, payload:{id:newUuid(), ...values}, accepted:false};
    const request = composer.request; composer.currentId = request.payload.id; composer.receipt = null; composer.pollFailed = false;
    set('[data-composer-receipt]', '等待提交回执 · #' + request.payload.id); set('[data-composer-receipt-info]', '尚未取得确认；不代表任务已入队。'); set('[data-composer-result]', ''); list('[data-composer-citations]', []);
    q('[data-composer-link]').hidden = false; q('[data-composer-link]').href = '/api/tasks/' + request.payload.id;
    composer.busy = true; updateComposer(); feedback('正在登记文本分析；请等待明确回执。');
    try {
      const response = await getJson('/api/tasks', {method:'POST', headers:{'Content-Type':'application/json', 'X-BGV-CSRF':composer.caps.csrf_token}, body:JSON.stringify(request.payload)});
      if (!response.ok) {
        feedback('登记未获成功回执（HTTP ' + response.status + '）：' + text(response.data.reason ?? response.data.error, '服务拒绝或当前不可用。', 180) + ' 输入仍保留；可显式重试。', 'error');
        if (response.status === 403) void loadComposer();
        return;
      }
      if (response.data.id !== request.payload.id || !uuidPattern.test(response.data.id) || typeof response.data.state !== 'string') throw new Error('invalid receipt');
      request.accepted = true; composer.currentId = response.data.id; composer.receipt = response.data; composer.pollFailed = false;
      try { localStorage.setItem(receiptStorageKey, response.data.id); } catch (_) { /* Storage is optional; never persist drafts, output, or credentials. */ }
      showReceipt(response.data);
    } catch (_) { feedback('登记结果尚未确认：连接中断或回执无效。草稿保留；再次提交会沿用同一 ID，避免重复派发。', 'error'); }
    finally { composer.busy = false; updateComposer(); }
  }
  const roomy = matchMedia('(min-width:1200px) and (min-height:640px)');
  function applyDensity() {
    root.classList.toggle('cy-roomy', roomy.matches);
    for (const detail of root.querySelectorAll('[data-roomy-details]')) if (!detail.dataset.manual) detail.open = roomy.matches;
  }
  for (const detail of root.querySelectorAll('[data-roomy-details]')) detail.querySelector('summary').addEventListener('click', () => { detail.dataset.manual = 'true'; });
  roomy.addEventListener('change', applyDensity); applyDensity();
  q('#composerForm').addEventListener('submit', submitComposer);
  q('#composerPrompt').addEventListener('input', () => updateComposer(true));
  q('#composerContext').addEventListener('input', () => updateComposer(true));
  q('#composerWriter').addEventListener('change', () => updateComposer(true));
  q('[data-composer-link]').addEventListener('click', event => { event.preventDefault(); q('#composerTaskDetails').open = true; void pollReceipt(true); });
  function restoreReceipt() {
    try {
      const id = localStorage.getItem(receiptStorageKey);
      if (!id || !uuidPattern.test(id)) return;
      composer.currentId = id; set('[data-composer-receipt]', '正在恢复上次任务回执 · #' + id);
      q('[data-composer-link]').hidden = false; q('[data-composer-link]').href = '/api/tasks/' + id;
      void pollReceipt(true);
    } catch (_) { /* A disabled store does not affect the current session. */ }
  }
  q('[data-refresh]').addEventListener('click', () => { void refresh(); void loadComposer(); void pollReceipt(true); });
  q('[data-pause]').addEventListener('click', () => { state.visualPaused = !state.visualPaused; applyMotion(); });
  q('[data-motion]').addEventListener('change', () => { state.motion = q('[data-motion]').checked; applyMotion(); });
  reduced.addEventListener('change', applyMotion);
  applyMotion(); render(); refresh(); updateComposer(); loadComposer(); restoreReceipt();
  setInterval(refresh, 2000);
  setInterval(pollReceipt, 2000);
  setInterval(() => { if (state.data) { if (!isFresh()) render(); else set('[data-runtime]', runtime(state.data, true)); } }, 1000);
})();'''
