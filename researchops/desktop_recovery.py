"""Pure ownership decisions for the desktop's own background service."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import secrets
import sys

UI_OWNER = "BGV.Windows.ResearchOps.UI.v1"


def _dpapi(data, protect):
    class Blob(C.Structure):
        _fields_=[('length',W.DWORD),('data',C.POINTER(C.c_ubyte))]
    raw=C.create_string_buffer(data);source=Blob(len(data),C.cast(raw,C.POINTER(C.c_ubyte)));out=Blob()
    api=C.WinDLL('crypt32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[W.HLOCAL];kernel.LocalFree.restype=W.HLOCAL
    fn=api.CryptProtectData if protect else api.CryptUnprotectData
    fn.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(Blob)];fn.restype=W.BOOL
    if not fn(C.byref(source),None,None,None,None,1,C.byref(out)):
        raise ValueError('UI_SESSION_KEY_DPAPI_FAILED')
    try:return C.string_at(out.data,out.length)
    finally:kernel.LocalFree(C.cast(out.data,W.HLOCAL))


def ui_session_key(existing=None, path=None):
    """Only this application's generated signing key, DPAPI outside all repos."""
    path=Path(path) if path is not None else Path(os.environ['LOCALAPPDATA'])/'BGVSceneControl/state/ui-session-key.dpapi'
    path=path.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path,*path.parents)):
        raise ValueError('UI_SESSION_KEY_REPARSE_PATH')
    if any((p/'.git').exists() for p in path.parents):
        raise ValueError('UI_SESSION_KEY_IN_REPOSITORY_FORBIDDEN')
    if path.exists():
        if path.stat().st_size>4096:raise ValueError('UI_SESSION_KEY_INVALID')
        value=_dpapi(path.read_bytes(),False)
        if len(value)!=32 or (existing is not None and not secrets.compare_digest(value,existing)):
            raise ValueError('UI_SESSION_KEY_CONFLICT')
        return value
    value=existing if existing is not None else secrets.token_bytes(32)
    if type(value) is not bytes or len(value)!=32:raise ValueError('UI_SESSION_KEY_INVALID')
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with path.open('xb') as stream:stream.write(_dpapi(value,True))
    except FileExistsError:return ui_session_key(value,path)
    return value


def preserve_running_ui_session():
    """Planned upgrade hook; no key is returned/logged or copied to a repo."""
    flask=sys.modules.get('flask')
    if flask is None:return 'NOT_APPLICABLE'
    try:app=flask.current_app._get_current_object()
    except RuntimeError:return 'NOT_APPLICABLE'
    allowed={Path(r'E:\Github\Research-Agent-Orchestrator\ui_preview'),Path(__file__).resolve().parents[1]/'ui_preview'}
    if app.testing or Path(app.root_path) not in allowed:return 'NOT_APPLICABLE'
    try:ui_session_key(app.secret_key)
    except (OSError,ValueError,KeyError):return 'UNVERIFIED'
    return 'PRESERVED'

def valid_receipt(receipt):
    return (type(receipt) is dict and receipt.get("owner") == UI_OWNER
            and receipt.get("read_only") is True and type(receipt.get("pid")) is int
            and receipt["pid"] > 0 and type(receipt.get("birth")) is str
            and receipt["birth"].isdigit() and len(receipt["birth"]) <= 30
            and type(receipt.get("source_sha256")) is str)

def decide(receipt, response, expected_hash, identity, port_open=False):
    """Return READY/STARTABLE or a reason; never start, terminate or change anything."""
    if receipt is not None and not valid_receipt(receipt):
        return "RECEIPT_UNVERIFIED"
    if receipt is not None:
        actual = identity(receipt["pid"])
        if actual == "UNKNOWN":
            return "PROCESS_IDENTITY_UNKNOWN"
        live = actual == receipt["birth"]
        if live and receipt["source_sha256"] != expected_hash:
            return "OTHER_VERSION_RUNNING"
        if live:
            service = response.get("service") if type(response) is dict else None
            if (type(service) is dict and response.get("read_only") is True
                    and service.get("owner") == UI_OWNER and service.get("read_only") is True
                    and service.get("pid") == receipt["pid"]
                    and service.get("bundle_sha256") == expected_hash):
                return "READY"
            return "OWNED_PROCESS_UNRESPONSIVE"
    if port_open or response is not None:
        return "PORT_IDENTITY_UNVERIFIED"
    return "STARTABLE"
