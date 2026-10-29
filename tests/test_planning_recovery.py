import importlib.util,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy,test_state_autonomy
from jobs import Jobs
from tracker import LocalTracker
from process_owner import identity
spec=importlib.util.spec_from_file_location('planning_recovery',pathlib.Path(__file__).resolve().parents[1]/'bin/planning-recovery.py');recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
class Planning(unittest.TestCase):
 setUp=test_state_autonomy.SharedPlanning.setUp
 tearDown=test_state_autonomy.SharedPlanning.tearDown
 setup_tick=test_state_autonomy.SharedPlanning.setup_tick
 setup_shared=test_state_autonomy.SharedPlanning.setup_shared
 def job_ids(self):
  def create(lane,kind,title,status,description='',assignee=None,job_id=None,company=None):return {'id':'delivery-issue' if kind=='delivery' else 'pm-issue','identifier':'T-1'}
  return create
 def state(self):return LocalTracker(Jobs(self.root),self.root)
 def test_interrupted_pm_recovers_once_with_one_delivery(self):
  self.setup_shared()
  config=self.root/'data/control.json';d=json.loads(config.read_text());d['projects']['test']['repo']=str(self.repo);config.write_text(json.dumps(d))
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=KeyboardInterrupt):
   with self.assertRaises(KeyboardInterrupt):autonomy.tick('test')
  receipt=next((self.root/'data/autonomy/test').glob('*/state.json'));s=json.loads(receipt.read_text());s['owner']={**identity(),'boot_id':'old'};receipt.write_text(json.dumps(s))
  self.assertEqual(recovery.reconcile(self.root,self.state())[0]['state'],'retry_pending')
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)) as run:
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,1)
  receipts=[json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json')];self.assertEqual(max(r['planning_restarts'] for r in receipts),1)
  self.assertEqual(len(list((self.root/'data/delivery-bindings').glob('*.json'))),1)
 def test_disabled_lane_is_not_restarted(self):
  self.setup_shared();p=self.root/'data/autonomy-policies/test.json';d=json.loads(p.read_text());d['enabled']=False;p.write_text(json.dumps(d))
  with patch.object(recovery,'alive') as alive:recovery.reconcile(self.root,self.state());alive.assert_not_called()
