"""Project/goal contracts; mutation APIs lock, binding readers are pure. Never dispatches."""
import json
import datetime as dt
from pathlib import Path
import re
import uuid
from .integrity import canonical, digest, manifest, no_links, read_json, write_json

PROFILES = ("factory", "car-warehouse", "housing", "office", "museum", "stadium")
ROLES = {"coordinator": "claude", "reviewer": "claude", "worker": "codex", "final_merge": "user"}
SMOKE_ACTIONS = {"analyze_numbers", "inspect_text", "analyze_text"}
HASH = re.compile(r"[0-9a-f]{64}")
PROJECT_KEYS = {"schema","id","name","profile","kind","roles","rules_sha256","active_goal","approval_sha256","state","created","updated"}
RULE_KEYS = {"schema","project_id","profile","text","allowed_actions","readonly_roots","rules_sha256"}
GOAL_KEYS = {"schema","id","project_id","purpose","text","rules_sha256","source_sha256","plan","plan_sha256","goal_sha256"}
APPROVAL_KEYS = {"schema","project_id","goal_id","rules_sha256","goal_sha256","plan_sha256","source_sha256","roles","capabilities","authorization","time","approval_sha256"}

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _id(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value

def _text(value, minimum=1, maximum=20000):
    if (type(value) is not str or not minimum <= len(value) <= maximum or not value.strip()
            or any(ord(c)<32 and c not in "\n\r\t" for c in value)):
        raise ValueError("Bounded literal text required")
    return value

def _hash(value):
    if type(value) is not str or not HASH.fullmatch(value):
        raise ValueError("SHA256 required")
    return value

def _json(value, maximum=131072):
    try:
        raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
    except (TypeError,ValueError,OverflowError,RecursionError):
        raise ValueError("Finite JSON required") from None
    if len(raw)>maximum: raise ValueError("Governance JSON too large")
    return value

def _directory(system, project):
    return no_links(no_links(system.runtime)/"projects"/_id(project))

def _read(path):
    path=no_links(path)
    if not path.is_file() or path.stat().st_size>262144:
        raise ValueError("Missing/oversized governance record")
    return read_json(path)

def _seal(value, field):
    return {**value,field:digest(canonical(value))}

def _verify(value, keys, field):
    if type(value) is not dict or set(value)!=keys or type(value.get("schema")) is not int or value["schema"]!=1:
        raise ValueError("Unknown/missing governance fields")
    _hash(value[field])
    if digest(canonical({k:v for k,v in value.items() if k!=field}))!=value[field]:
        raise ValueError("Governance content hash mismatch")
    return value

def _immutable(path, value):
    path=no_links(path)
    if path.exists():
        if _read(path)!=value: raise ValueError("Immutable ID has different content")
        return
    no_links(path.parent).mkdir(parents=True,exist_ok=True)
    write_json(path,value)

def _actions(system, actions):
    if (type(actions) is not list or not 1<=len(actions)<=12
            or any(type(a) is not str or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}",a)
                   or a not in system.policy["actions"] for a in actions)
            or len(set(actions))!=len(actions)):
        raise ValueError("Only registered action names allowed")
    return sorted(actions)

def _roots(roots):
    if type(roots) not in (list,tuple) or len(roots)>8:
        raise ValueError("At most eight read-only roots")
    result=[]
    forbidden={".ssh",".aws",".azure",".gnupg","credentials",".env","auth.json","credentials.json"}
    for raw in roots:
        _text(raw,1,2048); p=Path(raw)
        if (not p.is_absolute() or ".." in p.parts or p==Path(p.anchor)
                or p.drive.startswith("\\\\") or any(c in raw for c in ("*","?","\n","\r"))
                or any(c.lower() in forbidden for c in p.parts)):
            raise ValueError("Scoped absolute input roots required")
        p=no_links(p)
        if not p.exists(): raise ValueError("Input root unavailable")
        if str(p).casefold() in {v.casefold() for v in result}: raise ValueError("Duplicate input root")
        result.append(str(p))
    return sorted(result)

def _rules(system, project, text, actions, roots):
    return _seal({"schema":1,"project_id":project["id"],"profile":project["profile"],
                  "text":_text(text,10,20000),"allowed_actions":_actions(system,actions),
                  "readonly_roots":_roots(roots)},"rules_sha256")

