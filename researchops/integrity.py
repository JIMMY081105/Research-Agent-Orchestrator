"""Content bindings cover all allowlisted source/config/docs/tests, including untracked files."""
import hashlib
import json
import os
from pathlib import Path

EXCLUDED = {".git", ".runtime", ".venv", "venv", "env", "__pycache__", ".pytest_cache", "work"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def no_links(path):
    p = Path(path).absolute()
    for item in (p, *p.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("Reparse path rejected: " + str(item))
    return p


# Every file that can form a revision: what runs (Python, PowerShell), what is read at run
# time (config, prompts) and what documents it. Anything else refuses hashing, packaging,
# snapshotting and scheduled execution, so nothing unbound can run alongside the revision.
ALLOWED = {"": (".py", ".md"), "researchops": (".py",), "tests": (".py",),
           "tools": (".ps1", ".py"), "config": (".json",), "prompts": (".txt",), "skills": (".md",)}
CREDENTIAL_NAMES = {".env", "auth.json", "credentials.json", ".netrc", ".npmrc", ".pypirc", ".git-credentials"}
CREDENTIAL_PREFIXES = (".env.", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
CREDENTIAL_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".ppk", ".jks", ".keystore", ".kdbx")


def refuse_unbound(rel):
    """Decide by path alone, before any byte of the file is read."""
    folder, _, name = rel.rpartition("/")
    low = name.lower()
    if low in CREDENTIAL_NAMES or low.startswith(CREDENTIAL_PREFIXES) or low.endswith(CREDENTIAL_SUFFIXES):
        raise ValueError("Credential-like file refused before reading: " + rel)
    if not (rel == ".gitignore" or (folder in ALLOWED and low.endswith(ALLOWED[folder]))):
        raise ValueError("File outside the source allowlist refused: " + rel)


def manifest(root):
    root = no_links(root)
    paths = []
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for d in dirs:
            no_links(Path(base)/d)
        for name in sorted(names):
            p = no_links(Path(base)/name)
            if p.suffix in {".pyc", ".pyo"}:
                continue
            paths.append(p)
    rels = [p.relative_to(root).as_posix() for p in paths]
    for rel in rels:
        refuse_unbound(rel)  # the whole tree is vetted before any content is read
    files = {rel: digest(p.read_bytes()) for rel, p in zip(rels, paths)}
    return {"files": files, "sha256": digest(canonical(files))}


def write_json(path, value):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    no_links(tmp)
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
