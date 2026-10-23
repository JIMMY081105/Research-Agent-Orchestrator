"""Loopback Flask/Jinja/HTMX UI for the independently installed worker."""
from pathlib import Path
import os
import uuid
import secrets
from flask import Flask, abort, render_template, request, send_from_directory, session
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
    app.config.update(SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_HTTPONLY=True)
    app.config.update(MAX_CONTENT_LENGTH=32*1024, TEMPLATES_AUTO_RELOAD=True)
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

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"})
        return response

    @app.context_processor
    def context():
        live=execution.capability()
        connected=live.get('enabled') is True
        selected=dict(options)
        if connected:
            selected.update(models=live['models'],efforts=['Medium','High','Extra high'],speeds=['Standard'],modes=['Task'])
        session.setdefault('csrf',secrets.token_urlsafe(32))
        session.permanent=True
        request_id=str(uuid.uuid4())
        session['request_ids']=(session.get('request_ids',[])+[request_id])[-32:]
        return dict(options=selected,connected=connected,worker=live,delivery=execution.delivery_capability(),ui_revision=ROOT.parent.parent.name if ROOT.parent.name=='source' else 'development',
                    default_model=('gpt-6.1-sol' if 'gpt-6.1-sol' in live.get('models',[]) else live.get('default_model')) if connected else 'GPT-6.1 Sol',
                    request_id=request_id,current_session=session.get('worker_session',''),csrf=session['csrf'])

    def owned(ident):
        if ident not in session.get('owned_worker_sessions',[]):abort(403)

    def owned_turn(ident,turn):
        owned(ident)
        if turn not in {t['id'] for t in execution.status(ident)['turns']}:abort(403)

    @app.get('/')
    def index():
        page=request.args.get('page','prompt')
        if page not in ('prompt','progress'): abort(404)
        return render_template('index.html',page=page,scenario='running')

    @app.get('/view/<page>')
    def view(page):
        if page not in ('prompt','progress'): abort(404)
        if request.args.get('new')=='1':session.pop('worker_session',None)
        scenario=request.args.get('scenario','running')
        if scenario not in ('running','review','approval','blocked','complete'): abort(400)
        return render_template('partials/'+page+'.html',scenario=scenario)

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
        if request.form.get('request_id') not in session.get('request_ids',[]):abort(403)
        if request.form.get('session'):owned(request.form['session'])
        try:
            result=execution.submit(request.form)
            session['worker_session']=result['session']
            session['owned_worker_sessions']=list(dict.fromkeys(session.get('owned_worker_sessions',[])+[result['session']]))[-20:]
            return render_template('partials/execution.html',status=execution.status(result['session']),task=result,csrf=session['csrf'])
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

    @app.get('/preview-health')
    def health(): return dict(owner=OWNER,ui_only=not execution.capability().get('enabled'),pid=os.getpid(),ui_bundle_sha256=ROOT.parent.parent.name if ROOT.parent.name=='source' else 'development')
    return app


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,choices=(8878,),default=8878);args=parser.parse_args()
    from werkzeug.serving import make_server
    # Explicit loopback binding, no debugger/reloader, no production task/service changes.
    make_server('127.0.0.1',args.port,create_app(),threaded=True).serve_forever()
