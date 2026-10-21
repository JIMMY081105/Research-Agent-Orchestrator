"""Isolated Edge interaction checks with synthetic data; never dispatches a real worker."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from researchops.dashboard_server import LocalServer, resources
from researchops.desktop_bundle import source_manifest
from researchops.worker_store import WorkerError
from researchops.mission_status import phase_for


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Fixture:
    """All settings/status are illustrative. No SQLite, CLI, SSH or real port is read."""
    def __init__(self):
        self.turn = str(uuid.uuid4())
        self.session = str(uuid.uuid4())
        self.state = 'RUNNING'
        self.created = utc()
        self.updated = self.created
        self.issues = ['DEMO: supplement the evidence.']
        self.attempts = []
        self.fail_next = False
        self.events = []
        self.review_supported = True

    def change(self, state):
        self.state, self.updated = state, utc()

    def capability(self):
        return {'enabled': True, 'owner': 'SYNTHETIC_UI_FIXTURE', 'skills': [],
                'default_model': 'DEMO CODEX MODEL', 'prompt_chars': 20000}

    def submit(self, request):
        self.attempts.append(request)
        if self.fail_next:
            self.fail_next = False
            raise WorkerError('SIMULATED_UNAVAILABLE', 503)
        return {'session': self.session, 'id': request['id'], 'state': 'QUEUED'}

    def decide(self, _):
        raise WorkerError('SYNTHETIC_NO_APPROVAL_OPERATION')

    def cancel(self, _):
        raise WorkerError('SYNTHETIC_NO_CANCEL_OPERATION')

    def status(self, *_):
        review = {'id': self.turn, 'status': 'PASS' if self.state == 'REVIEW_PASS' else 'REWORK' if self.state == 'NEEDS_REWORK' else 'CALL_RESERVED',
                  'model': None, 'effort': 'high', 'permission_mode': 'dontAsk', 'tools_disabled': True,
                  'issues': self.issues if self.state == 'NEEDS_REWORK' else [],
                  'created_at': self.created, 'completed_at': self.updated}
        if self.state == 'REVIEW_PASS' and not self.review_supported:
            review['status'] = 'UNVERIFIED'
        stage = {'id': self.turn, 'state': self.state, 'phase': phase_for(self.state),
                 'model': 'DEMO CODEX MODEL', 'effort': 'high', 'permission_mode': 'approval',
                 'created': self.created, 'updated': self.updated, 'review': review}
        return {'session': self.session, 'sessions': [{'id': self.session, 'model': 'DEMO CODEX MODEL', 'workspace': 'DEMO WORKSPACE'}],
                'turns': [{'id': self.turn, 'session': self.session, 'state': self.state,
                           'prompt': '演示：比较场景资产方案，并逐阶段提交独立审核。',
                           'response': '演示：正在核对候选方案与约束。这里显示公开执行摘要。',
                           'mode': 'approval', 'effort': 'high', 'created': self.created, 'updated': self.updated}],
                'approvals': [], 'events': self.events, 'workflow': {'stages': [stage], 'master_plan': None,
                'reasoning_available': False, 'total_turns': 1, 'displayed_turns': 1}}

    def snapshot(self):
        now = utc()
        active = 'claude' if self.state == 'REVIEWING' else 'codex'
        busy = self.state in ('RUNNING', 'REVIEWING')
        engines = {}
        for name in ('codex', 'claude'):
            live = busy and name == active
            engines[name] = {'state': 'RUNNING' if live else 'IDLE', 'last_attempt': {},
                'active_attempts': [{'task': self.turn, 'stage': 'review' if name == 'claude' else 'execute', 'created': self.created}] if live else []}
        return {'schema': 1, 'read_only': True, 'observed_at': now, 'engines': engines,
            'mission': {'tasks': [], 'active_task_ids': []},
            'controller': {'paused': False, 'task_counts': {}, 'daily_reviews': {'day': now[:10], 'used': 0, 'limit': 50, 'remaining': 50}},
            'research_observer': {'transport': 'DOCUMENTATION DEMO', 'stale': False, 'observed_at': now, 'progress_signals': []},
            'gpu': {'status': 'OK', 'observed_at': now, 'last_checked_at': now, 'processes': [],
                'gpus': [{'index': 0, 'name': 'DEMO GPU', 'utilization_percent': 0, 'memory_used_mib': 0, 'memory_total_mib': 46068, 'temperature_c': 30}]}}


class Browser:
    def __init__(self, directory):
        import websocket  # Optional QA dependency; the application does not import it.
        self.sequence, self.ws = 0, None
        self.process = None
        profile = directory / 'edge-profile'
        profile.mkdir(exist_ok=False)
        edge = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        with (directory / 'edge.log').open('wb') as log:
            self.process = subprocess.Popen([str(edge), '--headless=new', '--no-first-run',
                '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--autoplay-policy=no-user-gesture-required', '--remote-debugging-port=0',
                '--user-data-dir=' + str(profile), 'about:blank'], stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, creationflags=0x08000000)
        try:
            active, deadline = profile / 'DevToolsActivePort', time.monotonic() + 15
            while not active.is_file():
                if self.process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('OWN_PREVIEW_BROWSER_START_FAILED')
                time.sleep(.1)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            port = int(active.read_text().splitlines()[0])
            with opener.open('http://127.0.0.1:' + str(port) + '/json/list', timeout=5) as response:
                page = next(p for p in json.load(response) if p.get('type') == 'page')
            self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=15, suppress_origin=True)
            self.call('Page.enable')
        except BaseException:
            self.close()
            raise

    def call(self, method, params=None):
        self.sequence += 1
        current = self.sequence
        self.ws.send(json.dumps({'id': current, 'method': method, 'params': params or {}}))
        while True:
            value = json.loads(self.ws.recv())
            if value.get('id') == current:
                if 'error' in value:
                    raise RuntimeError(value['error'])
                return value.get('result', {})

    def evaluate(self, expression):
        value = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
        if value.get('exceptionDetails'):
            raise RuntimeError(value['exceptionDetails'].get('text', 'SCRIPT_FAILED'))
        return value.get('result', {}).get('value')

    def wait(self, expression, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return True
            time.sleep(.1)
        return False

    def capture(self, path):
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})['data']))

    def size(self, width, height):
        self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False})

    def close(self):
        if self.ws:
            try:
                self.call('Browser.close')
            except Exception:
                pass
            self.ws.close()
            self.ws = None
        if self.process:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()  # Only this own newly-created process.
                self.process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capture-preview', action='store_true')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    directory = args.output.parent / ('ui-run-' + str(uuid.uuid4()))
    directory.mkdir()
    before = source_manifest(ROOT)
    fixture, checks, server, thread, browser = Fixture(), {}, None, None, None
    report = {'scope': 'SYNTHETIC_UI_INTERACTIONS_NOT_INSTALLED_ACCEPTANCE', 'model_calls': 0,
              'ssh_calls': 0, 'live_database_reads': 0, 'source_sha256': before['sha256'], 'directory': str(directory)}
    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)
    def refresh():
        browser.evaluate("document.querySelector('[data-refresh]').click()")
    try:
        server = LocalServer(('127.0.0.1', 0), fixture, resources(ROOT / 'assets/avatars'), worker=fixture)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        thread.start()
        browser = Browser(directory)
        browser.size(1536, 864)
        browser.call('Page.navigate', {'url': 'http://127.0.0.1:' + str(server.server_port)})
        check('initial_real_script_loaded', browser.wait("document.querySelector('.cy-stage-log')&&document.querySelector('[data-code-state]').textContent.includes('EXECUTING')"))
        browser.evaluate("document.querySelector('.cy-subtitle').textContent='DOCUMENTATION DEMO · NO LIVE JOBS'")
        check('initial_snapshot_does_not_invent_transfer', browser.evaluate("!document.querySelector('#scene-cyber-deck').classList.contains('cy-transfer')"))
        check('reported_model_effort_permission', browser.evaluate("document.querySelector('.cy-code .cy-agent-specs').textContent.includes('DEMO CODEX MODEL')&&document.querySelector('.cy-code .cy-agent-specs').textContent.includes('Approval needed')&&document.querySelector('.cy-code .cy-agent-specs').textContent.includes('high')"))
        check('unreported_claude_model_not_guessed', browser.evaluate("document.querySelector('.cy-claude .cy-agent-specs').textContent.includes('未上报')"))
        for width, height in ((1366, 768), (1536, 864), (1920, 1000)):
            browser.size(width, height)
            time.sleep(.2)
            geometry = browser.evaluate("(()=>{const r=e=>e.getBoundingClientRect(),panels=Array.from(document.querySelectorAll('.cy-panel')).map(r),a=r(document.querySelector('[data-avatar=david]')),b=r(document.querySelector('[data-avatar=lucy]')),m=r(document.querySelector('.cy-mission')),p=r(document.querySelector('#workerPrompt')),refs=r(document.querySelector('#workerReferences'));return {panels:panels.every(x=>x.left>=0&&x.top>=0&&x.right<=innerWidth&&x.bottom<=innerHeight),noScroll:document.documentElement.scrollHeight<=innerHeight&&document.documentElement.scrollWidth<=innerWidth,avatars:a.width>=110&&Math.abs(a.width-b.width)<1&&Math.abs(a.width-a.height)<1&&a.left<panels[2].left+panels[2].width/2&&b.left>panels[3].left+panels[3].width/2,bottom:m.bottom-p.bottom,refsAbove:refs.bottom<=p.top}})()")
            check('layout_' + str(width), geometry['panels'] and geometry['noScroll'] and geometry['avatars'] and 0 <= geometry['bottom'] < 45 and geometry['refsAbove'])
            browser.capture(directory / (str(width) + '.png'))
        browser.size(1536, 864)
        browser.evaluate("document.querySelector('#workerPrompt').value='draft survives refresh';document.querySelector('#workerPrompt').dispatchEvent(new Event('input'));document.querySelector('#workerMode').value='full';document.querySelector('#workerMode').dispatchEvent(new Event('change'))")
        check('draft_mode_does_not_relabel_running_turn', browser.evaluate("document.querySelector('.cy-code .cy-agent-specs').textContent.includes('Approval needed')"))
        fixture.change('REVIEWING');refresh()
        check('review_stage_and_forward_handoff', browser.wait("document.querySelector('[data-claude-state]').textContent.includes('REVIEWING')&&document.querySelector('#scene-cyber-deck').dataset.transfer==='forward'"))
        fixture.issues = ['<img src=x onerror="window.__injected=true"> DEMO issue']
        fixture.change('NEEDS_REWORK');refresh()
        check('rework_return_handoff', browser.wait("document.querySelector('[data-claude-state]').textContent.includes('REWORK')&&document.querySelector('#scene-cyber-deck').dataset.transfer==='reverse'"))
        check('draft_and_reference_safety', browser.evaluate("document.querySelector('#workerPrompt').value==='draft survives refresh'&&!window.__injected&&!document.querySelector('img[src=x]')&&document.querySelector('#missionConversation').textContent.includes('<img src=x')"))
        time.sleep(1.9);refresh();time.sleep(.25)
        check('unchanged_poll_does_not_replay_transfer', browser.evaluate("!document.querySelector('#scene-cyber-deck').classList.contains('cy-transfer')"))
        fixture.change('PAUSED_REVIEW');refresh()
        check('paused_review_is_blocked_not_completed', browser.wait("document.querySelector('[data-claude-state]').textContent.includes('BLOCKED')&&document.querySelector('[data-code-phase]').textContent.includes('3/4')"))
        fixture.events = [{'id':i,'turn':fixture.turn,'kind':'STATUS','body':'DEMO event '+str(i),'created':utc()} for i in range(70)]
        refresh()
        check('stage_history_has_local_scroll', browser.wait("document.querySelector('.cy-code .cy-stage-log').scrollHeight>document.querySelector('.cy-code .cy-stage-log').clientHeight"))
        browser.evaluate("(()=>{const e=document.querySelector('.cy-code .cy-stage-log');e.scrollTop=0;e.dispatchEvent(new Event('scroll'));})()")
        fixture.events.append({'id':70,'turn':fixture.turn,'kind':'STATUS','body':'DEMO event 70','created':utc()});refresh()
        check('reading_history_does_not_jump_to_latest', browser.wait("document.querySelector('.cy-code .cy-stage-log').textContent.includes('DEMO event 70')&&document.querySelector('.cy-code .cy-stage-log').scrollTop===0"))
        fixture.events = []
        check('stale_stops_active_lights', browser.evaluate("(()=>{document.dispatchEvent(new CustomEvent('bgv:status',{detail:{fresh:false,value:{engines:{}}}}));return Array.from(document.querySelectorAll('.cy-duo .cy-panel')).every(e=>e.dataset.progress==='idle')&&document.querySelector('[data-code-state]').textContent.includes('STALE')})()"))
        check('expired_timestamp_overrides_fresh_flag', browser.evaluate("(()=>{document.dispatchEvent(new CustomEvent('bgv:status',{detail:{fresh:true,value:{observed_at:'2000-01-01T00:00:00Z',engines:{codex:{state:'RUNNING'}}}}}));return document.querySelector('[data-code-state]').textContent.includes('STALE')&&!document.querySelector('#scene-cyber-deck').classList.contains('cy-transfer')})()"))
        fixture.change('REVIEW_PASS');refresh()
        check('ready_for_next_step', browser.wait("document.querySelector('[data-claude-state]').textContent.includes('可继续下一步')"))
        fixture.review_supported = False;refresh()
        check('unsupported_pass_is_not_presented_as_ready', browser.wait("document.querySelector('[data-claude-state]').textContent.includes('UNVERIFIED')&&!document.querySelector('.cy-chat-thread').textContent.includes('COMPLETED')"))
        fixture.review_supported = True;refresh()
        browser.wait("document.querySelector('[data-claude-state]').textContent.includes('可继续下一步')")
        browser.evaluate("document.querySelector('#workerPrompt').value='compare options';document.querySelector('#workerContext').value='quoted material';document.querySelector('#workerPrompt').dispatchEvent(new Event('input'))")
        fixture.fail_next = True
        browser.evaluate("document.querySelector('#workerSubmit').click()")
        check('failed_submit_retains_both_inputs', browser.wait("document.querySelector('#workerState').textContent.includes('SIMULATED_UNAVAILABLE')&&document.querySelector('#workerPrompt').value==='compare options'&&document.querySelector('#workerContext').value==='quoted material'"))
        browser.evaluate("document.querySelector('#workerSubmit').click()")
        check('successful_submit_clears_inputs', browser.wait("document.querySelector('#workerPrompt').value===''&&document.querySelector('#workerContext').value===''"))
        check('reference_and_retry_id_bound', len(fixture.attempts) == 2 and fixture.attempts[0]['id'] == fixture.attempts[1]['id'] and 'quoted material' in fixture.attempts[1]['prompt'])
        browser.evaluate("document.querySelector('#analysisTab').click()")
        check('analysis_composer_kept_at_bottom', browser.evaluate("(()=>{const p=document.querySelector('#composerPrompt').getBoundingClientRect(),m=document.querySelector('.cy-mission').getBoundingClientRect();return p.height>0&&m.bottom-p.bottom<45})()"))
        browser.evaluate("document.querySelector('#workerTab').click();document.querySelector('[data-pause]').click()")
        check('pause_stops_video', browser.evaluate("Array.from(document.querySelectorAll('[data-avatar-video]')).every(v=>v.paused)"))
        browser.evaluate("document.querySelector('[data-pause]').click()")
        check('hidden_page_stops_decorative_motion', browser.evaluate("(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));return document.querySelector('#scene-cyber-deck').classList.contains('cy-progress-hidden')&&Array.from(document.querySelectorAll('[data-avatar-video]')).every(v=>v.paused)})()"))
        browser.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
        if args.capture_preview:
            fixture.issues = ['DEMO: supplemental evidence requested.']
            fixture.change('RUNNING');refresh()
            browser.wait("document.querySelector('[data-code-state]').textContent.includes('EXECUTING')")
            frames = directory / 'frames';frames.mkdir()
            start = time.monotonic()
            for index in range(48):
                if index in (16, 32):
                    fixture.change('REVIEWING' if index == 16 else 'REVIEW_PASS');refresh()
                time.sleep(max(0, start + index / 8 - time.monotonic()))
                browser.capture(frames / (f'{index:03d}.png'))
            report['preview_frames'] = str(frames)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)[:200]
        if browser:
            try:
                browser.capture(directory / 'failure.png')
            except Exception:
                pass
    finally:
        if browser:
            browser.close()
            checks['own_browser_closed'] = browser.process.poll() is not None
        if server:
            server.shutdown();server.server_close();thread.join(timeout=5)
            checks['own_fixture_closed'] = not thread.is_alive()
        checks['source_unchanged'] = source_manifest(ROOT) == before
        report.update(checks=checks, success=bool(checks) and all(checks.values()) and 'error' not in report, completed_at=utc())
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'success': report['success'], 'checks': len(checks), 'failed': [k for k,v in checks.items() if not v], 'error': report.get('error'), 'report': str(args.output)}))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
