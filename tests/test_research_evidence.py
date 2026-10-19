import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import product_research as research
import research_experiment as probes

class Evidence(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();(self.repo/'spec.py').write_text('VALUE=7\n')
  self.plan={'kind':'existing_defect','question':'Does output violate current contract?','stop_condition':'Observe real behavior','skills':['looop:investigation']}
  self.report={'status':'supported','question':self.plan['question'],'finding':'PM verified actual behavior','counterevidence':'Synthetic evidence only','recommendation':'Define minimal fix','sources':[{'kind':'repository','path':'spec.py','quote':'VALUE=7'}],'skill_usage':[{'path':'looop:investigation','impact':'Compared actual observations'}]}
 def test_pm_owns_research_conclusion_scheduler_checks_structure(self):
  run=Mock(side_effect=[json.dumps(self.plan),json.dumps(self.report)])
  with patch.object(research,'fetch',side_effect=AssertionError('Scheduler must not research')):
   result=research.perform(run,self.repo,self.root/'run','PM','State',Mock(),{'harness':'codex','provider':'codex'},public_required=True)
  self.assertEqual(result['evidence_basis']['assessed_by'],'product-manager-agent');self.assertEqual(run.call_count,2)
 def test_missing_required_result_fields_are_corrected_not_inferred(self):
  bad={**self.report};bad.pop('finding');run=Mock(side_effect=[json.dumps(self.plan),json.dumps(bad),json.dumps(self.report)])
  result=research.perform(run,self.repo,self.root/'run','PM','State',Mock(),{'harness':'codex','provider':'codex'})
  self.assertEqual(result['status'],'supported');self.assertEqual(run.call_count,3)
 def test_successive_retry_preserves_agent_context_without_reexecution(self):
  probe={'runtime':'python','purpose':'Observe implementation','script':'print(7)'}
  with patch('sandbox.run',return_value=json.dumps({'exit_code':0,'output':'7','observations':{'value':7},'evidence_path':'output.json'})):
   receipt=probes.execute(self.repo,self.root/'prior/experiment-1',probe,None,Mock())
  resumed=self.root/'resumed';resumed.mkdir();(resumed/'research.json').write_text(json.dumps({'experiments':[receipt]}));self.assertEqual(probes.restored(self.repo,resumed),[receipt])
 def test_legacy_controller_receipts_are_not_fresh_agent_approvals(self):
  old=self.root/'prior/experiment-1';old.mkdir(parents=True);(old/'result.json').write_text(json.dumps({'exit_code':0,'source_fingerprint':'old'}));self.assertEqual(probes.restored(self.repo,old.parent),[])
