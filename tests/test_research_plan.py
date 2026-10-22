import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).parent))
import test_research_continuation as continuation
from research_plan import normalize,restore
import product_research as research
from handoff import prepare
from looop_support import setUpModule  # noqa: F401

class ResearchPlan(unittest.TestCase):
 def test_optional_null_missing_and_text_are_equivalent(self):
  available=research.catalog(self.repo);original=copy.deepcopy(self.plan_value)
  baseline=normalize(original,self.repo,available)
  self.assertEqual(normalize({**original,'skill_reason':None,'fallback_reason':None},self.repo,available),baseline)
  self.assertEqual(original,self.plan_value)
  self.assertEqual(normalize({**original,'skill_reason':'Relevant method'},self.repo,available)['skill_reason'],'Relevant method')
 def test_required_skill_explanations_still_required(self):
  available=research.catalog(self.repo)
  with self.assertRaisesRegex(ValueError,'Explain missing'):normalize({**self.plan_value,'skills':[],'skill_reason':None},self.repo,available)
  available.append({'path':'project-skill','origin':'project'})
  with self.assertRaisesRegex(ValueError,'explicit gap'):normalize({**self.plan_value,'fallback_reason':None},self.repo,available)
 def test_invalid_type_and_length_have_distinct_field_errors(self):
  for field in ('skill_reason','fallback_reason'):
   with self.assertRaisesRegex(ValueError,field+' must be a string or null'):normalize({**self.plan_value,field:[]},self.repo,research.catalog(self.repo))
   with self.assertRaisesRegex(ValueError,field+' exceeds 2000'):normalize({**self.plan_value,field:'x'*2001},self.repo,research.catalog(self.repo))
 def test_restored_plan_skips_selection_and_preserves_original_handoff(self):
  checkpoint=self.repo/'old';checkpoint.mkdir()
  (checkpoint/'state.json').write_text(json.dumps({'error':'Research plan explanation must be concise'}))
  run=checkpoint/'research-plan-retry-2';run.mkdir()
  identity=prepare(run,{'type':'object'})
  original=json.dumps({**identity,'result':{**self.plan_value,'fallback_reason':None}})
  (run/'handoff.json').write_text(original)
  harness=Mock(return_value=json.dumps(self.supported))
  result=research.perform(harness,self.repo,self.repo/'new','PM','State',Mock(),{'harness':'codex','provider':'codex'},checkpoint=checkpoint)
  self.assertEqual(result['status'],'supported');self.assertEqual(harness.call_count,1)
  self.assertEqual(harness.call_args.args[1].name,'research')
  self.assertTrue((self.repo/'new/research-plan-reused.json').exists())
  self.assertEqual((run/'handoff.json').read_text(),original)
 def test_fresh_state_failure_is_not_swallowed(self):
  checkpoint=self.repo/'old';checkpoint.mkdir()
  (checkpoint/'state.json').write_text(json.dumps({'error':'Research plan explanation must be concise'}))
  run=checkpoint/'research-plan';run.mkdir();identity=prepare(run,{'type':'object'})
  (run/'handoff.json').write_text(json.dumps({**identity,'result':self.plan_value}))
  with self.assertRaisesRegex(ValueError,'State moved'):
   restore(checkpoint,self.repo/'new',self.repo,research.catalog(self.repo),False,Mock(side_effect=ValueError('State moved')))
 def test_unrelated_failure_is_not_replayed(self):
  checkpoint=self.repo/'old';checkpoint.mkdir();(checkpoint/'state.json').write_text('{"error":"Different product blocker"}')
  self.assertIsNone(restore(checkpoint,self.repo/'new',self.repo,research.catalog(self.repo),False,Mock()))
 def setUp(self):
  continuation.ResearchContinuation.setUp(self)
  self.plan_value=self.plan

 def test_failed_experiment_restores_plan_and_unverified_report_not_verdict(self):
  checkpoint=self.repo/'old';checkpoint.mkdir()
  (checkpoint/'state.json').write_text(json.dumps({'error':'Experiment runtime must be python, node or node_ts'}))
  saved={}
  for name,value in (('research-plan',self.plan_value),('research-retry-2',{'status':'supported','finding':'Prior evidence remains unverified','next_step':{'kind':'experiment','detail':'Missing runtime observation'}})):
   run=checkpoint/name;run.mkdir();identity=prepare(run,{'type':'object'})
   saved[name]=json.dumps({**identity,'result':value});(run/'handoff.json').write_text(saved[name])
  harness=Mock(return_value=json.dumps(self.supported))
  result=research.perform(harness,self.repo,self.repo/'new','PM','State',Mock(),{'harness':'codex','provider':'codex'},checkpoint=checkpoint)
  self.assertEqual(harness.call_count,1)
  self.assertIn('Prior evidence remains unverified',harness.call_args.args[2])
  self.assertIn('unverified context',harness.call_args.args[2])
  self.assertEqual(result['status'],'supported')
  for name,original in saved.items():self.assertEqual((checkpoint/name/'handoff.json').read_text(),original)
