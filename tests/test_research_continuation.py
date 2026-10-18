import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import product_research as research
class ResearchContinuation(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.repo=pathlib.Path(self.temp.name)
  (self.repo/'spec.md').write_text('Confirmed product evidence requires reliable source attribution.')
  self.plan={'question':'Does attribution exist?','stop_condition':'Read source and specification','skills':['looop:investigation']}
  self.gap={'status':'insufficient_evidence','question':self.plan['question'],'finding':'Need to read implementation','counterevidence':'No confirmed defect','recommendation':'Read spec.md before deciding','next_step':{'kind':'investigate','detail':'Read spec.md'},'skill_usage':[{'path':'looop:investigation','impact':'Identified exact missing source'}],'sources':[]}
  self.supported={**self.gap,'status':'supported','finding':'Specification confirms requirement','sources':[{'kind':'repository','path':'spec.md','quote':'Confirmed product evidence requires reliable source attribution.'}]}
 def perform(self,responses,fresh=None):
  self.run=Mock(side_effect=[json.dumps(v) for v in responses]);self.fresh=fresh or Mock()
  return research.perform(self.run,self.repo,self.repo/'run','PM','Current state',self.fresh,{'harness':'codex','provider':'codex'})
 def test_continue_same_research_then_verify_without_replanning(self):
  result=self.perform([self.plan,self.gap,self.supported]);self.assertEqual(result['status'],'supported');self.assertEqual(result['followups'],1);self.assertEqual(self.run.call_count,3)
  self.assertEqual(self.run.call_args.args[1].name,'research-followup-1');prompt=self.run.call_args.args[2];self.assertIn('RESEARCH CONTINUATION',prompt);self.assertIn('Read spec.md',prompt);self.assertIn('Does attribution exist?',prompt);self.assertNotIn('Catalog: ',prompt)
  self.assertIn('sha256',result['sources'][0]);self.assertEqual(json.loads((self.repo/'run/research.json').read_text())['status'],'supported')
 def test_persistent_gap_stops_with_preserved_evidence(self):
  result=self.perform([self.plan,self.gap,self.gap,self.gap]);self.assertEqual(result['status'],'insufficient_evidence');self.assertEqual(self.run.call_count,4);self.assertEqual(result['followups'],2)
 def test_external_decision_or_source_wait_is_not_blindly_retried(self):
  for kind in ('human_decision','wait_source'):
   gap=copy.deepcopy(self.gap);gap['next_step']['kind']=kind
   result=self.perform([self.plan,gap]);self.assertEqual(self.run.call_count,2);self.assertEqual(result['next_step']['kind'],kind)
 def test_rejected_is_idle_not_research_recovery(self):
  result=self.perform([self.plan,{**self.gap,'status':'rejected'}]);self.assertEqual(result['status'],'rejected');self.assertEqual(self.run.call_count,2)
 def test_project_change_during_continuation_stops_model(self):
  def fresh():
   if getattr(self,'run',None) and self.run.call_count>=2:raise ValueError('Decision changed')
  with self.assertRaisesRegex(ValueError,'Decision changed'):self.perform([self.plan,self.gap,self.supported],fresh)
  self.assertEqual(self.run.call_count,2)
