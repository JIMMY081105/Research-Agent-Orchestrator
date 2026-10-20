"""Per-attempt LPAC: fresh profile/SID, no network capability, exact owned-tree ACLs."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from .integrity import (CREDENTIAL_NAMES, CREDENTIAL_PREFIXES, CREDENTIAL_SUFFIXES,
                        read_json, write_json)

K=C.WinDLL('kernel32',use_last_error=True)
A=C.WinDLL('advapi32',use_last_error=True)
U=C.WinDLL('userenv',use_last_error=True)
KB=C.WinDLL('kernelbase',use_last_error=True)
O=C.WinDLL('ole32',use_last_error=True)
O.CoTaskMemFree.argtypes=[C.c_void_p];O.CoTaskMemFree.restype=None
K.GetCurrentProcess.restype=W.HANDLE
K.CloseHandle.argtypes=[W.HANDLE]
K.LocalFree.argtypes=[C.c_void_p]
A.OpenProcessToken.argtypes=[W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)]
A.GetTokenInformation.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
A.ConvertSidToStringSidW.argtypes=[C.c_void_p,C.POINTER(W.LPWSTR)]
A.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[W.LPCWSTR,W.DWORD,C.POINTER(C.c_void_p),C.POINTER(W.DWORD)]
A.SetFileSecurityW.argtypes=[W.LPCWSTR,W.DWORD,C.c_void_p]
A.FreeSid.argtypes=[C.c_void_p]
U.CreateAppContainerProfile.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,C.c_void_p,W.DWORD,C.POINTER(C.c_void_p)]
U.CreateAppContainerProfile.restype=C.c_long
U.DeleteAppContainerProfile.argtypes=[W.LPCWSTR];U.DeleteAppContainerProfile.restype=C.c_long
U.GetAppContainerFolderPath.argtypes=[W.LPCWSTR,C.POINTER(W.LPWSTR)];U.GetAppContainerFolderPath.restype=C.c_long
KB.DeriveCapabilitySidsFromName.argtypes=[W.LPCWSTR,C.POINTER(C.c_void_p),C.POINTER(W.DWORD),C.POINTER(C.c_void_p),C.POINTER(W.DWORD)]

class SidAndAttributes(C.Structure):
    _fields_=[('sid',C.c_void_p),('attributes',W.DWORD)]

def check(ok):
    if not ok: raise C.WinError(C.get_last_error())

def hresult(hr):
    if hr: raise OSError('Windows AppContainer HRESULT '+hex(hr&0xffffffff))

def sid_string(sid):
    text=W.LPWSTR();check(A.ConvertSidToStringSidW(sid,C.byref(text)))
    try:return text.value
    finally:K.LocalFree(text)

def current_user_sid():
    token=W.HANDLE();check(A.OpenProcessToken(K.GetCurrentProcess(),8,C.byref(token)))
    try:
        size=W.DWORD();A.GetTokenInformation(token,1,None,0,C.byref(size));buf=C.create_string_buffer(size.value)
        check(A.GetTokenInformation(token,1,buf,size,C.byref(size)))
        return sid_string(C.cast(buf,C.POINTER(C.c_void_p))[0])
    finally:K.CloseHandle(token)

def safe_path(path):
    path=Path(os.path.abspath(path))
    for p in [path,*path.parents]:
        if p.exists() and p.lstat().st_file_attributes&0x400:
            raise ValueError('Reparse point refused: '+str(p))
    return path

def all_paths(root):
    root=safe_path(root);result=[root]
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in sorted(dirs+files):result.append(safe_path(Path(base)/name))
    return result

def exact_tree_acl(root,sid,access):
    """Replace only a tree owned/created by this attempt, never outside research or Python.
    OWNER RIGHTS RC removes the implicit owner's WRITE_DAC; token User F alone does
    not satisfy LPAC's independent package/capability check. No CR conditional ACE remains.
    """
    paths=all_paths(root)
    text=('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;'+current_user_sid()+')'
          '(A;OICI;'+access+';;;'+sid+')(A;OICI;RC;;;OW)')
    sd=C.c_void_p();check(A.ConvertStringSecurityDescriptorToSecurityDescriptorW(text,1,C.byref(sd),None))
    try:
        for path in paths:check(A.SetFileSecurityW(str(path),0x80000004,sd))
    finally:K.LocalFree(sd)

def save_lease(path,data):
    write_json(safe_path(path),data)

class AppContainer:
    def __init__(self,lease,process_identity):
        self.lease=safe_path(lease);self.identity=process_identity
        self.name='BGV.Tool.'+uuid.uuid4().hex
        self.sid=C.c_void_p();self.cap_allocs=[];self.profile_created=False;self.capabilities=None
        self.data={'schema':1,'name':self.name,'controller':{'pid':os.getpid(),'birth':self.identity(os.getpid())},'state':'PREPARING'}
    def __enter__(self):
        self.lease.parent.mkdir(parents=True,exist_ok=True)
        save_lease(self.lease,self.data) # before profile creation, recoverable after a crash
        try:
            hresult(U.CreateAppContainerProfile(self.name,self.name,'BGV per-tool LPAC',None,0,C.byref(self.sid)))
            self.profile_created=True
            self.sid_text=sid_string(self.sid)
            p=W.LPWSTR();hresult(U.GetAppContainerFolderPath(self.sid_text,C.byref(p)))
            try:self.profile=safe_path(Path(p.value).parent)
            finally:O.CoTaskMemFree(p)
            if self.profile.name.lower()!=self.name.lower():raise ValueError('Unexpected profile path')
            exact_tree_acl(self.profile,self.sid_text,'FRFX')
            groups,caps=C.c_void_p(),C.c_void_p();gc,cc=W.DWORD(),W.DWORD()
            check(KB.DeriveCapabilitySidsFromName('registryRead',C.byref(groups),C.byref(gc),C.byref(caps),C.byref(cc)))
            for arr,n in [(groups,gc.value),(caps,cc.value)]:
                self.cap_allocs.extend(C.cast(arr,C.POINTER(C.c_void_p))[i] for i in range(n));self.cap_allocs.append(arr)
            if cc.value!=1:raise ValueError('Unexpected registryRead capability count')
            self.capabilities=(SidAndAttributes*1)(SidAndAttributes(C.cast(caps,C.POINTER(C.c_void_p))[0],4))
            self.data.update(sid=self.sid_text,profile=str(self.profile),state='READY',capabilities=['registryRead'],network_capabilities=[])
            save_lease(self.lease,self.data)
            return self
        except BaseException:
            self.close();raise
    def protect_readonly(self,root):exact_tree_acl(root,self.sid_text,'FRFX')
    def protect_output(self,root):exact_tree_acl(root,self.sid_text,'0x1301bf')
    def started(self,pid,birth):
        self.data.update(child={'pid':pid,'birth':birth},state='RUNNING');save_lease(self.lease,self.data)
    def environment(self,out):
        out=str(safe_path(out))
        keep=('USERPROFILE','LOCALAPPDATA','APPDATA','HOMEDRIVE','HOMEPATH','COMSPEC','OS','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','SystemRoot','WINDIR')
        env={k:os.environ[k] for k in keep if k in os.environ}
        env.update(PATH=str(Path(os.environ['SystemRoot'])/'System32'),TEMP=out,TMP=out,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        return env
    def close(self):
        error=None
        if self.profile_created:
            hr=U.DeleteAppContainerProfile(self.name)
            if hr:error='Delete profile HRESULT '+hex(hr&0xffffffff)
            else:self.profile_created=False
        for p in self.cap_allocs:K.LocalFree(p)
        self.cap_allocs=[]
        if self.sid:A.FreeSid(self.sid);self.sid=C.c_void_p()
        self.data['state']='CLEANUP_FAILED' if error else 'CLOSED'
        if error:self.data['error']=error
        save_lease(self.lease,self.data)
        if error:raise RuntimeError(error)
    def __exit__(self,*exc):self.close()

def recover_lease(path,process_identity):
    path=safe_path(path);data=read_json(path)
    if data['state']=='CLOSED':return False
    name=data['name']
    if not re.fullmatch(r'BGV\.Tool\.[0-9a-f]{32}',name):raise ValueError('Unowned profile name')
    for key in ('controller','child'):
        proc=data.get(key)
        if proc:
            live=process_identity(proc['pid'])
            if live=='UNKNOWN' or live==proc['birth']:raise RuntimeError('Owner or child still alive/ambiguous: '+key)
    # Only our registered profile and already-dead attempts. Do not terminate any process here.
    hr=U.DeleteAppContainerProfile(name)
    if hr and (hr&0xffffffff)!=0x80070002:raise OSError('Delete profile HRESULT '+hex(hr&0xffffffff))
    data.update(state='CLOSED',recovered=True);save_lease(path,data);return True

def hash_tree(root):
    root=safe_path(root);rows={}
    for p in all_paths(root):
        if p.is_file():rows[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def copy_file_checked(src,dst):
    src=safe_path(src);dst=safe_path(dst)
    name=src.name.lower()
    if name in CREDENTIAL_NAMES or name.startswith(CREDENTIAL_PREFIXES) or name.endswith(CREDENTIAL_SUFFIXES):
        raise ValueError('Credential-like runtime file refused before reading')
    raw=src.read_bytes();before=hashlib.sha256(raw).digest();dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw)
    if hashlib.sha256(src.read_bytes()).digest()!=before:raise ValueError('Source changed during copy')
    return before.hex()

def copy_tree_checked(src,dst,ignore_names=(),suffixes=None):
    src=safe_path(src);dst=safe_path(dst);dst.mkdir(parents=True,exist_ok=False)
    for base,dirs,files in os.walk(src,followlinks=False):
        dirs[:]=[d for d in sorted(dirs) if d not in ignore_names]
        rel=Path(base).relative_to(src)
        for name in dirs:safe_path(Path(base)/name);(dst/rel/name).mkdir()
        for name in sorted(files):
            if name not in ignore_names and (suffixes is None or Path(name).suffix in suffixes):
                copy_file_checked(Path(base)/name,dst/rel/name)

def copy_runtime(python,dest,packages=()):
    """Copy only stdlib, runtime DLLs and explicitly named project dependencies; no .pth/env/auth."""
    src=safe_path(python).parent;dest=safe_path(dest);dest.mkdir(parents=True,exist_ok=False)
    for f in ('python.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll'):copy_file_checked(src/f,dest/f)
    copy_tree_checked(src/'DLLs',dest/'DLLs',('__pycache__',))
    copy_tree_checked(src/'Lib',dest/'Lib',('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip'))
    site=dest/'Lib'/'site-packages';site.mkdir()
    for source in packages:copy_tree_checked(source,site/Path(source).name,('__pycache__','tests','test'))
    return dest/'python.exe'