def get_project(system, project_id):
    directory=_directory(system,project_id)
    p=_read(directory/"project.json")
    if (type(p) is not dict or set(p)!=PROJECT_KEYS or type(p["schema"]) is not int or p["schema"]!=1 or p["id"]!=project_id
            or p["profile"] not in PROFILES or p["kind"] not in ("research","ops-smoke") or p["roles"]!=ROLES):
        raise ValueError("Invalid project record")
    _text(p["name"],1,120)
    r=_verify(_read(directory/"rules"/(_hash(p["rules_sha256"])+".json")),RULE_KEYS,"rules_sha256")
    if r["project_id"]!=project_id or r["profile"]!=p["profile"]: raise ValueError("Foreign rules")
    _actions(system,r["allowed_actions"]); _roots(r["readonly_roots"])
    return {**p,"rules":r,"output_root":str(directory/"outputs")}

def register_project(system, project_id, name, profile, rules_text, allowed_actions, readonly_roots=(), kind="research"):
    _id(project_id); _text(name,1,120)
    if profile not in PROFILES or kind not in ("research","ops-smoke"): raise ValueError("Unknown profile/kind")
    with system.lock():
        directory=_directory(system,project_id)
        rules=_rules(system,{"id":project_id,"profile":profile},rules_text,allowed_actions,readonly_roots)
        if kind=="ops-smoke" and set(rules["allowed_actions"])-SMOKE_ACTIONS: raise ValueError("Smoke scope")
        if (directory/"project.json").exists():
            p=get_project(system,project_id)
            if any(p[k]!=v for k,v in {"name":name,"profile":profile,"kind":kind,"rules_sha256":rules["rules_sha256"]}.items()):
                raise ValueError("ID exists; explicit update_rules required")
            return p
        now=utc()
        p={"schema":1,"id":project_id,"name":name,"profile":profile,"kind":kind,"roles":dict(ROLES),
           "rules_sha256":rules["rules_sha256"],"active_goal":None,"approval_sha256":None,
           "state":"AWAITING_GOAL","created":now,"updated":now}
        _immutable(directory/"rules"/(rules["rules_sha256"]+".json"),rules)
        write_json(directory/"project.json",p)
        return get_project(system,project_id)

def update_rules(system, project_id, rules_text, allowed_actions=None, readonly_roots=None):
    with system.lock():
        p=get_project(system,project_id)
        r=_rules(system,p,rules_text,p["rules"]["allowed_actions"] if allowed_actions is None else allowed_actions,
                 p["rules"]["readonly_roots"] if readonly_roots is None else readonly_roots)
        if p["kind"]=="ops-smoke" and set(r["allowed_actions"])-SMOKE_ACTIONS: raise ValueError("Smoke expansion")
        directory=_directory(system,project_id)
        _immutable(directory/"rules"/(r["rules_sha256"]+".json"),r)
        pointer={k:p[k] for k in PROJECT_KEYS}
        pointer.update(rules_sha256=r["rules_sha256"],state="AWAITING_GOAL",updated=utc())
        write_json(directory/"project.json",pointer)
        return get_project(system,project_id)

def _plan(system, project, plan):
    if type(plan) is not list or not 1<=len(plan)<=12: raise ValueError("Expected 1..12 tasks")
    normalized=[]
    for leaf in plan:
        if type(leaf) is not dict or set(leaf) not in ({"id","action","input"},{"id","action","input","depends_on"}):
            raise ValueError("Unknown plan fields")
        task=_id(leaf["id"])
        if leaf["action"] not in project["rules"]["allowed_actions"]: raise ValueError("Unauthorized action")
        _json(leaf["input"],system.policy["max_input_bytes"])
        system.acceptance_for(leaf["action"],leaf["input"])
        deps=leaf.get("depends_on",[])
        if (type(deps) is not list or len(deps)>12 or any(_id(d)==task for d in deps) or len(set(deps))!=len(deps)):
            raise ValueError("Invalid dependencies")
        normalized.append({"id":task,"action":leaf["action"],"input":leaf["input"],
                           "input_sha256":digest(canonical(leaf["input"])),"depends_on":sorted(deps)})
    ids=[v["id"] for v in normalized]
    if len(set(ids))!=len(ids) or any(d not in ids for v in normalized for d in v["depends_on"]):
        raise ValueError("Foreign or duplicate task IDs")
    graph={v["id"]:v["depends_on"] for v in normalized}; done=set(); visiting=set()
    def visit(key):
        if key in visiting: raise ValueError("Cyclic plan")
        if key in done: return
        visiting.add(key)
        for dep in graph[key]: visit(dep)
        visiting.remove(key); done.add(key)
    for key in ids: visit(key)
    _json(normalized)
    return normalized

