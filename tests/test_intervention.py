import json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from intervention import describe
from console_actions import retry
from project_state import Store,Conflict
class Intervention(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)
  folder=self.root/'data/delivery-bindings';folder.mkdir(parents=True)
  (folder/'task.json').write_text(json.dumps({'lane':'demo','policy':{'repo':'/fixture'},'packet':{'baseline_sha':'abc'}}))
  self.item={'id':'task','phase':'blocked','holds':[],'evidence':{}}
  self.state={'state':'blocked','failed_stage':'building','error':'Connection refused','owner':{'pid':123}}
 def describe(self):return describe(self.root,'demo',self.item,self.state,{'intents':{}})
 @patch('intervention.alive',return_value=False)
 @patch('intervention.subprocess.check_output',return_value='abc\n')
 def test_connection_recovery_explains_rebuild(self,*_):
  value=self.describe();self.assertTrue(value['retry_allowed']);self.assertEqual(value['category'],'connection');self.assertIn('不是从失败阶段',value['retry_effect']);self.assertIn('task',value['diagnostic'])
 @patch('intervention.alive',return_value=False)
 @patch('intervention.subprocess.check_output',return_value='new\n')
 def test_baseline_movement_disables_retry(self,*_):self.assertIn('基线已变化',self.describe()['unavailable_reason'])
 def test_format_failure_requires_preserved_resume(self):
  self.state['failure']={'category':'model_output'};value=self.describe();self.assertFalse(value['retry_allowed']);self.assertIn('同一提交',value['instruction'])
 def test_holds_and_publication_prevent_retry(self):
  self.item['holds']=['change'];self.assertIn('产品决定',self.describe()['unavailable_reason'])
  self.item['holds']=[];self.state['pr_url']='https://github.com/x/y/pull/1';self.assertIn('已有 PR',self.describe()['unavailable_reason'])
 @patch('intervention.alive',return_value=True)
 def test_running_worker_cannot_retry(self,*_):self.assertIn('进程',self.describe()['unavailable_reason'])
 def test_retry_checks_revision_and_server_eligibility(self):
  store=Store(self.root);store.ensure('demo');store.bind('demo','task',{'title':'Example'});store.transition('demo','task','blocked',{'error':'format'})
  folder=self.root/'data/deliveries/task';folder.mkdir(parents=True);(folder/'state.json').write_text(json.dumps({**self.state,'failure':{'category':'model_output'}}))
  with self.assertRaises(Conflict):retry(self.root,'demo','task','fixed',-1)
  with self.assertRaisesRegex(ValueError,'协议'):retry(self.root,'demo','task','fixed',store.read('demo')['revision'])
