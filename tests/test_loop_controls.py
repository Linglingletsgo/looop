import importlib.util,json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict,Held
import loop_control as loop
import console_actions as actions
import onboarding
import autonomy

class LoopControls(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
  for d in ('data/autonomy-policies','data/delivery-policies','data/locks'):(self.root/d).mkdir(parents=True,exist_ok=True)
  self.write('data/control.json',{'projects':{'demo':{'profile':'fixture','repo':str(self.root),'id':'project'}},'agents':{'demo:delivery':'agent'}})
  self.write('data/autonomy-policies/demo.json',{'enabled':False});self.write('data/delivery-policies/demo.json',{'enabled':True})
  self.store=Store(self.root);self.store.ensure('demo')
  self.validation=patch('bridge.validate_profile',return_value={});self.validation.start()
 def tearDown(self):self.validation.stop();self.tmp.cleanup()
 def write(self,p,value):
  path=self.root/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
 def switch(self,mode,key='request'):
  return loop.switch(self.root,'demo',mode,self.store.read('demo')['revision'],key)
 def test_legacy_pause_is_unchanged_until_explicit_command(self):
  self.assertEqual(loop.view(self.root,'demo')['mode'],'paused');self.assertNotIn('loop_control',self.store.read('demo'))
 def test_control_idempotency_and_stale_revision(self):
  self.switch('once');v=loop.switch(self.root,'demo','once',0,'request');self.assertTrue(v['replayed'])
  with self.assertRaises(Conflict):loop.switch(self.root,'demo','continuous',0,'other')
 def test_one_shot_claim_survives_reopen_and_cannot_claim_twice(self):
  self.switch('once');loop.claim(self.root,'demo','job');self.assertEqual(Store(self.root).read('demo')['loop_control']['attempt'],'job')
  with self.assertRaises(Conflict):loop.claim(self.root,'demo','another')
  self.write('data/autonomy/demo/job/state.json',{'state':'no_work','reason':'No valuable work'})
  self.assertEqual(loop.settle(self.root,'demo')['mode'],'paused')
 def test_one_shot_waits_for_mainline_verification(self):
  self.switch('once');loop.claim(self.root,'demo','job');self.write('data/autonomy/demo/job/state.json',{'state':'queued','delivery_issue':'task'})
  self.write('data/deliveries/task/state.json',{'state':'merged'});self.assertEqual(loop.settle(self.root,'demo')['mode'],'once')
  self.write('data/deliveries/task/state.json',{'state':'merged','mainline_verified':'sha'});self.assertEqual(loop.settle(self.root,'demo')['mode'],'paused')
 def test_pause_does_not_mutate_bound_tasks(self):
  self.store.bind('demo','task',{'title':'task'});self.switch('paused');self.assertEqual(self.store.read('demo')['tasks']['task']['phase'],'queued')
 def test_no_authority_and_worktree_lanes_cannot_enable(self):
  self.write('data/autonomy-policies/mainline.json',{'enabled':False});self.store.ensure('mainline')
  with self.assertRaises(ValueError):loop.switch(self.root,'mainline','continuous',0,'request')
  (self.root/'data/autonomy-policies/demo.json').unlink()
  with self.assertRaises(ValueError):self.switch('continuous')
 def test_one_shot_cannot_replace_active_task(self):
  self.store.bind('demo','task',{'title':'task'})
  with self.assertRaises(Conflict):self.switch('once')
 def test_switch_cannot_race_external_development(self):
  self.store.external_work('demo',{'action':'start','id':'manual','summary':'Editing'},0,'external','session')
  with self.assertRaises(Held):self.switch('continuous')
 def test_same_baseline_one_shot_can_finish_without_model(self):
  self.store.selection('demo','waiting','Stale waiting reason')
  self.switch('once');loop.finish_without_attempt(self.root,'demo','Baseline already planned');self.assertEqual(loop.view(self.root,'demo')['mode'],'paused')
  doc=self.store.read('demo');self.assertNotEqual(doc['phase'],'waiting');self.assertEqual(doc['selection'],{'phase':'no_work','detail':'Baseline already planned'})
 def test_new_requirement_is_shared_idempotent_and_does_not_resume(self):
  payload={'action':'intent','lane':'demo','revision':0,'request_id':'intent-request','title':'Improve flow','body':'Meaningful observable result','priority':'high'}
  result=actions.execute(payload,self.root);again=actions.execute(payload,self.root)
  self.assertEqual(result['revision'],again['revision']);doc=Store(self.root).context('demo');self.assertEqual(len(doc['intents']),1);self.assertEqual(loop.view(self.root,'demo')['mode'],'paused')
 def test_change_resolution_keeps_immutable_packet(self):
  self.store.bind('demo','task',{'title':'Original'});self.store.submit('demo',{'type':'change','title':'Change','body':'Different scope','target_task':'task','human_confirmed':True},1,'change','session');doc=self.store.read('demo');intent=next(iter(doc['intents']))
  actions.execute({'action':'decision','lane':'demo','intent_id':intent,'resolution':'follow_up','revision':2,'request_id':'resolve'},self.root)
  doc=self.store.read('demo');self.assertEqual(doc['tasks']['task']['packet']['title'],'Original');self.assertFalse(doc['tasks']['task']['holds']);self.assertEqual(doc['intents'][intent]['status'],'ready')
 def test_evidence_does_not_include_raw_logs_or_unrelated_task(self):
  self.store.bind('demo','task',{'title':'Task','acceptance':['Checked']});self.write('data/deliveries/task/state.json',{'state':'blocked','prompt':'SECRET','logs':'SECRET'})
  self.assertNotIn('SECRET',json.dumps(actions.evidence(self.root,'demo','task')))
  with self.assertRaises(ValueError):actions.evidence(self.root,'demo','unknown')
 def test_retry_cannot_cross_project_or_reuse_stale_revision(self):
  self.store.bind('demo','task',{'title':'Task'});self.store.transition('demo','task','blocked');self.write('data/delivery-bindings/task.json',{'lane':'other'})
  with self.assertRaises(Conflict):actions.retry(self.root,'demo','task','Resolved issue',0)
  with self.assertRaises(ValueError):actions.retry(self.root,'demo','task','Resolved issue',2)

class Onboarding(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name);self.repo=self.base/'example';self.repo.mkdir();subprocess.run(['git','init','-q',str(self.repo)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:subprocess.run(['git','-C',str(self.repo),'config',k,v],check=True)
  (self.repo/'AGENTS.md').write_text('Preserve existing project rules.\n');(self.repo/'package.json').write_text(json.dumps({'scripts':{'test':'echo must-not-run'}}));subprocess.run(['git','-C',str(self.repo),'add','.'],check=True);subprocess.run(['git','-C',str(self.repo),'commit','-qm','fixture'],check=True)
 def tearDown(self):self.tmp.cleanup()
 def test_preview_is_readonly_and_reuses_project_roles(self):
  roles=self.repo/'.agents/roles';roles.mkdir(parents=True);(roles/'builder.md').write_text('Existing builder contract')
  before=subprocess.check_output(['git','-C',str(self.repo),'status','--porcelain'])
  value=onboarding.preview(self.repo,self.base);self.assertTrue(next(r for r in value['roles'] if r['name']=='builder')['project_defined']);self.assertEqual([s['stage'] for s in value['workflow']],['build','review']);self.assertEqual(value['checks'],[['npm','run','test']]);self.assertEqual(before,subprocess.check_output(['git','-C',str(self.repo),'status','--porcelain']));self.assertFalse((self.repo/'.agent').exists())
 def test_fingerprint_changes_when_rules_change(self):
  old=onboarding.preview(self.repo,self.base)['fingerprint'];(self.repo/'AGENTS.md').write_text('Changed rules');self.assertNotEqual(old,onboarding.preview(self.repo,self.base)['fingerprint'])
 def test_outside_project_root_is_rejected(self):
  with self.assertRaises(ValueError):onboarding.preview(self.repo,self.base/'elsewhere')
 def test_linked_worktree_is_identified(self):
  worktree=self.base/'ui-worktree';subprocess.run(['git','-C',str(self.repo),'worktree','add','-q','-b','ui',str(worktree)],check=True);self.assertTrue(onboarding.preview(worktree,self.base)['worktree'])
 def test_context_only_connect_preserves_rules_and_owns_state(self):
  root=self.base/'controller';(root/'data').mkdir(parents=True);(root/'data/control.json').write_text('{"projects":{},"agents":{}}');(root/'bin').mkdir()
  source=pathlib.Path(__file__).resolve().parents[1]/'bin'
  for name in ('project-session.py','project_state.py','product_goals.py'):(root/'bin'/name).write_bytes((source/name).read_bytes())
  class Board:
   def api(self,method,path,data=None):
    if method=='GET':return []
    return {'id':'company' if path=='/companies' else 'project'}
  real=onboarding.preview
  with patch.object(onboarding,'preview',side_effect=lambda repo:real(repo,self.base)):
   p=real(self.repo,self.base);result=onboarding.connect(root,self.repo,p['fingerprint'],Board())
  self.assertFalse(result['automatic_scheduling']);self.assertTrue((self.repo/'AGENTS.md').read_text().startswith('Preserve existing project rules.'));self.assertFalse(json.loads((self.repo/'.agent/project.json').read_text())['execution_enabled']);self.assertEqual(Store(root).database('example'),self.repo/'.agent/local/runtime/data/project-state/state.sqlite');self.assertFalse(json.loads((root/'data/control.json').read_text())['agents'])

class SingleRunIntegration(unittest.TestCase):
 from test_autonomy import Autonomy as Fixture
 setUp=Fixture.setUp
 tearDown=Fixture.tearDown
 setup_tick=Fixture.setup_tick
 def test_single_pm_no_work_never_repeats_and_settles(self):
  self.mandate['enabled']=False;self.setup_tick();store=Store(self.root);store.ensure('test')
  with patch('bridge.validate_profile',return_value={}):loop.switch(self.root,'test','once',0,'single')
  class Board:
   def api(self,method,path,data=None):
    if path=='/auth/get-session':return {'user':{'id':'owner'}}
    if method=='POST':return {'id':'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"No valuable work"}') as model:
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(model.call_count,1)
  self.assertEqual(loop.view(self.root,'test')['mode'],'paused');self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_single_paused_during_planning_drains_without_next_selection(self):
  self.mandate['enabled']=False;self.setup_tick();store=Store(self.root);store.ensure('test')
  with patch('bridge.validate_profile',return_value={}):loop.switch(self.root,'test','once',0,'single')
  class Board:
   def api(self,method,path,data=None):
    if path=='/auth/get-session':return {'user':{'id':'owner'}}
    if method=='POST':return {'id':'pm','identifier':'T-1'}
  def model(*args,**kwargs):
   loop.switch(self.root,'test','paused',store.read('test')['revision'],'pause')
   return '{"action":"no_work","reason":"Drained"}'
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model) as run:
   autonomy.tick('test');autonomy.tick('test');self.assertEqual(run.call_count,1)
  self.assertEqual(loop.view(self.root,'test')['mode'],'paused')

 def test_cancelled_planning_failure_does_not_poison_same_baseline_restart(self):
  self.mandate['enabled']=False;self.setup_tick();store=Store(self.root);store.ensure('test');(self.root/'data/project-state/enabled').touch()
  prior=self.root/'data/autonomy/test/old/state.json';prior.parent.mkdir(parents=True)
  prior.write_text(json.dumps({'state':'cancelled','baseline_sha':self.sha,'planning_revision':0,'selected_intent':None,'error':'Research plan schema failed','resolution':{'previous_state':'blocked'}}))
  with patch('bridge.validate_profile',return_value={}):loop.switch(self.root,'test','once',0,'restart')
  class Board:
   def api(self,method,path,data=None):
    if path=='/auth/get-session':return {'user':{'id':'owner'}}
    if method=='POST':return {'id':'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"No ready work after verified research"}') as model:
   autonomy.tick('test');loop.settle(self.root,'test');autonomy.tick('test')
   self.assertEqual(model.call_count,1)
  self.assertEqual(len(list(prior.parent.parent.glob('*/state.json'))),2)
  self.assertEqual(json.loads(prior.read_text())['state'],'cancelled')
  self.assertEqual(store.read('test')['selection']['phase'],'no_work')
 def test_completed_no_work_memo_updates_display_without_another_model_call(self):
  self.mandate['enabled']=False;self.setup_tick();store=Store(self.root);store.ensure('test');(self.root/'data/project-state/enabled').touch()
  prior=self.root/'data/autonomy/test/old/state.json';prior.parent.mkdir(parents=True)
  prior.write_text(json.dumps({'state':'no_work','baseline_sha':self.sha,'planning_revision':0,'selected_intent':None}))
  store.selection('test','waiting','Stale resume message')
  with patch('bridge.validate_profile',return_value={}):loop.switch(self.root,'test','once',store.read('test')['revision'],'restart')
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   autonomy.tick('test');model.assert_not_called()
  self.assertEqual(loop.view(self.root,'test')['mode'],'paused');self.assertEqual(store.read('test')['selection']['phase'],'no_work');self.assertNotEqual(store.read('test')['phase'],'waiting')