def get_goal(system, project_id, goal_id):
    g=_verify(_read(_directory(system,project_id)/"goals"/(_id(goal_id)+".json")),GOAL_KEYS,"goal_sha256")
    if g["project_id"]!=project_id or g["id"]!=goal_id or g["purpose"] not in ("research","ops-smoke"):
        raise ValueError("Foreign goal")
    if digest(canonical(g["plan"]))!=g["plan_sha256"]: raise ValueError("Plan hash mismatch")
    _text(g["text"],10,20000)
    return g

def save_goal(system, project_id, goal_id, text, plan, purpose="research", *, expected_rules_sha=None, expected_source_sha=None):
    _id(goal_id); _text(text,10,20000)
    if purpose not in ("research","ops-smoke"): raise ValueError("Unknown goal purpose")
    with system.lock():
        p=get_project(system,project_id)
        source=manifest(system.root)["sha256"]
        if ((expected_rules_sha is not None and expected_rules_sha!=p["rules_sha256"])
                or (expected_source_sha is not None and expected_source_sha!=source)):
            raise ValueError("Source or rules changed before plan adoption")
        if (p["kind"]=="ops-smoke")!=(purpose=="ops-smoke"): raise ValueError("Smoke/science mismatch")
        fixed=_plan(system,p,plan)
        g=_seal({"schema":1,"id":goal_id,"project_id":project_id,"purpose":purpose,"text":text,
                 "rules_sha256":p["rules_sha256"],"source_sha256":source,
                 "plan":fixed,"plan_sha256":digest(canonical(fixed))},"goal_sha256")
        _immutable(_directory(system,project_id)/"goals"/(goal_id+".json"),g)
        return g

def _approval(system, project, goal):
    a=_verify(_read(_directory(system,project["id"])/"approvals"/(_hash(project["approval_sha256"])+".json")),
              APPROVAL_KEYS,"approval_sha256")
    if (a["project_id"]!=project["id"] or a["goal_id"]!=goal["id"] or a["roles"]!=ROLES
            or a["rules_sha256"]!=project["rules_sha256"] or a["goal_sha256"]!=goal["goal_sha256"]
            or a["plan_sha256"]!=goal["plan_sha256"] or a["source_sha256"]!=goal["source_sha256"]
            or a["capabilities"]!={"research_write":False,"gpu":False,"publish":False}):
        raise ValueError("Stale/foreign approval")
    _text(a["authorization"],20,20000)
    return a

def approve_goal(system, project_id, goal_id, expected_plan_sha, authorization_text):
    """Explicit human/trusted local operator approval, not an LLM proposal action."""
    _hash(expected_plan_sha); _text(authorization_text,20,20000)
    with system.lock():
        p,g=get_project(system,project_id),get_goal(system,project_id,goal_id)
        if (expected_plan_sha!=g["plan_sha256"] or g["rules_sha256"]!=p["rules_sha256"]
                or g["source_sha256"]!=manifest(system.root)["sha256"]
                or any(system.policy[k] for k in ("research_write","gpu","publish"))):
            raise ValueError("Approval plan/rules/source/scope mismatch")
        if p["kind"]=="ops-smoke" and any(t["action"] not in SMOKE_ACTIONS for t in g["plan"]):
            raise ValueError("Smoke cannot approve research")
        if p["active_goal"]==goal_id and p["approval_sha256"]:
            old=_approval(system,p,g)
            if old["authorization"]==authorization_text: return old
        a=_seal({"schema":1,"project_id":project_id,"goal_id":goal_id,"rules_sha256":p["rules_sha256"],
                 "goal_sha256":g["goal_sha256"],"plan_sha256":g["plan_sha256"],"source_sha256":g["source_sha256"],
                 "roles":dict(ROLES),"capabilities":{"research_write":False,"gpu":False,"publish":False},
                 "authorization":authorization_text,"time":utc()},"approval_sha256")
        directory=_directory(system,project_id)
        _immutable(directory/"approvals"/(a["approval_sha256"]+".json"),a)
        pointer={k:p[k] for k in PROJECT_KEYS}
        pointer.update(active_goal=goal_id,approval_sha256=a["approval_sha256"],state="ACTIVE",updated=utc())
        write_json(directory/"project.json",pointer)
        return a

