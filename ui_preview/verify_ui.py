"""Exercise the actual HTMX/Jinja preview with an isolated headless Edge profile."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import uuid
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from tools.verify_mission_ui import Browser


def manifest():
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    directory=args.output.parent/('flask-ui-'+str(uuid.uuid4()));directory.mkdir()
    checks={};before=manifest();browser=None;report=dict(scope='UI_ONLY_FLASK_JINJA_HTMX',model_calls=0,ssh_calls=0,production_database_access=0,directory=str(directory))
    def check(name,value):
        checks[name]=bool(value)
        if not value:raise AssertionError(name)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8877/preview-health',timeout=3) as r: health=json.load(r)
        check('real_preview_server_identity',health['owner']=='ResearchAgentOrchestrator.UI.Preview' and health['ui_only'])
        browser=Browser(directory);browser.size(1536,864)
        js=browser.evaluate;wait=browser.wait
        browser.call('Page.navigate',{'url':'http://127.0.0.1:8877/'})
        check('jinja_and_htmx_loaded',wait("document.querySelector('[data-view=prompt]')&&window.htmx&&htmx.version==='2.0.11'"))
        check('requested_defaults',js("document.querySelector('[name=model]').value==='GPT-6.1 Sol'&&document.querySelector('[name=effort]').value==='Extra high'"))
        check('preview_disclosure_present',js("document.body.textContent.includes('未接入模型、GPU 或任务系统')"))
        check('single_navigation_no_header_dropdown',js("!document.querySelector('#page-switch,.page-menu')&&document.querySelector('#page-name').tagName==='H1'&&!!document.querySelector('#new-chat')"))
        check('composer_explanation_removed',js("!document.querySelector('#mode-note')&&!document.querySelector('.composer').textContent.includes('不改变真实')"))
        check('memory_fraction_and_percent',js("document.querySelector('.gpu-memory').textContent.includes('12.8 / 45.0')&&document.querySelector('.memory-percent').textContent==='28%'"))
        js("document.querySelector('#prompt').value='keep my draft';document.querySelector('#prompt').dispatchEvent(new Event('input',{bubbles:true}))")
        for w,h in ((1092,565),(1366,768),(1536,864),(1920,1000)):
            browser.size(w,h)
            for page in ('progress','prompt'):
                js("document.querySelector('[data-nav="+page+"]').click()")
                check('htmx_switch_'+page+'_'+str(w),wait("document.documentElement.dataset.page==='"+page+"'"))
                result=js("(()=>{const r=e=>e.getBoundingClientRect(),inside=b=>b.width>0&&b.height>0&&b.left>=0&&b.top>=0&&b.right<=innerWidth+1&&b.bottom<=innerHeight+1, page=document.documentElement.dataset.page;return {body:document.documentElement.scrollHeight<=innerHeight&&document.documentElement.scrollWidth<=innerWidth,ui:page==='prompt'?inside(r(document.querySelector('#prompt')))&&inside(r(document.querySelector('.send')))&&inside(r(document.querySelector('.gpu-chip')))&&r(document.querySelector('.gpu-chip')).width<370:document.querySelector('.gpu-chip').getBoundingClientRect().height===0&&Array.from(document.querySelectorAll('.agent')).every(e=>inside(r(e)))}})()")
                check('layout_'+page+'_'+str(w),result['body'] and result['ui'])
                if page=='prompt':
                    for field in ('permission','model','effort','speed','mode'):
                        js("document.querySelector('[popovertarget=menu-"+field+"]').click()")
                        check('upward_menu_'+field+'_'+str(w),wait("(()=>{const m=document.querySelector('#menu-"+field+"'),b=document.querySelector('[popovertarget=menu-"+field+"]'),r=m.getBoundingClientRect(),br=b.getBoundingClientRect();return m.matches(':popover-open')&&r.height>40&&r.bottom<=br.top&&r.top>=0&&r.left>=0&&r.right<=innerWidth})()"))
                        js("document.querySelector('#menu-"+field+"').hidePopover()")
                browser.capture(directory/(page+'-'+str(w)+'.png'))
        browser.size(1536,864)
        check('draft_survives_page_swaps',js("document.querySelector('#prompt').value==='keep my draft'"))
        for field,value in (('permission','Full Access'),('speed','Fast'),('mode','Goal')):
            js("document.querySelector('[popovertarget=menu-"+field+"]').click()")
            check('picker_open_'+field,wait("document.querySelector('#menu-"+field+"').matches(':popover-open')"))
            js("Array.from(document.querySelectorAll('#menu-"+field+" [data-option]')).find(o=>o.dataset.option==='"+value+"').click()")
            check('picker_select_'+field,wait("document.querySelector('[name="+field+"]').value==='"+value+"'&&document.querySelector('[data-setting="+field+"] .setting-value').textContent==='"+value+"'&&!document.querySelector('#menu-"+field+"').matches(':popover-open')"))
        js("document.querySelector('[popovertarget=menu-permission]').click()")
        check('selected_option_focused',wait("document.activeElement?.dataset.option==='Full Access'"))
        js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowUp',bubbles:true}))")
        check('keyboard_arrow_navigation',js("document.activeElement?.dataset.option==='Approval needed'"))
        browser.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        browser.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        check('escape_closes_menu_and_returns_focus',wait("!document.querySelector('#menu-permission').matches(':popover-open')&&document.activeElement.getAttribute('popovertarget')==='menu-permission'"))
        js("document.querySelector('[data-nav=progress]').click()")
        check('sidebar_is_page_switch',wait("document.documentElement.dataset.page==='progress'&&document.querySelector('#page-name').textContent==='Progress'"))
        js("document.querySelector('[data-nav=prompt]').click()")
        check('settings_retained',wait("document.querySelector('[name=permission]')?.value==='Full Access'&&document.querySelector('[name=speed]').value==='Fast'&&document.querySelector('[name=mode]').value==='Goal'"))
        js("document.querySelector('[name=channel]').value='analysis';document.querySelector('[name=channel]').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#prompt').value='<img src=x onerror=alert(1)>';document.querySelector('.send').click()")
        check('demo_submission_through_htmx',wait("document.querySelectorAll('.bubble').length===2"))
        check('escaped_text_not_code',js("!document.querySelector('img[src=x]')&&document.querySelector('.bubble.user').textContent.includes('<img src=x')"))
        check('text_analysis_is_preview_only',js("document.querySelector('.bubble.assistant').textContent.includes('文本分析')&&document.querySelector('.bubble.assistant').textContent.includes('没有调用 Codex 或 Claude')"))
        js("document.querySelector('[data-nav=progress]').click()")
        check('progress_loaded',wait("document.documentElement.dataset.page==='progress'"))
        js("document.querySelector('[hx-get$=approval]').click()")
        check('approval_scenario',wait("!!document.querySelector('.approval-demo')"))
        js("document.querySelector('[data-preview-decision]').click()")
        check('approval_is_only_visual',js("document.querySelector('.decision-note').textContent.includes('未发送真实批准')"))
        js("document.querySelector('[hx-get$=review]').click()")
        check('review_scenario_animation',wait("!!document.querySelector('.claude.working')&&!!document.querySelector('.handoff.transmitting')"))
        check('portraits_are_square',js("Array.from(document.querySelectorAll('video')).every(v=>Math.abs(v.getBoundingClientRect().width-v.getBoundingClientRect().height)<1&&getComputedStyle(v).objectFit==='contain')"))
        js("document.querySelector('#motion-toggle').click()")
        check('motion_control_pauses_video',js("document.documentElement.classList.contains('motion-off')&&Array.from(document.querySelectorAll('video')).every(v=>v.paused)"))
        js("document.querySelector('#motion-toggle').click();document.querySelector('[data-nav=prompt]').click()")
        check('return_to_prompt',wait("!!document.querySelector('#prompt')"))
        js("document.querySelector('#new-chat').click()")
        check('new_chat_resets_ui_only',wait("document.querySelector('#prompt')?.value===''&&document.querySelectorAll('.bubble').length===0"))
        browser.capture(directory/'prompt-final.png')
    except Exception as e:
        report['error']=type(e).__name__+': '+str(e)[:200]
        if browser:
            try:browser.capture(directory/'failure.png')
            except Exception:pass
    finally:
        if browser:browser.close();checks['own_browser_closed']=browser.closed
        checks['source_unchanged']=before==manifest()
        report.update(checks=checks,files=before,success=bool(checks) and all(checks.values()) and 'error' not in report)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report.get(k) for k in ('success','error','directory')}));return 0 if report['success'] else 2


if __name__=='__main__':raise SystemExit(main())
