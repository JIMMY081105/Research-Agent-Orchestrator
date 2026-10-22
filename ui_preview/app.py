"""Flask/Jinja/HTMX layout preview. No CLI, task database or research integration."""
from pathlib import Path
import os
from flask import Flask, abort, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent
OWNER = 'ResearchAgentOrchestrator.UI.Preview'


def create_app():
    app = Flask(__name__, template_folder=str(ROOT/'templates'), static_folder=str(ROOT/'static'))
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
    def context(): return dict(options=options)

    @app.get('/')
    def index():
        page=request.args.get('page','prompt')
        if page not in ('prompt','progress'): abort(404)
        return render_template('index.html',page=page,scenario='running')

    @app.get('/view/<page>')
    def view(page):
        if page not in ('prompt','progress'): abort(404)
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

    @app.get('/avatars/<name>')
    def avatar(name):
        if name not in ('david.mp4','lucy.mp4','david.jpg','lucy.jpg'): abort(404)
        return send_from_directory(ROOT.parent/'assets'/'avatars',name)

    @app.get('/preview-health')
    def health(): return dict(owner=OWNER,ui_only=True,pid=os.getpid())
    return app


if __name__=='__main__':
    from werkzeug.serving import make_server
    # Explicit loopback binding, no debugger/reloader, no production task/service changes.
    make_server('127.0.0.1',8877,create_app(),threaded=True).serve_forever()