def binding_for_submission(system, project, goal, action, writer):
    """Pure read; safe under System.submit's lock. Core must check selected plan item."""
    p,g=get_project(system,_id(project)),get_goal(system,project,_id(goal))
    if p["state"]!="ACTIVE" or p["active_goal"]!=goal or writer!="codex":
        raise ValueError("No active approved goal for this writer")
    a=_approval(system,p,g)
    if action not in p["rules"]["allowed_actions"] or g["source_sha256"]!=manifest(system.root)["sha256"]:
        raise ValueError("Action/source outside approval")
    return {"schema":1,"project_id":project,"goal_id":goal,"profile":p["profile"],
            "rules_sha256":p["rules_sha256"],"goal_sha256":g["goal_sha256"],"plan_sha256":g["plan_sha256"],
            "approval_sha256":a["approval_sha256"],
            "plan":[{k:t[k] for k in ("id","action","input_sha256","depends_on")} for t in g["plan"]],
            "readonly_roots":p["rules"]["readonly_roots"],"output_root":str(no_links(_directory(system,project)/"outputs"/goal))}

def binding_current(system, spec):
    if "project_binding" not in spec: return True
    try:
        b=spec["project_binding"]
        if type(b) is not dict: return False
        expected=binding_for_submission(system,b["project_id"],b["goal_id"],spec["action"],spec["writer"])
        if b!=expected or spec.get("reviewer")!="claude": return False
        leaf=next((v for v in expected["plan"] if v["id"]==spec["id"]),None)
        return (leaf is not None and leaf["action"]==spec["action"]
                and leaf["input_sha256"]==spec["input_sha256"]==digest(canonical(spec["input"]))
                and spec["workdir"]==str(no_links(Path(expected["output_root"])/_id(spec["id"])))
                and spec["source"]==manifest(system.root)
                and spec["source"]["sha256"]==get_goal(system,b["project_id"],b["goal_id"])["source_sha256"])
    except (OSError,ValueError,KeyError,TypeError): return False

def project_context(system, spec):
    if "project_binding" not in spec: return {}
    if not binding_current(system,spec): raise ValueError("Stale project task binding")
    b=spec["project_binding"];p=get_project(system,b["project_id"]);g=get_goal(system,b["project_id"],b["goal_id"])
    leaf=next(t for t in b["plan"] if t["id"]==spec["id"])
    return {"untrusted_reference_data":True,"project_id":p["id"],"profile":p["profile"],"roles":dict(ROLES),
            "rules_text":p["rules"]["text"],"goal_text":g["text"],"rules_sha256":b["rules_sha256"],
            "goal_sha256":b["goal_sha256"],"plan_sha256":b["plan_sha256"],"depends_on":leaf["depends_on"],
            "scope":{"research_write":False,"gpu":False,"publish":False}}

def dependency_status(system, spec):
    """Recheck ancestor evidence with a bounded cycle guard, including at acceptance."""
    stack=getattr(system,"_dependency_stack",set())
    key=spec.get("id")
    if key in stack or len(stack)>=12: return "BLOCKED"
    system._dependency_stack=stack
    stack.add(key)
    try:
        return _dependency_status(system,spec)
    finally:
        stack.remove(key)


def _dependency_status(system, spec):
    if "project_binding" not in spec: return "READY"
    if not binding_current(system,spec): return "BLOCKED"
    leaf=next(t for t in spec["project_binding"]["plan"] if t["id"]==spec["id"]);waiting=False
    for task in leaf["depends_on"]:
        row=system.db.execute("SELECT spec,state FROM tasks WHERE id=?",(task,)).fetchone()
        if row is None: waiting=True;continue
        try:
            prior=json.loads(row["spec"])
            if prior.get("id")!=task or not binding_current(system,prior) or prior.get("project_binding")!=spec["project_binding"]:
                return "BLOCKED"
        except (ValueError,TypeError,KeyError): return "BLOCKED"
        if row["state"]=="ACCEPTED":
            try:
                from .deployment import verified_acceptance
                verified_acceptance(system,row["spec"],{"source":manifest(system.root)})
            except (OSError,ValueError,KeyError,TypeError):
                return "BLOCKED"
            continue
        if row["state"] in ("QUEUED","REWORK","EXECUTING","REVIEWING","AWAITING_REVIEW") or row["state"].startswith(("WAITING_","PAUSED_")):
            waiting=True
        else: return "BLOCKED"
    return "WAITING" if waiting else "READY"

