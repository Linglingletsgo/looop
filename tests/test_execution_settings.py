import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import execution_settings as settings,activation,delivery,test_delivery,test_autonomy,autonomy
from project_state import Conflict,Store

class Settings(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def command(self):return {'harness':'codex','routes':{s:'codex' for s in settings.STAGES},'codex_model':'gpt-test'}
 def test_revision_idempotency_and_supported_harness_only(self):
  command=self.command();self.assertEqual(settings.save(self.root,command,0,'save')['revision'],1);self.assertTrue(settings.save(self.root,command,0,'save')['replayed'])
  with self.assertRaises(Conflict):settings.save(self.root,command,0,'stale')
  with self.assertRaises(ValueError):settings.save(self.root,{**command,'harness':'pi'},1,'other')
  with self.assertRaises(Conflict):settings.save(self.root,{**command,'codex_model':'other'},0,'save')
 def test_no_secret_and_no_fake_commandcode_model(self):
  command=self.command();command['routes']['build']='commandcode'
  with self.assertRaises(ValueError):settings.save(self.root,command,0,'missing-key')
  (self.root/'secrets').mkdir();(self.root/'secrets/commandcode.key').write_text('NEVER-PUBLISH')
  settings.save(self.root,command,0,'save');self.assertNotIn('NEVER-PUBLISH',json.dumps(settings.public(self.root)))
  self.assertEqual(settings.route(settings.read(self.root),'build'),{'harness':'codex','provider':'commandcode','model':None})
 def test_selection_of_model_and_fallback(self):
  self.assertEqual(settings.route(None,'build','commandcode')['provider'],'commandcode')
  self.assertEqual(settings.route(self.command(),'review')['model'],'gpt-test')

class DeliveryRoutes(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def test_running_delivery_keeps_settings_snapshot(self):
  command={'harness':'codex','routes':{s:'codex' for s in settings.STAGES},'codex_model':'before'};settings.save(self.root,command,0,'before');seen=[]
  def harness(workspace,scratch,prompt,**kwargs):
   seen.append(kwargs['execution_route'])
   if kwargs['role']=='builder':
    (workspace/'app.py').write_text('value = 1\n');settings.save(self.root,{**command,'codex_model':'after'},1,'after')
   return '{"verdict":"approved","findings":[]}'
  fixture=test_delivery.Delivery.execute(self,harness=harness)
  self.assertEqual(fixture['state'],'validated');self.assertEqual({s['model'] for s in seen},{'before'});self.assertEqual(settings.read(self.root)['codex_model'],'after')

class Activation(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_preview_has_concrete_blockers_and_preserves_worktree(self):
  self.setup_tick();(self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps({'version':1,'execution_enabled':False,'roles':{},'workflow_mapping':'Keep black-box acceptance'}));before=autonomy.git(self.repo,'status','--porcelain')
  value=activation.preview(self.root,'test');self.assertFalse(value['ready']);self.assertTrue(any('黑盒' in s for s in value['blockers']));self.assertTrue(any('未提交' in s for s in value['blockers']));self.assertEqual(before,autonomy.git(self.repo,'status','--porcelain'))
  store=Store(self.root);store.ensure('test')
  with self.assertRaises(ValueError):activation.enable(self.root,'test',0,'enable',value['fingerprint'])
  self.assertEqual(store.read('test')['revision'],0)
 def test_adapted_project_can_enable_once_without_dispatch(self):
  self.setup_tick();(self.root/'data/delivery-policies/test.json').unlink();(self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps({'version':1,'roles':{},'checks':[['python3','test.py']]}));autonomy.git(self.repo,'add','.');autonomy.git(self.repo,'commit','-qm','adapter');autonomy.git(self.repo,'remote','add','origin','git@github.com:fixture/project.git');store=Store(self.root);store.ensure('test');calls=[]
  class Board:
   def api(self,m,p,d=None):
    calls.append((m,p))
    return {'id':'agent','adapterConfig':{},'status':'idle'}
  with patch('bridge.validate_profile',return_value={}),patch('board.Board',Board):
   value=activation.preview(self.root,'test');self.assertTrue(value['ready'],value['blockers']);activation.enable(self.root,'test',0,'enable',value['fingerprint']);activation.enable(self.root,'test',0,'enable',value['fingerprint'])
  self.assertTrue((self.root/'data/delivery-policies/test.json').exists());self.assertNotIn('loop_control',store.read('test'));self.assertFalse(any(p.endswith('/issues') for _,p in calls))
