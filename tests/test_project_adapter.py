import importlib.util,json,pathlib,subprocess,sys,tempfile,unittest,copy
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import roles,delivery
from project_adapter import load,context,summary,evidence,check_policy
from project_state import Store
class Adapter(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
  (self.repo/'AGENTS.md').write_text('Mandatory engineering constraints.');(self.repo/'web').mkdir();(self.repo/'web/AGENTS.md').write_text('Mandatory web constraints.')
  (self.repo/'roles').mkdir();(self.repo/'roles/engineer.md').write_text('Engineer contract.');(self.repo/'roles/reviewer.md').write_text('Independent quality review.');(self.repo/'history.md').write_text('Historical handoff, do not inject by default.')
  self.adapter={'version':1,'role_discovery':'explicit','roles':{'builder':['roles/engineer.md'],'reviewer':['roles/reviewer.md']},'rules':{'common':[],'reference':['history.md']},'workflow':[{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'},{'stage':'acceptance','role':'acceptance'}],'checks':[['python3','-m','unittest']],'allowed_paths':['web/app.py']}
 def tearDown(self):self.tmp.cleanup()
 def test_role_context_selects_role_but_keeps_native_rules(self):
  r=roles.resolve(self.repo,self.adapter);self.assertIn('Engineer contract',roles.contract(r,'builder'));self.assertNotIn('quality review',roles.contract(r,'builder'))
  c=context(self.repo,self.adapter,'builder',['web/app.py']);self.assertIn('Mandatory engineering',c);self.assertIn('Mandatory web',c);self.assertNotIn('Historical handoff',c);self.assertNotIn('quality review',c)
  self.assertTrue(roles.fingerprints(r)['acceptance']['source'].startswith('default:'))
 def test_checked_in_manifest_and_bound_copy_must_agree(self):
  (self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps(self.adapter));self.assertEqual(load(self.repo),self.adapter)
  other={**self.adapter,'allowed_paths':['other.py']}
  with self.assertRaisesRegex(ValueError,'differs'):load(self.repo,other)
 def test_path_escape_and_symlink_rejected(self):
  for file in ('../outside','/tmp/x'):
   a={**self.adapter,'roles':{'builder':[file]}}
   with self.assertRaises(ValueError):roles.resolve(self.repo,a)
  (self.repo/'linked.md').symlink_to(self.repo/'AGENTS.md');a={**self.adapter,'rules':{'common':['linked.md']}}
  with self.assertRaises(ValueError):context(self.repo,a,'builder')
 def test_legacy_manifest_conflict_is_explicit(self):
  (self.repo/'.paperclip').mkdir();(self.repo/'.paperclip/roles.json').write_text(json.dumps({'version':1,'roles':{'builder':'history.md'}}))
  with self.assertRaisesRegex(ValueError,'Conflicting'):roles.resolve(self.repo,self.adapter)
 def test_policy_cannot_silently_change_project_workflow(self):
  p={'project_adapter':self.adapter,**{k:self.adapter[k] for k in ('workflow','checks','allowed_paths')}};check_policy(p)
  p['workflow']=p['workflow'][:-1]
  with self.assertRaises(ValueError):check_policy(p)
 def test_standalone_cli_imports_no_board_or_bridge(self):
  script=pathlib.Path(__file__).resolve().parents[1]/'bin/agent-project.py'
  code="import importlib.util,sys;spec=importlib.util.spec_from_file_location('cli',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);import delivery,lifecycle;assert 'board' not in sys.modules and 'bridge' not in sys.modules and 'pipeline' not in sys.modules"
  subprocess.run([sys.executable,'-c',code,str(script)],check=True,env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(script.parent)})
 def test_standalone_and_board_share_core_and_no_replay(self):
  import test_delivery
  fixture=test_delivery.Delivery();fixture.setUp()
  try:
   repo=fixture.repo;config={**self.adapter,'roles':{},'rules':{'common':[]},'allowed_paths':['app.py'],'workflow':fixture.policy['workflow']}
   path=pathlib.Path(__file__).resolve().parents[1]/'bin/agent-project.py';spec=importlib.util.spec_from_file_location('cli',path);cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
   root=fixture.root
   with patch.object(cli,'ROOT',root),patch.object(delivery,'ROOT',root),patch.object(delivery,'run',side_effect=fixture.harness),patch.object(delivery,'command',return_value=subprocess.CompletedProcess([],0,'passed')):
    cli.configure('example',repo,config,fixture.policy);cli.bind('example',fixture.packet,'shared-job');first=cli.run_bound('shared-job')
    binding=json.loads((root/'data/delivery-bindings/shared-job.json').read_text())
    with patch.object(delivery,'run',side_effect=AssertionError('duplicate model call')):
     second=delivery.execute(binding['packet'],binding['policy'],'shared-job',emit=lambda _:None,publish=False)
    self.assertEqual(first['target_sha'],second['target_sha']);self.assertEqual(Store(root).read('example')['tasks']['shared-job']['phase'],'completed')
  finally:fixture.tearDown()
 def test_nested_native_rules_are_bound_evidence(self):
  hashes=evidence(self.repo,self.adapter);self.assertIn('web/AGENTS.md',hashes);self.assertIn('AGENTS.md',hashes)
  (self.repo/'web/AGENTS.md').write_text('Changed web constraint')
  self.assertNotEqual(hashes['web/AGENTS.md'],evidence(self.repo,self.adapter)['web/AGENTS.md'])
 def test_workflow_rules_only_in_coordinator_context(self):
  a=copy.deepcopy(self.adapter);a['rules']['by_role']={'product':['history.md']}
  self.assertNotIn('Historical handoff',context(self.repo,a,'builder',['web/app.py']))
  self.assertIn('Historical handoff',context(self.repo,a,'product',['web/app.py']))
  self.assertIn('history.md',evidence(self.repo,a))
 def test_standalone_pm_is_readonly_and_does_not_bind(self):
  import test_delivery
  fixture=test_delivery.Delivery();fixture.setUp()
  try:
   path=pathlib.Path(__file__).resolve().parents[1]/'bin/agent-project.py';spec=importlib.util.spec_from_file_location('cli',path);cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
   a={**self.adapter,'roles':{},'rules':{},'allowed_paths':['app.py'],'workflow':fixture.policy['workflow']}
   proposal={'action':'task','packet':{k:fixture.packet[k] for k in ('title','requirements','acceptance','allowed_paths')}}
   with patch.object(cli,'ROOT',fixture.root),patch('sandbox.run',return_value=json.dumps(proposal)) as model:
    cli.configure('example',fixture.repo,a,fixture.policy);result=cli.plan('example','Confirm existing synthetic double behavior only','pm-one')
    self.assertFalse(result['bound']);self.assertEqual(model.call_args.kwargs['role'],'readonly');self.assertEqual(Store(fixture.root).read('example')['tasks'],{})
    self.assertTrue((fixture.root/'data/plans/pm-one/packet.json').exists())
  finally:fixture.tearDown()

 def test_context_only_project_cannot_be_enabled_by_policy(self):
  a={**self.adapter,'execution_enabled':False}
  with self.assertRaisesRegex(ValueError,'context-only'):check_policy({'project_adapter':a})
  self.assertIn('Mandatory engineering',context(self.repo,a,'product'))

 def test_new_local_binding_cannot_corrupt_board_linked_lane(self):
  import test_delivery
  fixture=test_delivery.Delivery();fixture.setUp()
  try:
   path=pathlib.Path(__file__).resolve().parents[1]/'bin/agent-project.py';spec=importlib.util.spec_from_file_location('cli',path);cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
   a={**self.adapter,'roles':{},'rules':{},'allowed_paths':['app.py'],'workflow':fixture.policy['workflow']}
   with patch.object(cli,'ROOT',fixture.root):
    cli.configure('example',fixture.repo,a,fixture.policy)
    p=fixture.root/'data/control.json';c=json.loads(p.read_text());c['projects']['example']['id']='native-board-id';p.write_text(json.dumps(c))
    with self.assertRaisesRegex(ValueError,'Paperclip-linked'):cli.bind('example',fixture.packet,'new-job')
    self.assertEqual(Store(fixture.root).read('example')['tasks'],{})
  finally:fixture.tearDown()

 def test_unmapped_project_manifest_stops_execution(self):
  import test_delivery
  fixture=test_delivery.Delivery();fixture.setUp()
  try:
   (fixture.repo/'.agent').mkdir();(fixture.repo/'.agent/project.json').write_text(json.dumps({'version':1,'rules':{}}))
   delivery.git(fixture.repo,'add','.');delivery.git(fixture.repo,'commit','-qm','Project manifest')
   fixture.packet['baseline_sha']=delivery.git(fixture.repo,'rev-parse','HEAD').decode().strip()
   with self.assertRaisesRegex(ValueError,'manifest must be mapped'):fixture.execute()
  finally:fixture.tearDown()