def task_evidence_binding(system, spec, state, *, verify_evidence=True):
    """Content identity only; accepted evidence is independently re-verified from disk."""
    folder=no_links(no_links(system.runtime)/"tasks"/_id(spec["id"]))
    result={"source_sha256":spec["source"]["sha256"],"input_sha256":spec["input_sha256"],
            "artifact_sha256":None,"evidence_state":"NOT_PRODUCED"}
    artifact=no_links(folder/"artifact.json")
    if type(verify_evidence) is not bool:
        raise ValueError("verify_evidence must be bool")
    if not verify_evidence:
        # Display only: a queue ACCEPTED state never substitutes for current proof.
        result["evidence_state"] = "EVIDENCE_RECHECK_DEFERRED"
        return result
    try:
        if artifact.exists():
            result["artifact_sha256"]=digest(canonical(_read(artifact)))
            result["evidence_state"]="PRESENT_NOT_ACCEPTED"
        if state=="ACCEPTED":
            from .deployment import verified_acceptance
            verified_acceptance(system,canonical(spec).decode(),{"source":manifest(system.root)})
            result["evidence_state"]="VERIFIED_ACCEPTANCE"
    except (OSError,ValueError,KeyError,TypeError):
        result["evidence_state"]="INVALID_EVIDENCE"
    return result

def status_cards(system, *, verify_evidence=True):
    if type(verify_evidence) is not bool:
        raise ValueError("verify_evidence must be bool")
    root=no_links(no_links(system.runtime)/"projects")
    if not root.exists(): return []
    entries=sorted(root.iterdir(),key=lambda p:p.name)
    if len(entries)>100: raise ValueError("Project inventory limit")
    cards=[]
    for directory in entries:
        no_links(directory);_id(directory.name)
        try:
            p=get_project(system,directory.name);g=None;state="AWAITING_GOAL";reason="GOAL_NOT_SUPPLIED"
            if p["active_goal"]:
                g=get_goal(system,p["id"],p["active_goal"])
                try:
                    binding_for_submission(system,p["id"],g["id"],g["plan"][0]["action"],"codex")
                    state,reason="ACTIVE",None
                except (ValueError,OSError): state,reason="STALE_BINDING","RULES_SOURCE_OR_APPROVAL_CHANGED"
            tasks=[]; invalid_task_records=0
            for row in system.db.execute("SELECT id,spec,state,reason,reworks FROM tasks ORDER BY created"):
                try:
                    spec=json.loads(row["spec"])
                    if spec.get("id")!=row["id"]: raise ValueError("Queue task identity mismatch")
                    if (spec.get("project_binding") or {}).get("project_id")!=p["id"]: continue
                    tasks.append({"id":row["id"],"state":row["state"],"reason":row["reason"],"reworks":row["reworks"],
                                  "goal_id":spec["project_binding"]["goal_id"],"binding_current":binding_current(system,spec),
                                  "evidence":str(no_links(system.runtime)/"tasks"/_id(row["id"])),
                                  "content_binding":task_evidence_binding(system,spec,row["state"],verify_evidence=verify_evidence)})
                except (ValueError,TypeError,KeyError):
                    invalid_task_records+=1
            active_tasks=[t for t in tasks if t["goal_id"]==p["active_goal"]]
            if state=="ACTIVE":
                if any(not t["binding_current"] or t["content_binding"]["evidence_state"]=="INVALID_EVIDENCE"
                       or t["state"]=="NEEDS_ATTENTION" for t in active_tasks):
                    state,reason="BLOCKED","TASK_NEEDS_ATTENTION_OR_STALE_EVIDENCE"
                elif any(t["state"].startswith(("WAITING_","PAUSED_")) for t in active_tasks):
                    state,reason="WAITING","TASK_WAITING_FOR_ENGINE_BUDGET_OR_OPERATOR"
                elif (active_tasks and g and {t["id"] for t in active_tasks}=={t["id"] for t in g["plan"]}
                      and all(t["state"]=="ACCEPTED" for t in active_tasks)):
                    if verify_evidence:
                        state,reason="ACCEPTED","REGISTERED_TASK_SCOPE_ONLY"
                    else:
                        state,reason="UNVERIFIED","EVIDENCE_RECHECK_DEFERRED"
            if invalid_task_records:
                state,reason="BLOCKED","INVALID_QUEUE_RECORD_REQUIRES_INSPECTION"
            cards.append({"project_id":p["id"],"name":p["name"],"profile":p["profile"],"kind":p["kind"],
                          "unattributed_task_record_errors":invalid_task_records,
                          "roles":dict(ROLES),"state":state,"blocking_reason":reason,"rules_sha256":p["rules_sha256"],
                          "active_goal":p["active_goal"],"goal_sha256":g["goal_sha256"] if g else None,"tasks":tasks,
                          "output_root":p["output_root"],"governance_evidence":str(directory)})
        except (ValueError,OSError,KeyError,TypeError):
            cards.append({"project_id":directory.name,"state":"BLOCKED","blocking_reason":"INVALID_PROJECT_RECORD"})
    return cards
