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
