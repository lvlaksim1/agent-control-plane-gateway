import sys,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
import lease_gateway as g
NOW=datetime(2026,9,23,3,30,tzinfo=timezone.utc)
def idle(n=2): return {"schema_version":1,"state":"idle","generation":n,"execution_id":None,"task_id":None,"agent_id":None,"slot_id":None,"request_blob_sha":None,"claimed_at":None,"lease_until":None,"activation_projection_blob_sha":None}
def claim_req(e="e1"): return {"operation":"claim","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":e,"slot_id":"s1","request_blob_sha":"a"*40,"lease_minutes":45}
def activate_req(generation=3,e="e1",receipt="b"*40): return {"operation":"activate","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":e,"generation":generation,"request_blob_sha":"a"*40,"activation_projection_blob_sha":receipt}
class T(unittest.TestCase):
 def test_claim_reserves_not_activates(self):
  l,r=g.transition(idle(),claim_req(),NOW)
  self.assertTrue(r["accepted"]); self.assertEqual(l["state"],"reserved"); self.assertIsNone(l["activation_projection_blob_sha"]); self.assertEqual(l["generation"],3)
 def test_activation_requires_exact_reserved_owner_and_projection_receipt(self):
  l,_=g.transition(idle(),claim_req(),NOW)
  a,r=g.transition(l,activate_req(),NOW)
  self.assertTrue(r["accepted"]); self.assertEqual(a["state"],"active"); self.assertEqual(a["activation_projection_blob_sha"],"b"*40)
  same,bad=g.transition(a,activate_req(),NOW); self.assertFalse(bad["accepted"]); self.assertEqual(same,a)
 def test_target_write_fence_can_require_active_receipt(self):
  l,_=g.transition(idle(),claim_req(),NOW)
  self.assertEqual(l["state"],"reserved")
  a,_=g.transition(l,activate_req(),NOW)
  self.assertEqual((a["state"],a["activation_projection_blob_sha"]),("active","b"*40))
 def test_second_claim_denied_while_reserved(self):
  l,_=g.transition(idle(),claim_req("a"),NOW); same,r=g.transition(l,claim_req("b"),NOW)
  self.assertFalse(r["accepted"]); self.assertEqual(r["reason"],"lease-held"); self.assertEqual(same,l)
 def test_release_works_from_reserved_and_active(self):
  l,_=g.transition(idle(),claim_req(),NOW)
  l2,r2=g.transition(l,{"operation":"release","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"e1","generation":3},NOW)
  self.assertTrue(r2["accepted"]); self.assertEqual(l2["generation"],4)
  l,_=g.transition(idle(4),claim_req(),NOW); a,_=g.transition(l,activate_req(generation=5),NOW)
  l2,r2=g.transition(a,{"operation":"release","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"e1","generation":5},NOW)
  self.assertTrue(r2["accepted"]); self.assertEqual(l2["generation"],6)
 def test_renew_only_active(self):
  l,_=g.transition(idle(),claim_req(),NOW)
  same,r=g.transition(l,{"operation":"renew","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"e1","generation":3,"lease_minutes":45},NOW)
  self.assertFalse(r["accepted"]); self.assertEqual(same,l)
  a,_=g.transition(l,activate_req(),NOW)
  n,r=g.transition(a,{"operation":"renew","task_id":"opaque-task","agent_id":"opaque-agent","execution_id":"e1","generation":3,"lease_minutes":45},NOW)
  self.assertTrue(r["accepted"]); self.assertEqual(n["state"],"active")
 def test_recover_reserved_or_active_only_after_expiry(self):
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
