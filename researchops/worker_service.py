"""Independent owned worker: native Codex execution and explicit human approvals."""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from .dashboard_bundle import safe_path, read_small_json
from . import winproc
from .worker_rpc import Rpc
from .worker_store import Store, WorkerError, OWNER, BUSY, policy, save, sha, canonical, clean, utc
from .worker_review import charge, review_turn, workspace_snapshot
from .token_usage import app_server_usage

RULES = """You are the Codex executor in the user's local Scene Control application. Follow the user's task and loaded AGENTS.md/skills.
Your current owned workspace is the writable task directory. Code writes are limited to that workspace and explicit task scope in the authorized repositories: E:\\Github\\Building-Generation-Validation (existing controller) and E:\\Github\\Research-Agent-Orchestrator (newly authorized software development repository). The new software repository is separate from server building-generation code and scientific gate results. The public Buildings-Generation repository and existing research jobs remain read-only unless the user separately authorizes a concrete change.
Read C:\\Users\\User\\.claude\\INFRA.md before server/SSH work. Do not expose credentials, read auth/token files, change global authentication/billing, stop or restart old jobs, or infer dead processes from timeouts. Check existing job/process/checkpoint identities before scheduling new research work.
Do not invoke Codex, Claude, other AI agents or API endpoints recursively. An independent Claude review is performed by the host after this turn. Do not claim that you already passed that review. Do not push, create GitHub content, merge, start GPU work, or change VPN/scheduled tasks merely because Full Access is selected; task authorization still applies.
Keep final reports honest. State actual artifacts, checks and remaining gaps. Never publish hidden reasoning or credentials. Keep generated state out of Git.
After substantive actions append a factual summary through the existing F:\\Personal Data\\_archive_system\\ai_archive.py annotate tool as required by the user's standing archive rules; use platform OpenAI Codex. Do not alter existing archives.
"""


