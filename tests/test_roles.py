import json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from roles import resolve,contract,RoleError

class Roles(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def put(self,name,text):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
 def test_defaults_fill_absence(self):
  r=resolve(self.root);self.assertEqual(r['project_roles'],[]);self.assertIn('default:v1/builder',contract(r,'builder'))
 def test_arbitrary_project_roles_are_retained(self):
  self.put('.agents/roles/data-steward.md','Custom dataset constraints')
  self.put('.agents/roles/builder.md','Project build contract')
  r=resolve(self.root);self.assertIn('data-steward',r['project_roles']);self.assertIn('Project build contract',contract(r,'builder'));self.assertIn('default:v1/reviewer',contract(r,'reviewer'))
 def test_pm_and_owner_remain_separate(self):
  self.put('docs/project/agent-roles/product-manager.md','Discovery only')
  self.put('docs/project/agent-roles/product.md','Scope coordinator')
  r=resolve(self.root);self.assertIn('Discovery only',contract(r,'product-manager'));self.assertIn('Scope coordinator',contract(r,'product'))
 def test_inline_roles_override_defaults(self):
  self.put('AGENT.md','# Rules\n## Builder Agent\nPreserve migration rules\n## Accessibility Agent\nRead-only audits\n')
  r=resolve(self.root);self.assertIn('accessibility',r['project_roles']);self.assertIn('project:AGENT.md',contract(r,'builder'))
 def test_ambiguous_definitions_require_mapping(self):
  self.put('.agents/roles/reviewer.md','One');self.put('.codex/agents/reviewer.md','Two')
  with self.assertRaises(RoleError):resolve(self.root)
  self.put('.paperclip/roles.json',json.dumps({'version':1,'roles':{'reviewer':'.agents/roles/reviewer.md'}}))
  self.assertIn('One',contract(resolve(self.root),'reviewer'))
 def test_mapping_allows_custom_filename_and_workflow(self):
  self.put('docs/personas/privacy-owner.md','No private data')
  workflow=[{'role':'privacy','stage':'advisory'}]
  self.put('.paperclip/roles.json',json.dumps({'version':1,'roles':{'privacy':'docs/personas/privacy-owner.md'},'workflow':workflow}))
  r=resolve(self.root);self.assertEqual(r['workflow'],workflow);self.assertIn('No private data',contract(r,'privacy'))
 def test_no_silent_default_for_unknown_role(self):
  with self.assertRaises(RoleError):contract(resolve(self.root),'arbitrary-unmapped-role')
 def test_symlink_manifest_and_traversal_rejected(self):
  self.put('.paperclip/roles.json',json.dumps({'version':1,'roles':{'privacy':'../outside.md'}}))
  with self.assertRaises(RoleError):resolve(self.root)
 def test_symlink_role_not_read(self):
  self.put('.agents/roles/.keep','');(self.root/'.agents/roles/reviewer.md').symlink_to('/etc/passwd')
  with self.assertRaises(RoleError):resolve(self.root)
