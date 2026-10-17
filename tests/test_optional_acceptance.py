import copy,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_delivery,test_merging
from gates import GateError,require_pr
from merging import eligibility
class OptionalAcceptance(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 harness=test_delivery.Delivery.harness
 execute=test_delivery.Delivery.execute
 def test_without_acceptance_runs_builder_checks_review_only(self):
  self.policy['workflow']=[s for s in self.policy['workflow'] if s['stage'] not in ('acceptance','plan')];calls=[]
  def harness(*args,**kw):calls.append(args[1].name);return self.harness(*args,**kw)
  state=self.execute(harness=harness);self.assertEqual(state['state'],'validated');self.assertIsNone(state['acceptance'])
  self.assertEqual(len(calls),2);require_pr(state,self.policy)
  with self.assertRaises(GateError):require_pr(state)
 def test_configured_acceptance_is_still_required(self):
  self.assertTrue(self.execute()['acceptance'])
 def test_missing_review_still_refused(self):
  self.policy['workflow']=[s for s in self.policy['workflow'] if s['stage']=='build']
  with self.assertRaises(GateError):self.execute()
class ReviewMerge(unittest.TestCase):
 setUp=test_merging.ProductMerge.setUp
 tearDown=test_merging.ProductMerge.tearDown
 def test_review_only_merge_validates_report_and_checks(self):
  self.binding['policy']['workflow']=[{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'}];self.policy.update(mode='review_approved',review_role='reviewer');self.state['acceptance']=None
  p=self.root/'reviewer';p.mkdir();(p/'result.md').write_text('{"verdict":"approved"}')
  self.assertTrue(eligibility(self.root,self.state,self.binding,self.policy,self.pr))
  (p/'result.md').write_text('{"verdict":"changes_requested"}')
  with self.assertRaises(GateError):eligibility(self.root,self.state,self.binding,self.policy,self.pr)
