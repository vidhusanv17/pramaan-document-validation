import hashlib
import json
from datetime import datetime

from .models import AuditLog

GENESIS = "0" * 64


def _payload(ts, actor, action, entity_type, entity_id, details, prev):
    return json.dumps({"ts": ts.isoformat(), "actor": actor, "action": action, "entity_type": entity_type, "entity_id": entity_id,
                       "details": details, "prev": prev}, sort_keys=True, default=str, separators=(",", ":"))


def record(db, actor, action, entity_type, entity_id, details=None, actor_role=None):
    details = json.loads(json.dumps(details or {}, default=str))
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev = last.hash if last else GENESIS
    ts = datetime.utcnow().replace(microsecond=0)
    eid = None if entity_id is None else str(entity_id)
    h = hashlib.sha256(_payload(ts, actor, action, entity_type, eid, details, prev).encode()).hexdigest()
    e = AuditLog(ts=ts, actor=actor, actor_role=actor_role, action=action, entity_type=entity_type, entity_id=eid, details=details, prev_hash=prev, hash=h)
    db.add(e)
    db.flush()
    return e


def verify_chain(db):
    prev = GENESIS
    broken = []
    entries = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    for e in entries:
        h = hashlib.sha256(_payload(e.ts, e.actor, e.action, e.entity_type, e.entity_id, e.details or {}, prev).encode()).hexdigest()
        if h != e.hash or e.prev_hash != prev:
            broken.append(e.id)
        prev = e.hash
    return {"entries": len(entries), "intact": not broken, "broken_ids": broken[:20], "head_hash": prev}
