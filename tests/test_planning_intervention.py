import json,pathlib,sys,tempfile,unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from planning_intervention import preview,retry,blocked_patch
from product_goals import completion_coverage
from project_state import Store,Conflict
import autonomy
class PlanningIntervention(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)
  self.path=self.root/'data/autonomy/demo/pm-one/state.json';self.path.parent.mkdir(parents=True)
  self.state={'state':'blocked','owner':{'pid':0},'issue':'pm-issue','error':'Completion protocol failed','planning_revision':0}
  self.path.write_text(json.dumps(self.state));(self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'id':'project'}}}))
  self.store=Store(self.root);self.store.ensure('demo');self.board=Mock();self.board.api.return_value={'projectId':'project','status':'in_progress'}
 @patch('planning_intervention.alive',return_value=False)
 def test_explicit_retry_preserves_old_proposal_and_releases_only_pm(self,*_):
  proposal=self.path.parent/'proposal.json';proposal.write_text('{"action":"goal_complete"}')
  before=self.store.read('demo')['revision'];retry(self.root,'demo','pm-one','协议修复已核验',before,self.board)
  state=json.loads(self.path.read_text());self.assertEqual(state['state'],'cancelled');self.assertTrue(state['retry_pending']);self.assertEqual(proposal.read_text(),'{"action":"goal_complete"}');self.assertEqual(preview(self.root,'demo'),[])
  self.assertEqual(self.board.api.call_args.args[2]['status'],'cancelled')
  with self.assertRaises(Conflict):retry(self.root,'demo','pm-one','again',before,self.board)
 @patch('planning_intervention.alive',return_value=False)
 def test_binding_uncertainty_disables_retry(self,*_):
  (self.path.parent/'binding-request.json').write_text('{}');self.assertFalse(preview(self.root,'demo')[0]['retry_allowed'])
  with self.assertRaises(ValueError):retry(self.root,'demo','pm-one','checked',0,self.board)
  self.board.api.assert_not_called()
 @patch('planning_intervention.alive',return_value=True)
 def test_live_owner_disables_retry(self,*_):self.assertFalse(preview(self.root,'demo')[0]['retry_allowed'])
 @patch('planning_intervention.alive',return_value=False)
 def test_board_failure_retains_blocked_receipt(self,*_):
  self.board.api.side_effect=RuntimeError('offline')
  with self.assertRaises(RuntimeError):retry(self.root,'demo','pm-one','checked',0,self.board)
  self.assertEqual(json.loads(self.path.read_text())['state'],'blocked')
 def test_blocked_payload_has_real_recovery_descriptor(self):
  payload=blocked_patch('schema failed');self.assertEqual(payload['status'],'blocked');self.assertEqual(payload['unblockDescriptor']['owner'],'board');self.assertTrue(payload['unblockDescriptor']['action'])
 def test_blocked_pm_is_not_generic_waiting(self):
  with patch('execution_settings.read',return_value={}),patch('autonomy.paused',return_value=None):
   self.assertIn('PM 规划受阻：Completion protocol failed',autonomy.slots(self.root,'demo',{}))
 def test_multiple_proofs_and_order_preserve_exact_coverage(self):
  evidence=[{'criterion':'B'},{'criterion':'A'},{'criterion':'A'}]
  self.assertEqual(completion_coverage(evidence,['A','B']),evidence)
  for bad in ([{'criterion':'A'}],[{'criterion':'A'},{'criterion':'B'},{'criterion':'invented'}],[],[{'criterion':[]} ]):
   with self.assertRaises(ValueError):completion_coverage(bad,['A','B'])

 def prepare_completion(self):
  import subprocess
  from repository import git
  from handoff import prepare
  self.repo=self.root/'repo';self.repo.mkdir()
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  git(self.repo,'config','user.name','Synthetic');git(self.repo,'config','user.email','test@example.test')
  (self.repo/'spec.md').write_text('Observed completed outcome')
  git(self.repo,'add','.');git(self.repo,'commit','-qm','baseline')
  self.sha=git(self.repo,'rev-parse','HEAD').decode().strip()
  goal={'title':'Outcome','user_value':'Observable benefit','success_criteria':['Observed outcome'],'remaining':['Verify outcome'],'progress':'Delivered','slice_value':'Full outcome'}
  self.store.bind('demo','task',{},provenance={'product_goal':goal})
  self.store.transition('demo','task','completed',import_existing=True)
  doc=self.store.read('demo');goal=doc['product_goal']
  self.state.update(goal_id=goal['id'],planning_revision=doc['planning_revision'],baseline_sha=self.sha)
  self.path.write_text(json.dumps(self.state))
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'id':'project','repo':str(self.repo)}}}))
  scratch=self.path.parent/'pm';scratch.mkdir();identity=prepare(scratch,{'type':'object'})
  (scratch/'report.md').write_text('Baseline '+self.sha+': Verified outcome')
  self.value={'action':'goal_complete','goal_id':goal['id'],'reason':'Verified delivered outcome','completion_evidence':[{'criterion':'Observed outcome','kind':'runtime_check','path':'report.md','target_sha':self.sha,'quote':'Verified outcome'}]}
  (scratch/'handoff.json').write_text(json.dumps({**identity,'result':self.value}))
  self.before=self.store.read('demo')['revision']
 @patch('planning_intervention.alive',return_value=False)
 def test_saved_completion_runs_zero_models_and_preserves_handoff(self,*_):
  from planning_intervention import resume_completion
  self.prepare_completion();p=self.path.parent/'pm/handoff.json';before=p.read_bytes()
  with patch('sandbox.run',side_effect=AssertionError('No model calls')):
   result=resume_completion(self.root,'demo','pm-one','Evidence resolver repaired',self.before,self.board)
  self.assertEqual(result['model_calls'],0);self.assertTrue(result['goal_completed'])
  self.assertEqual(p.read_bytes(),before)
  self.assertEqual(self.store.read('demo')['product_goal']['status'],'completed')
  state=json.loads(self.path.read_text());self.assertEqual(state['state'],'no_work');self.assertNotIn('error',state)
  self.assertEqual(self.board.api.call_args.args[2]['status'],'done')
 @patch('planning_intervention.alive',return_value=False)
 def test_saved_completion_rejects_stale_contract_dirty_code_and_invented_proof(self,*_):
  from planning_intervention import resume_completion
  from repository import git
  self.prepare_completion()
  with self.assertRaises(Conflict):resume_completion(self.root,'demo','pm-one','Evidence repaired',self.before-1,self.board)
  (self.repo/'spec.md').write_text('Dirty')
  with self.assertRaisesRegex(ValueError,'dirty'):resume_completion(self.root,'demo','pm-one','Evidence repaired',self.before,self.board)
  git(self.repo,'checkout','--','spec.md')
  (self.path.parent/'pm/report.md').write_text('No execution proof')
  with self.assertRaisesRegex(ValueError,'not found'):resume_completion(self.root,'demo','pm-one','Evidence repaired',self.before,self.board)
  self.assertEqual(self.store.read('demo')['product_goal']['status'],'active')
  self.board.api.assert_not_called()
 @patch('planning_intervention.alive',return_value=True)
 def test_saved_completion_rejects_live_owner(self,*_):
  from planning_intervention import resume_completion
  self.prepare_completion()
  with self.assertRaisesRegex(ValueError,'stopped'):resume_completion(self.root,'demo','pm-one','Evidence repaired',self.before,self.board)

 @patch('planning_intervention.alive',return_value=False)
 def test_legacy_source_binding_recovery_marks_original_proposal_for_revalidation(self,*_):
  self.state['error']='No executable confirmed requirement selected';self.path.write_text(json.dumps(self.state))
  proposal=self.path.parent/'proposal.json';proposal.write_text('{"action":"task","intent_ids":["decision"]}')
  original=proposal.read_bytes()
  retry(self.root,'demo','pm-one','Source binding corrected',self.store.read('demo')['revision'],self.board)
  self.assertEqual(json.loads(self.path.read_text())['reuse_saved_proposal'],'pm-one')
  self.assertEqual(proposal.read_bytes(),original)
