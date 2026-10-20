"""Pure ownership decisions for the desktop's own background service."""
from __future__ import annotations

UI_OWNER = "BGV.Windows.ResearchOps.UI.v1"

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
