"""Loopback Flask/Jinja/HTMX UI for the independently installed worker."""
from pathlib import Path
import os
import uuid
import secrets
import sqlite3
import tempfile
import datetime as dt
from contextlib import closing
from flask import Flask, abort, render_template, request, send_from_directory, session, make_response, send_file
import execution

ROOT = Path(__file__).resolve().parent
OWNER = 'BGV.SceneControl.UI.v1'


def create_app(testing=False):
    app = Flask(__name__, template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
    app.testing=testing
    if testing:app.secret_key=secrets.token_bytes(32)
    else:
        import sys
        sys.path.insert(0,str(ROOT.parent))
        from researchops.desktop_recovery import ui_session_key
        app.secret_key=ui_session_key()
    app.config.update(SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_HTTPONLY=True,SESSION_REFRESH_EACH_REQUEST=False)
    app.config.update(MAX_CONTENT_LENGTH=32*1024, TEMPLATES_AUTO_RELOAD=True)
    app.config['PERMANENT_SESSION_LIFETIME']=dt.timedelta(days=365)
    if testing:
        app.testing_history=tempfile.TemporaryDirectory()
        history_path=Path(app.testing_history.name)/'history.sqlite3'
    else:history_path=Path(os.environ['LOCALAPPDATA'])/'BGVSceneControl/state/ui-history.sqlite3'
    from researchops.dashboard_bundle import safe_path
    history_path=safe_path(history_path);history_path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(history_path)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS ownership(owner TEXT NOT NULL,session TEXT NOT NULL,PRIMARY KEY(owner,session))')
        db.execute('CREATE TABLE IF NOT EXISTS browser_state(owner TEXT PRIMARY KEY,selected TEXT,nonce TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS nonces(owner TEXT NOT NULL,nonce TEXT NOT NULL,PRIMARY KEY(owner,nonce))')
        db.commit()

    def history(add=None):
        session.setdefault('client_id',str(uuid.uuid4()))
        with closing(sqlite3.connect(safe_path(history_path))) as db:
            for ident in [*session.get('owned_worker_sessions',[]),*([add] if add else [])]:
                db.execute('INSERT OR IGNORE INTO ownership VALUES(?,?)',(session['client_id'],ident))
            db.commit()
            return [r[0] for r in db.execute('SELECT session FROM ownership WHERE owner=?',(session['client_id'],))]

    def browser_state(selected=...,rotate=False):
        # Selection/nonces live on the server: a late display response cannot
        # roll them back by overwriting a signed browser cookie.
        owner=session['client_id']
        with closing(sqlite3.connect(safe_path(history_path))) as db:
            db.execute('INSERT OR IGNORE INTO browser_state VALUES(?,?,?)',(owner,session.get('worker_session'),str(uuid.uuid4())))
            if selected is not ...:db.execute('UPDATE browser_state SET selected=? WHERE owner=?',(selected,owner))
            if rotate:db.execute('UPDATE browser_state SET nonce=? WHERE owner=?',(str(uuid.uuid4()),owner))
            value=db.execute('SELECT selected,nonce FROM browser_state WHERE owner=?',(owner,)).fetchone()
            db.execute('INSERT OR IGNORE INTO nonces VALUES(?,?)',(owner,value[1]))
            db.execute('DELETE FROM nonces WHERE owner=? AND rowid NOT IN (SELECT rowid FROM nonces WHERE owner=? ORDER BY rowid DESC LIMIT 32)',(owner,owner))
            db.commit();return value

    def valid_nonce(value):
        with closing(sqlite3.connect(safe_path(history_path))) as db:
            known=db.execute('SELECT 1 FROM nonces WHERE owner=? AND nonce=?',(session['client_id'],value)).fetchone()
        return bool(known) or value in session.get('request_ids',[])
    options = dict(models=['GPT-6.1 Sol','GPT-6 Astra','GPT-6 Sol','GPT-6 Luna'],
                   efforts=['Low','Medium','High','Extra high','Max'],
                   speeds=['Standard','Fast'],permissions=['Approval needed','Full Access'],
                   modes=['Task','Plan','Goal'])

    @app.before_request
    def local_only():
        if request.remote_addr not in ('127.0.0.1','::1',None): abort(403)
        if request.host.split(':')[0] not in ('127.0.0.1','localhost'): abort(403)
        if request.method == 'POST' and request.headers.get('Origin') != request.host_url.rstrip('/'):
            abort(403)
        session.setdefault('client_id',str(uuid.uuid4()))

    @app.after_request
    def headers(response):
        csp=response.headers.get('Content-Security-Policy')
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"})
        if csp:response.headers['Content-Security-Policy']=csp
        return response

    @app.context_processor
    def context():
        live=execution.capability()
        connected=live.get('enabled') is True
        selected=dict(options)
        if connected:
            details=live.get('model_details',{})
            selected.update(models=live['models'],efforts=['Low','Medium','High','Extra high','Max'],
                speeds=['Standard','Fast'] if any('priority' in x.get('service_tiers',[]) for x in details.values()) else ['Standard'],
                modes=[m for m in options['modes'] if m.lower() in live.get('work_modes',['task'])])
        session.setdefault('csrf',secrets.token_urlsafe(32))
        if not session.permanent:session.permanent=True
        # Display polling must never age out a long draft's unused submission
        # nonce. Rotate only after an accepted submission, retaining retry IDs.
        selected_session,request_id=browser_state()
        current_settings={}
        current_goal=None
        current_model=None
        if request.endpoint in ('index','view') and selected_session:
            try:
                value=execution.status(selected_session)
                current_goal=value.get('goal')
                if value['turns']:
                    turn=value['turns'][0]
                    current_settings={'permission':'Full Access' if turn['mode']=='full' else 'Approval needed',
                        'effort':{'low':'Low','medium':'Medium','high':'High','xhigh':'Extra high','max':'Max'}.get(turn['effort'],'Extra high'),
                        'speed':'Fast' if turn.get('service_tier')=='priority' else 'Standard','mode':turn.get('work_mode','task').capitalize()}
                    if current_goal and current_goal.get('status')=='complete':current_settings['mode']='Task'
                    current_model=next((s['model'] for s in value.get('sessions',[]) if s['id']==selected_session),None)
            except (OSError,ValueError,KeyError):pass
        return dict(options=selected,connected=connected,worker=live,delivery=execution.delivery_capability(),ui_revision=ROOT.parent.parent.name if ROOT.parent.name=='source' else 'development',
                    default_model=current_model or (('gpt-6.1-sol' if 'gpt-6.1-sol' in live.get('models',[]) else live.get('default_model')) if connected else 'GPT-6.1 Sol'),current_settings=current_settings,current_goal=current_goal,
                    request_id=request_id,current_session=selected_session or '',csrf=session['csrf'])

    def owned(ident):
        if ident not in history():abort(403)

    def owned_turn(ident,turn):
        owned(ident)
        if turn not in {t['id'] for t in execution.status(ident)['turns']}:abort(403)

    @app.get('/')
    def index():
        page=request.args.get('page','prompt')
        if page not in ('prompt','progress'): abort(404)
        if request.args.get('task'):
            owned(request.args['task']);session['worker_session']=request.args['task'];browser_state(selected=request.args['task'])
        return render_template('index.html',page=page,scenario='running')

    @app.get('/view/<page>')
    def view(page):
        if page not in ('prompt','progress'): abort(404)
        if request.args.get('new')=='1':session.pop('worker_session',None);browser_state(selected=None)
        if request.args.get('task'):
            owned(request.args['task']);session['worker_session']=request.args['task'];browser_state(selected=request.args['task'])
        scenario=request.args.get('scenario','running')
        if scenario not in ('running','review','approval','blocked','complete'): abort(400)
        response=make_response(render_template('partials/'+page+'.html',scenario=scenario))
        response.headers['HX-Trigger']='taskChanged'
        return response

    @app.get('/tasks')
    def tasks():
        try:items=execution.conversations(history())
        except (OSError,ValueError,sqlite3.Error):items=[]
        return render_template('partials/tasks.html',items=items,selected=browser_state()[0])

    @app.post('/demo/message')
    def message():
        text=request.form.get('prompt','').strip()
        if not text or len(text)>20000: abort(400)
        # Render the proposed interaction only. Nothing is queued or persisted.
        return render_template('partials/message.html',text=text,
                               channel=request.form.get('channel','codex'))

    @app.post('/execute')
    def execute():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')):abort(403)
        if not valid_nonce(request.form.get('request_id')):abort(403)
        if request.form.get('session'):owned(request.form['session'])
        try:
            result=execution.submit(request.form)
            browser_state(selected=result['session'],rotate=True)
            session['worker_session']=result['session']
            session['owned_worker_sessions']=list(dict.fromkeys(session.get('owned_worker_sessions',[])+[result['session']]))[-20:]
            history(result['session'])
            response=make_response(render_template('partials/execution.html',status=execution.status(result['session']),task=result,csrf=session['csrf']))
            response.headers['HX-Trigger']='taskChanged';return response
        except (OSError,ValueError,KeyError) as error:
            reason=str(error) if isinstance(error,ValueError) else 'WORKER_UNAVAILABLE'
            return render_template('partials/execution_error.html',reason=reason),400

    @app.get('/execution/status/<ident>')
    def execution_status(ident):
        owned(ident)
        try:return render_template('partials/execution.html',status=execution.status(ident),task={'session':ident},csrf=session.get('csrf',''))
        except (OSError,ValueError,KeyError):abort(503)

    @app.post('/execution/decision')
    def decision():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')):abort(403)
        try:
            owned_turn(request.form['session'],request.form['turn'])
            value={k:request.form[k] for k in ('id','turn','decision')}
            if value['decision']=='answer':value['answers']={k[7:]:v for k,v in request.form.items() if k.startswith('answer_')}
            execution.store().decide(value)
            return execution_status(request.form['session'])
        except (OSError,ValueError,KeyError):abort(400)

    @app.post('/execution/cancel')
    def cancel():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')):abort(403)
        try:
            owned_turn(request.form['session'],request.form['id'])
            execution.store().cancel({'id':request.form['id']})
            return execution_status(request.form['session'])
        except (OSError,ValueError,KeyError):abort(400)

    @app.post('/execution/goal/resume')
    def resume_goal():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')):abort(403)
        ident=request.form.get('session');owned(ident)
        try:
            backend=execution.store();state=execution.status(ident)
            if not state.get('goal') or state['goal']['status']!='paused':abort(409)
            latest=state['turns'][0]
            if latest['state'] not in ('REVIEW_PASS','INTERRUPTED','CANCELLED') or (latest['state']!='REVIEW_PASS' and latest.get('reworks',0)>=2):abort(409)
            from researchops.dashboard_bundle import read_small_json,safe_path
            pause=safe_path(backend.runtime/'goals'/ident/'pause-request.json')
            if pause.exists():
                value=read_small_json(pause)
                if value.get('owner')!='BGV.Windows.CodexWorker.v1':abort(409)
                pause.rename(pause.with_name('pause-'+str(uuid.uuid4())+'.json'))
            value=read_small_json(safe_path(backend.runtime/'turns'/state['turns'][0]['id']/'request.json'))
            if value.get('work_mode')!='goal':abort(409)
            value.update(id=str(uuid.uuid4()),session=ident,prompt='Resume the existing goal within its original authorization. Check concrete evidence and retain all prior accounting.')
            backend.submit(value)
            return execution_status(ident)
        except (OSError,ValueError,KeyError):abort(400)

    @app.post('/execution/goal/pause')
    def pause_goal():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','invalid')):abort(403)
        ident=request.form.get('session');owned(ident)
        try:
            backend=execution.store();state=execution.status(ident)
            if not state.get('goal') or state['goal']['status']=='complete':abort(409)
            from researchops.worker_store import save,utc
            save(backend.runtime/'goals'/ident/'pause-request.json',{'owner':'BGV.Windows.CodexWorker.v1','requested_at':utc()})
            return execution_status(ident)
        except (OSError,ValueError,KeyError):abort(400)

    @app.get('/execution/progress/<ident>')
    def execution_progress(ident):
        owned(ident)
        try:return render_template('partials/live-progress.html',live=execution.status(ident))
        except (OSError,ValueError,KeyError):abort(503)

    @app.get('/avatars/<name>')
    def avatar(name):
        if name not in ('david.mp4','lucy.mp4','david.jpg','lucy.jpg'): abort(404)
        directory=ROOT.parent/'assets'
        if (directory/'avatars').is_dir():directory=directory/'avatars'
        return send_from_directory(directory,name)

    @app.get('/execution/artifacts/<ident>')
    def execution_artifacts(ident):
        owned(ident)
        try:return render_template('partials/artifacts.html',ident=ident,files=execution.artifacts(ident))
        except (OSError,ValueError):abort(503)

    @app.get('/execution/artifact/<ident>/<name>')
    def execution_artifact(ident,name):
        owned(ident)
        try:path=execution.artifact(ident,name)
        except (OSError,ValueError):abort(404)
        response=send_file(path,conditional=False)
        if path.suffix.lower()=='.html':
            response.headers['Content-Security-Policy']="sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
        return response

    @app.get('/preview-health')
    def health(): return dict(owner=OWNER,ui_only=not execution.capability().get('enabled'),pid=os.getpid(),ui_bundle_sha256=ROOT.parent.parent.name if ROOT.parent.name=='source' else 'development')
    return app


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,choices=(8878,),default=8878);args=parser.parse_args()
    from werkzeug.serving import make_server
    # Explicit loopback binding, no debugger/reloader, no production task/service changes.
    make_server('127.0.0.1',args.port,create_app(),threaded=True).serve_forever()
