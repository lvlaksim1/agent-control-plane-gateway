import sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import lease_gateway as g
NOW=datetime(2026,9,23,3,30,tzinfo=timezone.utc)
def idle(n=2): return {"schema_version":1,"state":"idle","generation":n,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"request_blob_sha":None,"claimed_at":None,"lease_until":None}
def claim_req(e="e1"): return {"operation":"claim","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":e,"slot_id":"s1","request_blob_sha":"a"*40,"lease_minutes":45}
class T(unittest.TestCase):
 def test_claim_release_fences(self):
  l,r=g.transition(idle(),claim_req(),NOW); self.assertTrue(r["accepted"]); self.assertEqual(l["generation"],3)
  old=dict(l); l2,r2=g.transition(l,{"operation":"release","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"e1","generation":3},NOW)
  self.assertTrue(r2["accepted"]); self.assertEqual(l2["generation"],4)
  self.assertNotEqual(old["generation"],l2["generation"])
 def test_second_claim_denied(self):
  l,_=g.transition(idle(),claim_req("a"),NOW); same,r=g.transition(l,claim_req("b"),NOW)
  self.assertFalse(r["accepted"]); self.assertEqual(same,l)
 def test_wrong_release_denied(self):
  l,_=g.transition(idle(),claim_req(),NOW); same,r=g.transition(l,{"operation":"release","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"wrong","generation":3},NOW)
  self.assertFalse(r["accepted"]); self.assertEqual(same,l)
 def test_recover_only_after_expiry(self):
  l,_=g.transition(idle(),claim_req(),NOW)
  same,r=g.transition(l,{"operation":"recover_expired","generation":3},NOW+timedelta(minutes=1)); self.assertFalse(r["accepted"])
  n,r=g.transition(l,{"operation":"recover_expired","generation":3},NOW+timedelta(minutes=46)); self.assertTrue(r["accepted"]); self.assertEqual(n["generation"],4)
 def test_workflow_uses_contents_api_cas_and_never_git_push(self):
  workflow=(Path(__file__).resolve().parents[1]/".github/workflows/lease-gateway.yml").read_text()
  self.assertIn("contents/runtime/lease.json",workflow)
  self.assertIn("-f sha=",workflow)
  self.assertIn("cmp -s /tmp/new-lease.json /tmp/verified-lease.json",workflow)
  self.assertNotIn("git push origin",workflow)
  self.assertIn("queue: max",workflow)

if __name__=="__main__": unittest.main()