class Service:
    def __init__(self, runtime, source_sha, trigger="scheduled-worker", rpc_factory=Rpc, reviewer=review_turn):
        self.runtime = safe_path(runtime)
        self.store = Store(runtime, initialize=True)
        self.source_sha = source_sha
        self.trigger = trigger
        self.rpc_factory, self.reviewer = rpc_factory, reviewer
        self.rpc = None
        self.skills = []
        self.models = []
        self.default_model = None
        self.active_turn = None
        self.message_text = {}
        self.message_phases = {}
        self.active_writers = set()
        self.pending_terminal = None
        self.stop = threading.Event()
        self.started_at = utc()
        self.heartbeat_lock = threading.Lock()
        self.last_heartbeat = 0.0
        self.failure_details = None

    def recover(self):
        path = safe_path(self.store.runtime / "process.json")
        if path.exists():
            old = read_small_json(path)
            if old.get("owner") != OWNER:
                raise WorkerError("UNKNOWN_EXISTING_WORKER_PROCESS_RECORD")
            identity = winproc.identity(old["pid"])
            if identity == "UNKNOWN" or identity == old.get("birth"):
                raise WorkerError("PREVIOUS_WORKER_PROCESS_STILL_LIVE_OR_UNKNOWN")
        with self.store.db() as db:
            # A crash is not permission to replay a running native turn or remote experiment.
            db.execute("UPDATE turns SET state='INTERRUPTED_NEEDS_RECONCILIATION',reason='WORKER_RESTART_NO_AUTOMATIC_REPLAY',updated=? WHERE state IN ('STARTING','RUNNING','WAITING_APPROVAL','WAITING_INPUT','REVIEWING','CANCELLING','WAITING_TOOL_EXIT')", (utc(),))
            db.execute("UPDATE approvals SET state='EXPIRED',updated=? WHERE state IN ('PENDING','ANSWERED')", (utc(),))

    def start(self):
        self.recover()
        machine = read_small_json(self.runtime / "machine.json")
        def started(pid, birth):
            save(self.store.runtime / "process.json", {"owner": OWNER, "pid": pid, "birth": birth,
                 "parent_pid": os.getpid(), "source_sha256": self.source_sha, "created_at": utc()})
        self.rpc = self.rpc_factory(machine["codex"], self.store.runtime, started)
        model_rows = self.rpc.call("model/list", {}).get("data", [])
        self.models = [v["id"] for v in model_rows if type(v.get("id")) is str]
        preferred_model = next((v["id"] for v in model_rows if v.get("isDefault") is True), None)
        if not preferred_model or preferred_model not in self.models:
            raise WorkerError("NATIVE_AVAILABLE_DEFAULT_MODEL_MISSING")
        rows = self.rpc.call("skills/list", {"cwds": [str(self.store.runtime)], "forceReload": False}).get("data", [])
        seen = set()
        for row in rows:
            for skill in row.get("skills", []):
                path = skill.get("path")
                if skill.get("enabled") is not True or type(path) is not str or path in seen:
                    continue
                seen.add(path)
                self.skills.append({"id": sha(path.encode()), "name": clean(skill.get("name", "skill"), 100),
                                    "description": clean(skill.get("description", ""), 500), "path": path})
        # A zero-model native thread verifies the policy shape supported by this installed CLI.
        probe = self.rpc.call("thread/start", {"cwd": str(self.store.runtime), "ephemeral": True,
             "modelProvider": "openai", "approvalPolicy": "untrusted", "sandbox": "workspace-write", "model": preferred_model})
        if probe.get("approvalPolicy") != "untrusted" or probe.get("sandbox", {}).get("type") != "workspaceWrite":
            raise WorkerError("NATIVE_APPROVAL_POLICY_NOT_APPLIED")
        self.default_model = probe["model"]
        self.heartbeat()

    def heartbeat(self, state="RUNNING", reason=None):
        with self.heartbeat_lock:
            if state == 'RUNNING' and time.monotonic() - self.last_heartbeat < 3:
                return
            save(self.store.runtime / "service.json", {"owner": OWNER, "pid": os.getpid(), "birth": winproc.identity(os.getpid()),
                 "parent_pid": os.getppid(), "state": state, "reason": reason, "observed_at": utc(),
                 "started_at": self.started_at, "trigger": self.trigger, "source_sha256": self.source_sha,
                 "models": self.models, "default_model": self.default_model, 'failure_details': self.failure_details,
                 "skills": [{k: v for k, v in s.items() if k != "path"} for s in self.skills]})
            self.last_heartbeat = time.monotonic()

    def next_turn(self):
        with self.store.db(True) as db:
            row = db.execute("SELECT t.*,s.workspace,s.thread,s.native_session,s.model FROM turns t JOIN sessions s ON s.id=t.session WHERE t.state='QUEUED' ORDER BY t.created LIMIT 1").fetchone()
        return dict(row) if row else None

    def begin(self, turn):
        if self.models and turn['model'] not in self.models:
            raise WorkerError('OWNED_SESSION_MODEL_NO_LONGER_AVAILABLE')
        workspace = self.store.workspace(turn["session"])
        if str(workspace) != turn["workspace"]:
            raise WorkerError("WORKER_WORKSPACE_BINDING_INVALID")
        workspace.mkdir(parents=True, exist_ok=True)
        agents = safe_path(workspace / "AGENTS.md")
        if not turn["thread"] and not agents.exists():
            template = safe_path(Path(__file__).parents[1] / "config/worker-AGENTS.md")
            agents.write_bytes(template.read_bytes())
        self.store.update(turn["id"], state="STARTING")
        requested = policy(turn["mode"], workspace)
        if turn.get('kind')=='analysis':
            requested={'approvalPolicy':'untrusted','sandboxPolicy':{'type':'readOnly'}}
        if turn["thread"]:
            response = self.rpc.call("thread/resume", {"threadId": turn["thread"], "excludeTurns": True,
                                                      "cwd": str(workspace), "modelProvider": "openai",
                                                      'model': turn['model'], 'developerInstructions': RULES})
            if response.get("thread", {}).get("id") != turn["thread"]:
                raise WorkerError("WORKER_RESUME_SESSION_MISMATCH")
        else:
            response = self.rpc.call("thread/start", {"cwd": str(workspace), "modelProvider": "openai",
                "approvalPolicy": requested["approvalPolicy"], "sandbox": 'read-only' if turn.get('kind')=='analysis' else "danger-full-access" if turn["mode"] == "full" else "workspace-write",
                "developerInstructions": RULES, "model": turn["model"], "ephemeral": False})
            expected_type = requested["sandboxPolicy"]["type"]
            if response.get("sandbox", {}).get("type") != expected_type or response.get("approvalPolicy") != requested["approvalPolicy"]:
                raise WorkerError("NATIVE_PERMISSION_MODE_MISMATCH")
            turn["thread"] = response["thread"]["id"]
            turn["native_session"] = response["thread"].get("sessionId", turn["thread"])
            with self.store.db() as db:
                db.execute("UPDATE sessions SET thread=?,native_session=? WHERE id=?", (turn["thread"], turn["native_session"], turn["session"]))
        if response.get('model') != turn['model']:
            raise WorkerError('NATIVE_OWNED_SESSION_MODEL_MISMATCH')
        self.store.event(turn["session"], turn["id"], "INSTRUCTIONS", json.dumps({"sources": response.get("instructionSources", []), "mode": turn["mode"], "workspace": str(workspace)}, ensure_ascii=False))
        selected = {s["id"]: s for s in self.skills}
        prompt = turn['prompt']
        if turn.get('reworks', 0):
            repair = read_small_json(self.store.runtime / 'turns' / turn['id'] / ('repair-'+str(turn['reworks'])+'.json'))
            if (repair.get('input_hash') != turn['input_hash'] or repair.get('workspace_sha256') != workspace_snapshot(workspace)['sha256']):
                raise WorkerError('REPAIR_INPUT_CHANGED_REQUIRES_RECONCILIATION')
            prompt += '\nIndependent Claude review requests the following corrections. Preserve the original task scope and permissions; do not invoke AI.\n' + json.dumps(repair['issues'], ensure_ascii=False)
        attempt = self.store.runtime / 'turns' / turn['id'] / 'attempts' / str(turn.get('reworks', 0))
        if attempt.exists():
            raise WorkerError('ATTEMPT_ALREADY_STARTED_NEEDS_RECONCILIATION')
        attempt.mkdir(parents=True, exist_ok=False)
        save(attempt / 'request.json', {'prompt': prompt, 'input_hash': turn['input_hash'], 'created_at': utc()})
        items = [{"type": "text", "text": prompt}]
        for skill_id in json.loads(turn["skills"]):
            if skill_id not in selected:
                raise WorkerError("WORKER_SKILL_DISAPPEARED")
            skill = selected[skill_id]
            safe_path(skill["path"])
            items.append({"type": "skill", "name": skill["name"], "path": skill["path"]})
        call_id = charge(self.runtime, "codex", "worker-execute:" + turn["id"], "execute")
        turn['call_id'] = call_id
        self.store.update(turn["id"], call_id=call_id)
        response = self.rpc.call("turn/start", {"threadId": turn["thread"], "input": items, "cwd": str(workspace),
                **requested, 'model': turn['model'], "effort": turn["effort"], "summary": "none"})
        turn["native_turn"] = response["turn"]["id"]
        turn["started_monotonic"] = time.monotonic()
        turn["running_seconds"] = 0.0
        turn["last_tick"] = time.monotonic()
        self.active_turn = turn
        self.message_text = {}
        self.message_phases = {}
        self.active_writers = set()
        self.pending_terminal = None
        self.store.update(turn["id"], state="RUNNING", native_turn=turn["native_turn"])
        self.store.event(turn["session"], turn["id"], "STATUS", "Codex 已开始 · " + turn["mode"])

    def review_response(self):
        # Only an explicit native final_answer establishes finality. Unknown
        # phases retain legacy behavior; never guess from wording or order.
        has_final = 'final_answer' in self.message_phases.values()
        return clean("\n".join(text for key, text in self.message_text.items()
                              if not has_final or self.message_phases.get(key) != 'commentary'), 64000)

    def answer(self):
        if not self.active_turn or self.pending_terminal is not None:
            return
        turn = self.active_turn
        with self.store.db(True) as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM approvals WHERE turn=? AND state='ANSWERED' ORDER BY created", (turn["id"],))]
        for row in rows:
            decision = row["decision"]
            params = json.loads(row["params"])
            if row["method"] == "item/permissions/requestApproval":
                result = {"permissions": params.get("permissions", {}) if decision == "accept" else {}, "scope": "turn"}
            elif row["method"] == "item/tool/requestUserInput":
                result = json.loads(decision) if decision.startswith("{") else {"answers": {}}
            else:
                result = {"decision": decision}
            # Mark sending first. A transport crash never blindly repeats an approval.
            with self.store.db() as db:
                db.execute("UPDATE approvals SET state='SENDING',updated=? WHERE id=? AND state='ANSWERED'", (utc(), row["id"]))
            self.rpc.respond(json.loads(row["rpc_id"]), result)
            with self.store.db() as db:
                db.execute("UPDATE approvals SET state='SENT',updated=? WHERE id=?", (utc(), row["id"]))
            # Native tools can ask for several approvals concurrently. Sending
            # one reply must not hide another request or make decide() reject it.
            with self.store.db(True) as db:
                pending = [r[0] for r in db.execute(
                    "SELECT method FROM approvals WHERE turn=? AND state IN ('PENDING','ANSWERED','SENDING')",
                    (turn["id"],))]
            state = ("WAITING_INPUT" if "item/tool/requestUserInput" in pending
                     else "WAITING_APPROVAL" if pending else "RUNNING")
            self.store.update(turn["id"], state=state)

    def handle(self, value):
        turn = self.active_turn
        method, params = value.get("method", ""), value.get("params", {})
        if not turn:
            if "id" in value and method:
                self.rpc.send({"id": value["id"], "error": {"code": -32601, "message": "No owned active turn"}})
            return
        if params.get("threadId") not in (None, turn["thread"]):
            return
        if params.get("turnId") not in (None, turn["native_turn"]):
            return
        if "id" in value and method:
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                          "item/permissions/requestApproval", "item/tool/requestUserInput"):
                now = time.monotonic()
                turn["running_seconds"] += now - turn["last_tick"]
                turn["last_tick"] = now
                self.store.approval(turn, value)
            else:
                self.rpc.send({"id": value["id"], "error": {"code": -32601, "message": "Unsupported approval type; no permission granted"}})
            return
        if method == 'thread/tokenUsage/updated':
            if params.get('threadId') != turn['thread'] or params.get('turnId') != turn['native_turn']:
                return
            save(safe_path(self.runtime / 'worker/turns' / turn['id'] / 'token-usage.json'),
                 dict(call_id=turn['call_id'], session_id=turn['session'], thread_id=turn['thread'],
                      turn_id=turn['native_turn'], token_usage=app_server_usage(params), observed_at=utc()))
        elif method == "item/agentMessage/delta":
            key = params.get("itemId", "message")
            self.message_text[key] = (self.message_text.get(key, "") + params.get("delta", ""))[:64000]
            self.store.update(turn["id"], response=clean("\n".join(self.message_text.values()), 64000))
        elif method in ("item/started", "item/completed"):
            item = params.get("item", {})
            kind = item.get("type")
            if kind in ('commandExecution','fileChange'):
                if params.get('threadId') != turn['thread'] or params.get('turnId') != turn['native_turn']:
                    raise WorkerError('NATIVE_WRITER_SCOPE_MISSING')
                writer_id = item.get('id')
                if type(writer_id) is not str or not writer_id:
                    raise WorkerError('NATIVE_WRITER_ID_MISSING')
                writer_key = (kind, writer_id)
                if method == 'item/completed' and item.get('status') in ('completed','failed','declined'):
                    self.active_writers.discard(writer_key)
                else:
                    self.active_writers.add(writer_key)
            if kind == "commandExecution":
                self.store.event(turn["session"], turn["id"], "COMMAND", json.dumps({"command": clean(item.get("command", ""), 6000), "cwd": item.get("cwd"), "status": item.get("status"), "exit_code": item.get("exitCode")}, ensure_ascii=False))
            elif kind == "fileChange":
                self.store.event(turn["session"], turn["id"], "FILE_CHANGE", json.dumps({"changes": [{"path": c.get("path"), "kind": c.get("kind")} for c in item.get("changes", [])][:40], "status": item.get("status")}, ensure_ascii=False))
            elif kind == "agentMessage" and method == "item/completed":
                key = item.get("id", "message")
                self.message_text[key] = clean(item.get("text", ""), 64000)
                self.message_phases[key] = item.get('phase')
                self.store.update(turn["id"], response=clean("\n".join(self.message_text.values()), 64000))
            if self.pending_terminal is not None and not self.active_writers:
                terminal = self.pending_terminal
                self.pending_terminal = None
                self.handle(terminal)
        elif method == "serverRequest/resolved":
            with self.store.db() as db:
                db.execute("UPDATE approvals SET state='RESOLVED',updated=? WHERE turn=? AND rpc_id=?", (utc(), turn["id"], json.dumps(params.get("requestId"))))
        elif method == "turn/completed":
            native = params.get("turn", {})
            if native.get("id") != turn["native_turn"]:
                raise WorkerError("COMPLETED_TURN_ID_MISMATCH")
            if self.active_writers:
                # Native turn interruption can precede foreground command exit.
                # Keep one-writer admission closed through the actual terminal
                # command/file notifications, not just the model-turn notification.
                self.pending_terminal = value
                self.store.update(turn['id'],state='WAITING_TOOL_EXIT',reason='NATIVE_TURN_ENDED_TOOL_EXIT_UNVERIFIED')
                with self.store.db() as db:
                    db.execute("UPDATE approvals SET state='EXPIRED',updated=? WHERE turn=? AND state IN ('PENDING','ANSWERED')",(utc(),turn['id']))
                self.store.event(turn['session'],turn['id'],'STATUS','原生回合已结束；仍等待本系统命令退出，不重复派发。')
                return
            state = native.get("status")
            if state != "completed":
                # Persist fixed categories only, never raw provider responses.
                error = native.get("error") or {}
                text = str(error.get("message", "")).lower()
                reason = ("QUOTA" if any(x in text for x in ("usage limit", "quota", "rate limit"))
                          else "AUTH" if any(x in text for x in ("unauthorized", "authentication", "not logged"))
                          else "NETWORK" if any(x in text for x in ("network", "connection", "timed out"))
                          else "MODEL_UNSUPPORTED" if "not supported" in text else "NATIVE_TURN_" + str(state).upper())
                self.store.update(turn["id"], state="INTERRUPTED" if state == "interrupted" else "PAUSED_MODEL_ERROR", reason=reason)
                with self.store.db() as db:
                    db.execute("UPDATE approvals SET state='EXPIRED',updated=? WHERE turn=? AND state IN ('PENDING','ANSWERED')", (utc(), turn["id"]))
                self.active_turn = None
                if reason in ('QUOTA', 'AUTH', 'NETWORK'):
                    raise WorkerError('NATIVE_MODEL_PAUSED_' + reason)
                return
            turn["response"] = self.review_response()
            attempt = self.store.runtime / 'turns' / turn['id'] / 'attempts' / str(turn.get('reworks', 0))
            # Preserve all visible commentary separately from the terminal
            # answer. No reasoning items enter this public-message record.
            save(attempt / 'public-messages.json', {'messages': [
                {'id': key, 'phase': self.message_phases.get(key), 'text': text}
                for key, text in self.message_text.items()]})
            save(attempt / 'result.json', {'response': turn['response'], 'native_turn': turn['native_turn'], 'completed_at': utc()})
            self.store.update(turn["id"], state="REVIEWING", response=turn["response"])
            self.heartbeat()
            try:
                result = self.reviewer(self.runtime, self.store, turn, self.source_sha)
                if result['verdict'] == 'REWORK' and result.get('issues') and turn.get('reworks', 0) < 2:
                    number = turn.get('reworks', 0)+1
                    save(self.store.runtime / 'turns' / turn['id'] / ('repair-'+str(number)+'.json'),
                         {'input_hash': turn['input_hash'], 'workspace_sha256': workspace_snapshot(Path(turn['workspace']))['sha256'],
                          'issues': result['issues'], 'parent_binding': result.get('binding_sha256'), 'created_at': utc()})
                    self.store.update(turn['id'], state='QUEUED', reworks=number, reason='CLAUDE_REWORK_AUTO_QUEUED')
                    self.store.event(turn['session'], turn['id'], 'STATUS', 'Claude 退回；已自动安排第 '+str(number)+' 次修复')
                else:
                    self.store.update(turn["id"], state="REVIEW_PASS" if result["verdict"] == "PASS" else "NEEDS_REWORK",
                                      reason=None if result["verdict"] == "PASS" else "REWORK_LIMIT_OR_MISSING_FINDINGS")
            except (WorkerError, OSError, ValueError) as error:
                self.store.update(turn["id"], state="PAUSED_REVIEW", reason=str(error) if isinstance(error, WorkerError) else "REVIEW_UNVERIFIED")
            finally:
                with self.store.db() as db:
                    db.execute("UPDATE approvals SET state='EXPIRED',updated=? WHERE turn=? AND state IN ('PENDING','ANSWERED')", (utc(), turn["id"]))
                self.active_turn = None

    def tick(self):
        self.answer()
        for value in self.rpc.drain():
            self.handle(value)
        if self.active_turn:
            turn = self.active_turn
            with self.store.db(True) as db:
                row = db.execute("SELECT state,cancel_requested FROM turns WHERE id=?", (turn["id"],)).fetchone()
                state = row["state"]
            now = time.monotonic()
            if state == "RUNNING":
                turn["running_seconds"] += now - turn["last_tick"]
            turn["last_tick"] = now
            timed_out = state == "RUNNING" and turn["running_seconds"] > 3600
            if self.pending_terminal is None and state != "CANCELLING" and (row["cancel_requested"] or timed_out):
                self.rpc.call("turn/interrupt", {"threadId": turn["thread"], "turnId": turn["native_turn"]})
                # The interrupt RPC acknowledges a request, not termination.
                # Retain the owned turn and BUSY writer gate until its exact
                # native turn/completed event arrives. Never replay on timeout.
                self.store.update(turn["id"], state="CANCELLING",
                                  reason="USER_REQUESTED_CANCEL" if row["cancel_requested"]
                                  else "OWNED_TIMEOUT_WAITING_NATIVE_COMPLETION")
                self.store.event(turn["session"], turn["id"], "STATUS",
                                 "已请求中断；等待原生任务结束，不重复派发。")
        else:
            if safe_path(self.store.runtime / 'stop-when-idle.json').exists():
                self.stop.set()
                return
            if safe_path(self.store.runtime / 'admission-paused.json').exists() or safe_path(self.store.runtime / 'review-pause.json').exists():
                self.heartbeat()
                return
            turn = self.next_turn()
            if turn:
                try:
                    self.begin(turn)
                except Exception as error:
                    self.store.update(turn["id"], state="PAUSED_START", reason=str(error) if isinstance(error, WorkerError) else "WORKER_START_FAILED")
                    # turn/start may have reached the server before a transport error.
                    # Close our own retained Job rather than start a second writer.
                    raise
        self.heartbeat()

    def run(self):
        heartbeat_stop = threading.Event()
        def beat():
            while not heartbeat_stop.wait(3):
                self.heartbeat()
        try:
            self.start()
            heartbeat_thread = threading.Thread(target=beat, daemon=True)
            heartbeat_thread.start()
            while not self.stop.wait(.3):
                self.tick()
        except Exception as error:
            heartbeat_stop.set()
            self.failure_details = {'type': type(error).__name__, 'winerror': getattr(error, 'winerror', None)}
            if self.active_turn:
                self.store.update(self.active_turn["id"], state="PAUSED_CONNECTION", reason=str(error) if isinstance(error, WorkerError) else "WORKER_CONNECTION_FAILED")
            self.heartbeat("PAUSED", str(error) if isinstance(error, WorkerError) else "WORKER_SERVICE_FAILED")
            raise
        finally:
            heartbeat_stop.set()
            if self.rpc:
                self.rpc.close()
            if self.stop.is_set():
                self.heartbeat('STOPPED', 'OWNED_IDLE_SHUTDOWN')
