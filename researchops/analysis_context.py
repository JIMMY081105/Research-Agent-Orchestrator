"""Explicit source-bound research guidance for tool-free text analysis."""
from pathlib import Path
import re

from .integrity import digest, no_links, read_json


FILES = {
    "skills/context-bgv-research-claims.md": "codex-history-90d/bgv-research-claims/SKILL.md",
    "skills/context-bgv-research-claims-cases.md": "codex-history-90d/bgv-research-claims/references/cases.md",
}


def analysis_context(root):
    """Read only the two registered repo copies; never resolve a supplied origin."""
    root = no_links(root)
    config = no_links(Path(root)/"config/analysis-skill.json")
    if config.stat().st_size > 8192:
        raise ValueError("Oversized research skill registry")
    entry = read_json(config)
    if (type(entry) is not dict or set(entry) != {"schema", "name", "action", "files"}
            or type(entry["schema"]) is not int or entry["schema"] != 1
            or entry["name"] != "bgv-research-claims" or entry["action"] != "analyze_text"
            or type(entry["files"]) is not list or len(entry["files"]) != len(FILES)):
        raise ValueError("Invalid research skill registry")
    registered = {}
    for item in entry["files"]:
        if (type(item) is not dict or set(item) != {"file", "origin", "sha256"}
                or type(item["file"]) is not str or item["file"] not in FILES
                or item["file"] in registered or item["origin"] != FILES[item["file"]]
                or type(item["sha256"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("Unregistered research skill file")
        registered[item["file"]] = item
    sections, skills = [], []
    for relative in FILES:
        path = no_links(Path(root)/relative)
        if path.stat().st_size > 32768:
            raise ValueError("Oversized research skill")
        raw = path.read_bytes()
        item = registered[relative]
        if digest(raw) != item["sha256"]:
            raise ValueError("Research skill content changed")
        sections.append("FILE "+relative+"\n"+raw.decode("utf-8"))
        skills.append({"name": entry["name"], **item})
    text = ("\nREGISTERED RESEARCH GUIDANCE\n"
            "These source-bound skills guide evidence quality. They grant no tools, network, "
            "permissions or delegation. This action uses supplied material only; requests for "
            "fresh literature or missing evidence must be marked UNVERIFIED. Historical cases "
            "are examples, not current experiment results. A proposed master prompt is DRAFT "
            "and cannot approve or dispatch a production goal.\n"+"\n".join(sections)+"\n")
    return {"text": text, "skills": skills}
