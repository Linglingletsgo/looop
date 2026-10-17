import copy,json,pathlib,sys,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_autonomy,test_loop_controls
import autonomy
from project_state import Store,Conflict
from loop_control import set_settings,view
from task_selection import backlog_items,check_source
from execution_config import inherited_policy,inherited_mandate

class Settings(unittest.TestCase):
 setUp=test_loop_controls.LoopControls.setUp
 tearDown=test_loop_controls.LoopControls.tearDown
 write=test_loop_controls.LoopControls.write
 def test_modes_revisioned_idempotent_and_do_not_start_loop(self):
  self.assertEqual(view(self.root,'demo')['selection_mode'],'backlog_only')
  set_settings(self.root,'demo',None,'backlog_and_research',0,'settings')
  self.assertEqual(Store(self.root).context('demo')['task_selection']['mode'],'backlog_and_research')
  self.assertEqual(view(self.root,'demo')['mode'],'paused');self.assertEqual(self.store.read('demo')['planning_revision'],1)
  self.assertTrue(set_settings(self.root,'demo',None,'backlog_and_research',0,'settings')['replayed'])
  with self.assertRaises(Conflict):set_settings(self.root,'demo',None,'backlog_only',0,'stale')
  with self.assertRaises(ValueError):set_settings(self.root,'demo',None,'other',1,'bad')

class Selection(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_pending_only_and_completed_item_not_repeated(self):
  (self.repo/'backlog.md').write_text('# Old backlog\n- [x] Already done\n- [ ] Pending work with observable outcome\nUnstructured historical idea\n')
  items=backlog_items(self.repo,['backlog.md']);self.assertEqual(len(items),1)
  self.assertEqual(backlog_items(self.repo,['backlog.md'],[items[0]['key']]),[])
  v={'action':'task','backlog_item':{'path':'backlog.md','quote':items[0]['quote']}}
  self.assertEqual(check_source(v,'backlog_only',None,items),items[0]['key'])
  v['backlog_item']['quote']='- [x] Already done'
  with self.assertRaises(ValueError):check_source(v,'backlog_and_research',None,items)
  with self.assertRaises(ValueError):check_source({'action':'task'},'backlog_only',None,items)
  self.assertIsNone(check_source({'action':'task'},'backlog_and_research',None,items))
 def test_empty_backlog_makes_no_model_calls(self):
  self.mandate['backlog_paths']=[];self.setup_tick()
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    return {'id':'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as run:
   autonomy.tick('test');autonomy.tick('test');run.assert_not_called()
  self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_research_without_backlog_allowed_and_scope_preserved(self):
  self.mandate['backlog_paths']=[];self.setup_tick();store=Store(self.root);store.ensure('test');set_settings(self.root,'test',None,'backlog_and_research',0,'research');self.value.pop('backlog_item')
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    return {'id':'delivery' if d and d.get('status')=='backlog' else 'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=[json.dumps(self.value),'{"verdict":"approved"}']):autonomy.tick('test')
  binding=json.loads((self.root/'data/delivery-bindings/delivery.json').read_text());self.assertEqual(binding['policy']['allowed_paths'],['test.py'])
 def test_switch_during_planning_rejects_stale_dispatch(self):
  self.setup_tick();store=Store(self.root);store.ensure('test');(self.root/'data/project-state/enabled').touch()
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    return {'id':'pm','identifier':'T-1'}
  def model(*args,**kwargs):
   set_settings(self.root,'test',None,'backlog_and_research',store.read('test')['revision'],'mode-change');return json.dumps(self.value)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',side_effect=model):
   with self.assertRaises(Conflict):autonomy.tick('test')
  self.assertFalse((self.root/'data/delivery-bindings').exists())
 def test_inherits_project_roles_workflow_checks_without_file_allowlist(self):
  from delivery import validate
  adapter={'version':1,'roles':{},'checks':[['python3','test.py']],'backlog_paths':['spec.py'],'rules':{'common':[]}}
  (self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps(adapter));autonomy.git(self.repo,'remote','add','origin','git@github.com:test/repo.git')
  policy=inherited_policy(self.repo);self.assertEqual(policy['scope_mode'],'task_paths');self.assertEqual([s['stage'] for s in policy['workflow']],['build','review'])
  packet={**self.value['packet'],'allowed_paths':['new_file.py'],'baseline_sha':self.sha};validate(packet,policy)
  restricted={**adapter,'allowed_paths':['test.py']};policy['project_adapter']=restricted;policy['allowed_paths']=['test.py']
  with self.assertRaisesRegex(ValueError,'restrictions'):validate(packet,policy)
  policy.pop('project_adapter');policy['scope_mode']='files';policy['allowed_paths']=['test.py'];
  with self.assertRaises(ValueError):validate(packet,policy)
  self.assertEqual(inherited_mandate(inherited_policy(self.repo))['backlog_paths'],['spec.py'])
  adapter['execution_enabled']=False;(self.repo/'.agent/project.json').write_text(json.dumps(adapter))
  with self.assertRaisesRegex(ValueError,'观察'):inherited_policy(self.repo)
 def test_actual_npm_script_in_host_environment(self):
  from executor import command
  (self.repo/'node_modules').mkdir();(self.repo/'package.json').write_text(json.dumps({'scripts':{'test':'node -e "if(!process.env.HOME.startsWith(\'/home/\'))process.exit(2);console.log(\'fixture passed\')"'}}))
  result=command(self.repo,['npm','run','test'],dependencies=self.repo/'node_modules');self.assertEqual(result.returncode,0,result.stdout);self.assertIn('fixture passed',result.stdout)
