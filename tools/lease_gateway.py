#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path

class GatewayError(ValueError): pass

def parse_time(v):
    if v.endswith("Z"): v=v[:-1]+"+00:00"
    dt=datetime.fromisoformat(v)
    if dt.tzinfo is None: raise GatewayError("timezone required")
    return dt.astimezone(timezone.utc)

def fmt(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def normalize(lease):
    # Backward-compatible read of v1 idle/active records during migration.
    n=dict(lease)
    n.setdefault("activation_projection_blob_sha",None)
    return n

def validate(lease):
    lease=normalize(lease)
    required=["schema_version","state","generation","execution_id","task_id","agent_id","slot_id","request_blob_sha","claimed_at","lease_until","activation_projection_blob_sha"]
    if any(k not in lease for k in required): raise GatewayError("invalid lease fields")
    if lease["schema_version"]!=1 or lease["state"] not in {"idle","reserved","active"}: raise GatewayError("invalid lease")
    if not isinstance(lease["generation"],int) or lease["generation"]<0: raise GatewayError("invalid generation")
    owner_fields=["execution_id","task_id","agent_id","slot_id","request_blob_sha","claimed_at","lease_until"]
    if lease["state"]=="idle":
        if any(lease[k] is not None for k in owner_fields+["activation_projection_blob_sha"]): raise GatewayError("idle lease must be empty")
    else:
        if any(lease[k] in (None,"") for k in owner_fields): raise GatewayError("owned lease incomplete")
        if len(lease["request_blob_sha"])!=40: raise GatewayError("invalid request blob")
        parse_time(lease["claimed_at"]); parse_time(lease["lease_until"])
        receipt=lease["activation_projection_blob_sha"]
        if lease["state"]=="reserved" and receipt is not None: raise GatewayError("reserved lease cannot be activated")
        if lease["state"]=="active" and (not isinstance(receipt,str) or len(receipt)!=40): raise GatewayError("active lease requires activation receipt")

def exact_owner(lease,req):
    lease=normalize(lease)
    for k in ("task_id","agent_id","execution_id","generation"):
        if lease[k]!=req.get(k): return False
    rb=req.get("request_blob_sha")
    if rb is not None and lease["request_blob_sha"]!=rb: return False
    return True

def idle_from(lease):
    return {"schema_version":1,"state":"idle","generation":lease["generation"]+1,
      "execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,
      "request_blob_sha":None,"claimed_at":None,"lease_until":None,
      "activation_projection_blob_sha":None}

def transition(lease,req,now):
    lease=normalize(lease); validate(lease)
    op=req.get("operation")
    if op=="claim":
        for k in ("task_id","agent_id","execution_id","slot_id","request_blob_sha"):
            if not req.get(k): raise GatewayError(f"claim requires {k}")
        if len(req["request_blob_sha"])!=40: raise GatewayError("invalid request_blob_sha")
        if lease["state"]!="idle":
            return lease,{"accepted":False,"operation":op,"reason":"lease-held","state":lease["state"],"generation":lease["generation"],"execution_id":lease["execution_id"]}
        minutes=int(req.get("lease_minutes",45))
        if minutes<5 or minutes>120: raise GatewayError("lease_minutes out of range")
        n={"schema_version":1,"state":"reserved","generation":lease["generation"]+1,
           "execution_id":req["execution_id"],"task_id":req["task_id"],"agent_id":req["agent_id"],
           "slot_id":req["slot_id"],"request_blob_sha":req["request_blob_sha"],
           "claimed_at":fmt(now),"lease_until":fmt(now+timedelta(minutes=minutes)),
           "activation_projection_blob_sha":None}
        return n,{"accepted":True,"operation":op,"reason":"reserved","state":"reserved","generation":n["generation"],"execution_id":n["execution_id"],"lease_until":n["lease_until"]}

    if op=="activate":
        if lease["state"]!="reserved" or not exact_owner(lease,req):
            return lease,{"accepted":False,"operation":op,"reason":"fence-mismatch","state":lease["state"],"generation":lease["generation"]}
        receipt=req.get("activation_projection_blob_sha")
        if not isinstance(receipt,str) or len(receipt)!=40:
            raise GatewayError("activate requires 40-char activation_projection_blob_sha")
        n=dict(lease); n["state"]="active"; n["activation_projection_blob_sha"]=receipt
        return n,{"accepted":True,"operation":op,"reason":"activated","state":"active","generation":n["generation"],"execution_id":n["execution_id"],"activation_projection_blob_sha":receipt}

    if op=="renew":
        if lease["state"]!="active" or not exact_owner(lease,req):
            return lease,{"accepted":False,"operation":op,"reason":"fence-mismatch","state":lease["state"],"generation":lease["generation"]}
        minutes=int(req.get("lease_minutes",45))
        n=dict(lease); n["lease_until"]=fmt(now+timedelta(minutes=minutes))
        return n,{"accepted":True,"operation":op,"reason":"renewed","state":"active","generation":n["generation"],"lease_until":n["lease_until"]}

    if op=="release":
        if lease["state"] not in {"reserved","active"} or not exact_owner(lease,req):
            return lease,{"accepted":False,"operation":op,"reason":"fence-mismatch","state":lease["state"],"generation":lease["generation"]}
        n=idle_from(lease)
        return n,{"accepted":True,"operation":op,"reason":"released","state":"idle","generation":n["generation"]}

    if op=="recover_expired":
        if lease["state"] not in {"reserved","active"}:
            return lease,{"accepted":False,"operation":op,"reason":"lease-idle","state":lease["state"],"generation":lease["generation"]}
        if req.get("generation")!=lease["generation"]:
            return lease,{"accepted":False,"operation":op,"reason":"generation-mismatch","state":lease["state"],"generation":lease["generation"]}
        if now<=parse_time(lease["lease_until"]):
            return lease,{"accepted":False,"operation":op,"reason":"lease-not-expired","state":lease["state"],"generation":lease["generation"],"lease_until":lease["lease_until"]}
        old={"task_id":lease["task_id"],"agent_id":lease["agent_id"],"execution_id":lease["execution_id"],"generation":lease["generation"],"state":lease["state"]}
        n=idle_from(lease)
        return n,{"accepted":True,"operation":op,"reason":"expired-fenced","state":"idle","generation":n["generation"],"fenced":old}
    raise GatewayError("unsupported operation")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--lease",required=True); ap.add_argument("--request",required=True); ap.add_argument("--now",required=True)
    ap.add_argument("--out-lease",required=True); ap.add_argument("--out-response",required=True)
    a=ap.parse_args()
    lease=json.loads(Path(a.lease).read_text()); req=json.loads(Path(a.request).read_text())
    new,response=transition(lease,req,parse_time(a.now))
    validate(new)
    Path(a.out_lease).write_text(json.dumps(new,indent=2)+"\n")
    Path(a.out_response).write_text(json.dumps(response,separators=(",",":"))+"\n")

if __name__=="__main__": main()
