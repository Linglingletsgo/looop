import copy,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from gates import *
class Gates(unittest.TestCase):
 def state(self):
  s={'risk':'high','target_sha':'a'*40,'builder_run':'b','reviews':{}}
  for m,r in [('standard','r1'),('adversarial','r2')]:s['reviews'][m]={'verdict':'approved','mode':m,'target_sha':s['target_sha'],'run_id':r}
  s['acceptance']={'verdict':'approved','target_sha':s['target_sha'],'run_id':'a1'}
  return s
 def test_complete(self):require_pr(self.state())
 def test_self_review_rejected(self):
  s=self.state();s['reviews']['standard']['run_id']='b'
  with self.assertRaises(GateError):require_pr(s)
 def test_sha_invalidates_everything(self):
  s=self.state();update_target(s,'c'*40);self.assertEqual(s['reviews'],{});self.assertIsNone(s['acceptance'])
  with self.assertRaises(GateError):require_pr(s)
 def test_adversarial_required(self):
  s=self.state();del s['reviews']['adversarial']
  with self.assertRaises(GateError):require_pr(s)
 def test_same_review_session(self):
  s=self.state();s['reviews']['adversarial']['run_id']='r1'
  with self.assertRaises(GateError):require_pr(s)
 def test_stale_acceptance(self):
  s=self.state();s['acceptance']['target_sha']='d'*40
  with self.assertRaises(GateError):require_pr(s)
 def test_acceptance_separate(self):
  s=self.state();s['acceptance']['run_id']='r1'
  with self.assertRaises(GateError):require_pr(s)
 def test_claim_not_approval(self):
  s=self.state();s['reviews']['standard']['verdict']='COMPLETE'
  with self.assertRaises(GateError):require_pr(s)
 def test_incomplete_packet(self):
  with self.assertRaises(GateError):validate_packet({'bundle':'x'})
 def test_low_risk(self):
  s=self.state();s['risk']='low';del s['reviews']['adversarial'];require_pr(s)

 def test_review_output_requires_unambiguous_object_and_findings(self):
  for text in ('[]','null','{"verdict":"approved","findings":"none"}','Summary\n{"verdict":"approved","findings":[]}','{"verdict":"blocked","findings":[]}\n{"verdict":"approved","findings":[]}'):
   with self.assertRaises(ValueError):verdict(text)
  self.assertEqual(verdict('```json\n{"verdict":"blocked","findings":["Evidence missing"]}\n```')['verdict'],'blocked')
