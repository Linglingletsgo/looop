import json,pathlib,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import onboarding
from role_install import install_default_roles,plan_default_roles
from roles import resolve

BASE={"version":1,"role_discovery":"auto","roles":{},"rules":{"common":[],"reference":[]},"workflow":[{"stage":"build","role":"builder"},{"stage":"review","role":"reviewer"}],"allowed_paths":[],"checks":[]}

class RoleInstall(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name);self.repo=self.base/'project';self.repo.mkdir()
  subprocess.run(['git','init','-q',str(self.repo)],check=True);self.adapter()
 def tearDown(self):self.tmp.cleanup()
 def adapter(self,value=None):
  path=self.repo/'.agent/project.json';path.parent.mkdir(parents=True,exist_ok=True)
  path.write_text(json.dumps(value or BASE));return path
 def test_empty_project_installs_and_maps_core_roles(self):
  result=install_default_roles(self.repo)
  self.assertEqual(sorted(result['installed']),['builder','product','product-manager','reviewer'])
  self.assertEqual(sorted(result['mapped']),['builder','product','product-manager','reviewer'])
  registry=resolve(self.repo)
  for name in result['installed']:
   target=self.repo/'.agent/roles'/(name+'.md')
   self.assertIn(name,registry['project_roles']);self.assertEqual(registry['roles'][name]['source'],'project:.agent/roles/'+name+'.md')
   self.assertEqual(registry['roles'][name]['text'],'PROJECT ROLE FILE .agent/roles/'+name+'.md\n'+target.read_text())
  self.assertEqual((self.repo/'.agent/roles/builder.md').read_text().splitlines()[0],'<!-- looop default role v1 (builder); project-owned copy, edit freely -->')
  self.assertEqual(json.loads((self.repo/'.agent/project.json').read_text())['roles']['builder'],['.agent/roles/builder.md'])
 def test_undecodable_existing_file_is_skipped_without_partial_install(self):
  (self.repo/'.agent/roles').mkdir();(self.repo/'.agent/roles/builder.md').write_bytes(b'\xff\xfe bad')
  result=install_default_roles(self.repo)
  self.assertEqual(result['skipped'],[{'role':'builder','path':'.agent/roles/builder.md','reason':'existing_different'}])
  self.assertEqual(sorted(result['mapped']),['product','product-manager','reviewer'])
  self.assertEqual((self.repo/'.agent/roles/builder.md').read_bytes(),b'\xff\xfe bad')
 def test_non_string_workflow_role_is_ignored(self):
  self.adapter({**BASE,'workflow':[{'stage':'build','role':1},{'stage':'x','role':None}]})
  self.assertEqual([i['role'] for i in plan_default_roles(self.repo)],['product-manager','product','builder','reviewer'])
 def test_symlinked_role_dir_plans_nothing(self):
  target=self.base/'elsewhere';target.mkdir();(self.repo/'.agent/roles').symlink_to(target)
  self.assertEqual(plan_default_roles(self.repo),[])
 def test_plan_falls_back_to_default_workflow(self):
  self.adapter({**BASE,'workflow':[]});self.assertEqual([i['role'] for i in plan_default_roles(self.repo)],['product-manager','product','builder','reviewer'])
 def test_project_role_files_are_not_installed(self):
  (self.repo/'.agents/roles').mkdir(parents=True);(self.repo/'.agents/roles/builder.md').write_text('Existing builder')
  result=install_default_roles(self.repo)
  self.assertNotIn('builder',result['installed']);self.assertFalse((self.repo/'.agent/roles/builder.md').exists());self.assertEqual((self.repo/'.agents/roles/builder.md').read_text(),'Existing builder')
  self.assertIn('builder',resolve(self.repo)['project_roles']);self.assertEqual(resolve(self.repo)['roles']['builder']['text'],'Existing builder')
 def test_inline_agents_heading_is_project_owned(self):
  (self.repo/'AGENTS.md').write_text('# Rules\n## Builder Agent\nKeep migrations reversible\n')
  result=install_default_roles(self.repo)
  self.assertNotIn('builder',result['installed']);self.assertFalse((self.repo/'.agent/roles/builder.md').exists());self.assertIn('product',result['installed'])
  self.assertIn('project:AGENTS.md#Builder Agent',resolve(self.repo)['roles']['builder']['source'])
 def test_workflow_role_is_installed(self):
  self.adapter({**BASE,'workflow':[{'stage':'build','role':'builder'},{'stage':'verify','role':'qa'}]})
  result=install_default_roles(self.repo);self.assertIn('qa',result['installed'])
  self.assertEqual(json.loads((self.repo/'.agent/project.json').read_text())['roles']['qa'],['.agent/roles/qa.md'])
  self.assertIn('qa',resolve(self.repo)['project_roles'])
 def test_include_all_adds_remaining_defaults(self):
  self.assertEqual({i['role'] for i in plan_default_roles(self.repo,include_all=True)},{'product-manager','product','builder','reviewer','qa','acceptance','ui-designer','ux-designer'})
  result=install_default_roles(self.repo,include_all=True);self.assertIn('ux-designer',result['installed']);self.assertTrue((self.repo/'.agent/roles/acceptance.md').is_file())
 def test_existing_different_file_is_skipped_not_overwritten(self):
  target=self.repo/'.agent/roles/builder.md';target.parent.mkdir(parents=True);target.write_text('Locally edited builder')
  result=install_default_roles(self.repo)
  self.assertEqual([(s['role'],s['reason']) for s in result['skipped']],[('builder','existing_different')])
  self.assertEqual(target.read_text(),'Locally edited builder');self.assertNotIn('builder',json.loads((self.repo/'.agent/project.json').read_text())['roles'])
 def test_existing_mapping_is_preserved(self):
  (self.repo/'docs/team').mkdir(parents=True);(self.repo/'docs/team/builder.md').write_text('Team builder')
  self.adapter({**BASE,'roles':{'builder':['docs/team/builder.md']}})
  result=install_default_roles(self.repo)
  self.assertNotIn('builder',result['installed']);self.assertEqual(json.loads((self.repo/'.agent/project.json').read_text())['roles']['builder'],['docs/team/builder.md'])
  self.assertEqual(resolve(self.repo)['roles']['builder']['source'],'project:docs/team/builder.md')
 def test_identical_existing_file_is_mapped(self):
  from role_install import _content
  target=self.repo/'.agent/roles/builder.md';target.parent.mkdir(parents=True);target.write_text(_content('builder'))
  result=install_default_roles(self.repo)
  self.assertNotIn('builder',result['installed']);self.assertIn('builder',result['mapped']);self.assertEqual(json.loads((self.repo/'.agent/project.json').read_text())['roles']['builder'],['.agent/roles/builder.md'])
  self.assertIn(_content('builder'),resolve(self.repo)['roles']['builder']['text'])
 def test_second_run_is_idempotent(self):
  install_default_roles(self.repo);first=(self.repo/'.agent/project.json').read_bytes();files={p.name:p.read_bytes() for p in (self.repo/'.agent/roles').iterdir()}
  again=install_default_roles(self.repo)
  self.assertEqual((again['installed'],again['mapped'],again['skipped']),([],[],[]))
  self.assertEqual((self.repo/'.agent/project.json').read_bytes(),first);self.assertEqual({p.name:p.read_bytes() for p in (self.repo/'.agent/roles').iterdir()},files)
 def test_symlinked_roles_directory_is_refused(self):
  elsewhere=self.base/'shared';elsewhere.mkdir();(self.repo/'.agent/roles').symlink_to(elsewhere)
  with self.assertRaisesRegex(ValueError,'symlink'):install_default_roles(self.repo)
  self.assertEqual(list(elsewhere.iterdir()),[])
 def test_missing_adapter_is_reported(self):
  (self.repo/'.agent/project.json').unlink()
  result=install_default_roles(self.repo)
  self.assertTrue(result['adapter_missing']);self.assertEqual((result['installed'],result['mapped']),([],[]));self.assertFalse((self.repo/'.agent/project.json').exists());self.assertFalse((self.repo/'.agent/roles').exists())

