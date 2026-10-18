import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import research_experiment as experiment
import product_research as research

class Experiments(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();(self.repo/'value.py').write_text('VALUE=7\n')
  self.probe={'runtime':'python','purpose':'Observe actual implementation','script':'from value import VALUE\nprint(VALUE)'}
 def execute(self,probe=None,fresh=None):return experiment.execute(self.repo,self.root/'probe',probe or self.probe,None,fresh or Mock())
 def test_real_execution_records_evidence_without_changing_original(self):
  value=self.execute();self.assertEqual(value['exit_code'],0);self.assertEqual(value['output'].strip(),'7');self.assertEqual((self.repo/'value.py').read_text(),'VALUE=7\n');self.assertFalse((self.repo/'.looop-research-probe.py').exists())
 def test_mutating_probe_is_rejected_and_original_preserved(self):
  with self.assertRaisesRegex(ValueError,'modified source'):self.execute({**self.probe,'script':'open("value.py","w").write("bad")'})
  self.assertEqual((self.repo/'value.py').read_text(),'VALUE=7\n');self.assertFalse((self.root/'probe/result.json').exists())
 def test_failed_probe_is_evidence_not_approval_and_output_bounded(self):
  value=self.execute({**self.probe,'script':'print("x"*20000)\nraise SystemExit(3)'})
  self.assertEqual(value['exit_code'],3);self.assertLessEqual(len(value['output']),12000);self.assertLessEqual((self.root/'probe/output.log').stat().st_size,12000)
 def test_stale_state_prevents_execution(self):
  with self.assertRaisesRegex(ValueError,'changed'):self.execute(fresh=Mock(side_effect=ValueError('changed')))
  self.assertFalse((self.root/'probe').exists())
 def test_environment_has_no_ambient_credentials(self):
  with patch.dict('os.environ',{'DATABASE_URL':'private','OPENAI_API_KEY':'private'}):
   result=self.execute({**self.probe,'script':'import os\nprint("DATABASE_URL" in os.environ, "OPENAI_API_KEY" in os.environ)'})
  self.assertEqual(result['output'].strip(),'False False')
 def test_invalid_runtime_rejected(self):
  with self.assertRaises(ValueError):self.execute({**self.probe,'runtime':'shell'})
 def test_existing_dependencies_attached_and_removed(self):
  deps=self.root/'dependencies';deps.mkdir();(deps/'marker').write_text('installed')
  probe={**self.probe,'script':'from pathlib import Path\nprint(Path("node_modules/marker").read_text())'}
  result=experiment.execute(self.repo,self.root/'probe',probe,str(deps),Mock())
  self.assertEqual(result['output'].strip(),'installed');self.assertFalse((self.root/'probe/workspace/node_modules').exists())
 def test_research_requests_probe_then_uses_controller_observations(self):
  plan={'question':'Does value equal seven?','stop_condition':'Execute synthetic probe','skills':['looop:investigation']}
  gap={'status':'insufficient_evidence','question':plan['question'],'finding':'Need runtime result','counterevidence':'Not observed','recommendation':'Run probe','next_step':{'kind':'experiment','detail':'Execute actual code','experiment':self.probe},'skill_usage':[{'path':'looop:investigation','impact':'Tested implementation'}]}
  rejected={**gap,'status':'rejected','recommendation':'No discrepancy observed'};rejected.pop('next_step')
  run=Mock(side_effect=[json.dumps(v) for v in (plan,gap,rejected)])
  result=research.perform(run,self.repo,self.root/'research','PM','State',Mock(),{'harness':'codex','provider':'codex'})
  self.assertEqual(result['status'],'rejected');self.assertEqual(result['experiments'][0]['exit_code'],0);self.assertNotIn('script',research.brief(result).get('next_step',{}));self.assertEqual(run.call_count,3);self.assertIn('Controller-executed experiment receipt',run.call_args.args[2]);self.assertIn('"exit_code": 0',run.call_args.args[2]);self.assertTrue((self.root/'research/experiment-1/result.json').exists())
