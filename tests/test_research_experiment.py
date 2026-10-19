import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import research_experiment as experiment
import product_research as research

class Experiments(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir();(self.repo/'value.py').write_text('VALUE=7\n')
  self.probe={'runtime':'python','purpose':'Observe actual implementation','script':'from value import VALUE\nprint(VALUE)'}
  self.value={'exit_code':0,'output':'7','observations':{'value':7},'evidence_path':'observations.json'}
 def execute(self,value=None,**kw):
  with patch('sandbox.run',return_value=json.dumps(value or self.value)) as run:
   self.run=run;return experiment.execute(self.repo,self.root/'experiment-1',self.probe,kw.get('dependencies'),kw.get('fresh',Mock()))
 def test_probe_dispatches_agent_without_executing_proposed_script(self):
  self.probe['script']='raise AssertionError("scheduler must never run this")'
  receipt=self.execute();self.assertEqual(receipt['executor'],'native-agent');self.assertEqual(receipt['exit_code'],0);self.assertEqual(self.run.call_count,1);self.assertIn('You own execution and interpretation',self.run.call_args.args[2]);self.assertEqual((self.repo/'value.py').read_text(),'VALUE=7\n')
 def test_dependencies_are_available_to_native_harness(self):
  deps=self.root/'deps';deps.mkdir();self.execute(dependencies=deps);self.assertEqual(self.run.call_args.kwargs['dependencies'],deps)
 def test_failed_agent_experiment_is_preserved_not_approval(self):
  receipt=self.execute({**self.value,'exit_code':3,'output':'missing prerequisite'});self.assertEqual(receipt['exit_code'],3)
 def test_stale_project_prevents_agent_dispatch(self):
  with patch('sandbox.run') as run,self.assertRaisesRegex(ValueError,'changed'):experiment.execute(self.repo,self.root/'experiment-1',self.probe,None,Mock(side_effect=ValueError('changed')))
  run.assert_not_called()
 def test_source_change_invalidates_context_receipt(self):
  receipt=self.execute();self.assertEqual(experiment.restored(self.repo,self.root),[receipt]);(self.repo/'value.py').write_text('VALUE=8');self.assertEqual(experiment.restored(self.repo,self.root),[])
 def test_missing_exit_code_does_not_invent_success(self):
  with patch('sandbox.run',return_value=json.dumps({'output':'pass'})) as run,self.assertRaises(ValueError):experiment.execute(self.repo,self.root/'experiment-1',self.probe,None,Mock())
  self.assertEqual(run.call_count,3)
 def test_research_request_dispatches_verifier_and_returns_to_pm(self):
  plan={'question':'Does value equal seven?','stop_condition':'Execute synthetic probe','skills':['looop:investigation']}
  gap={'status':'insufficient_evidence','question':plan['question'],'finding':'Need runtime result','counterevidence':'Not observed','recommendation':'Run probe','next_step':{'kind':'experiment','detail':'Execute actual code','experiment':self.probe},'skill_usage':[{'path':'looop:investigation','impact':'Tested implementation'}]}
  rejected={**gap,'status':'rejected'};rejected.pop('next_step');run=Mock(side_effect=[json.dumps(v) for v in (plan,gap,rejected)])
  with patch('sandbox.run',return_value=json.dumps(self.value)) as verifier:
   result=research.perform(run,self.repo,self.root/'research','PM','State',Mock(),{'harness':'codex','provider':'codex'})
  self.assertEqual(result['status'],'rejected');self.assertEqual(verifier.call_count,1);self.assertIn('Verification Agent experiment receipt',run.call_args.args[2])