class OnboardingRoleInstall(unittest.TestCase):
 from test_loop_controls import Onboarding as Fixture
 setUp=Fixture.setUp
 tearDown=Fixture.tearDown
 def controller(self,name):
  root=self.base/name;(root/'data').mkdir(parents=True);(root/'data/control.json').write_text('{"projects":{},"agents":{}}')
  source=pathlib.Path(__file__).resolve().parents[1]/'bin';tools=root/'bin';tools.mkdir()
  for tool in ('project-session.py','project_state.py','state_revisions.py','product_goals.py','lifecycle_io.py'):(tools/tool).write_bytes((source/tool).read_bytes())
  return root
 def test_preview_lists_planned_role_files_readonly(self):
  value=onboarding.preview(self.repo,self.base)
  entry=next(c for c in value['planned_changes'] if c.startswith('.agent/roles/'))
  self.assertTrue(all(n in entry for n in ('product-manager','product','builder','reviewer')))
  self.assertFalse((self.repo/'.agent').exists())
  self.assertEqual(sorted(r['name'] for r in value['roles'] if not r['project_defined']),['acceptance','builder','product','product-manager','qa','reviewer','ui-designer','ux-designer'])
 def test_fingerprint_covers_the_role_plan(self):
  first=onboarding.preview(self.repo,self.base)['fingerprint'];real=onboarding.plan_default_roles
  with patch.object(onboarding,'plan_default_roles',lambda *a,**k:real(*a,**k)+[{'role':'qa','path':'.agent/roles/qa.md','sha256':'x'}]):
   self.assertNotEqual(first,onboarding.preview(self.repo,self.base)['fingerprint'])
 def test_connect_installs_roles_only_when_it_creates_the_adapter(self):
  real=onboarding.preview;root=self.controller('controller')
  with patch.object(onboarding,'preview',side_effect=lambda repo:real(repo,self.base)):
   p=real(self.repo,self.base);result=onboarding.connect(root,self.repo,p['fingerprint'])
  self.assertEqual(sorted(result['default_roles']['installed']),['builder','product','product-manager','reviewer'])
  self.assertIn('builder',resolve(self.repo)['project_roles'])
  other=self.base/'adapted';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:subprocess.run(['git','-C',str(other),'config',k,v],check=True)
  (other/'AGENTS.md').write_text('Own rules\n');(other/'.agent').mkdir();(other/'.agent/project.json').write_text(json.dumps({**BASE,'execution_enabled':False}))
  subprocess.run(['git','-C',str(other),'add','.'],check=True);subprocess.run(['git','-C',str(other),'commit','-qm','fixture'],check=True)
  root2=self.controller('controller2')
  with patch.object(onboarding,'preview',side_effect=lambda repo:real(repo,self.base)):
   p=real(other,self.base);second=onboarding.connect(root2,other,p['fingerprint'])
  third=self.base/'failing';third.mkdir();subprocess.run(['git','init','-q',str(third)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:subprocess.run(['git','-C',str(third),'config',k,v],check=True)
  (third/'README.md').write_text('x\n');subprocess.run(['git','-C',str(third),'add','.'],check=True);subprocess.run(['git','-C',str(third),'commit','-qm','fixture'],check=True)
  with patch.object(onboarding,'preview',side_effect=lambda repo:real(repo,self.base)),patch.object(onboarding,'install_default_roles',side_effect=ValueError('disk full')):
   p=real(third,self.base);failed=onboarding.connect(self.controller('controller3'),third,p['fingerprint'])
  self.assertTrue(failed['connected']);self.assertEqual(failed['default_roles'],{'error':'disk full'})
  self.assertIsNone(second['default_roles']);self.assertFalse((other/'.agent/roles').exists());self.assertEqual(json.loads((other/'.agent/project.json').read_text())['roles'],{})

class CommandLine(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name);self.repo=self.base/'project';self.repo.mkdir()
  (self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps(BASE))
  self.cli=pathlib.Path(__file__).resolve().parents[1]/'bin/install-default-roles.py'
 def tearDown(self):self.tmp.cleanup()
 def run_cli(self,*args):
  return subprocess.run([sys.executable,str(self.cli),*args],capture_output=True,text=True)
 def test_dry_run_prints_plan_and_apply_writes(self):
  dry=self.run_cli('--repo',str(self.repo));self.assertEqual(dry.returncode,0,dry.stderr)
  view=json.loads(dry.stdout);self.assertFalse(view['adapter_missing']);self.assertIsNone(view['blocked'])
  self.assertEqual([i['role'] for i in view['plan']][:4],['product-manager','product','builder','reviewer'])
  self.assertFalse((self.repo/'.agent/roles').exists())
  applied=self.run_cli('--repo',str(self.repo),'--all','--apply');self.assertEqual(applied.returncode,0,applied.stderr)
  self.assertIn('ux-designer',json.loads(applied.stdout)['installed']);self.assertTrue((self.repo/'.agent/roles/ux-designer.md').is_file())
 def test_dry_run_reports_missing_adapter(self):
  (self.repo/'.agent/project.json').unlink()
  self.assertTrue(json.loads(self.run_cli('--repo',str(self.repo)).stdout)['adapter_missing'])
 def test_looop_checkout_is_refused(self):
  result=self.run_cli('--repo',str(self.cli.parents[1]));self.assertNotEqual(result.returncode,0);self.assertIn('Refusing',result.stderr)
