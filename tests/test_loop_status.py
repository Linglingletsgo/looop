import importlib.util,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
spec=importlib.util.spec_from_file_location('loop_status',pathlib.Path(__file__).resolve().parents[1]/'bin/loop-status.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ScopeDescription(unittest.TestCase):
 def test_task_scope_without_allowlist(self):
  self.assertIn('Packet',module.scope_description({}))
 def test_explicit_scope_is_preserved(self):
  self.assertEqual(module.scope_description({'allowed_paths':['a.ts']}),'允许文件：a.ts')
