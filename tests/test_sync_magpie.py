import importlib.util,json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
path=pathlib.Path(__file__).resolve().parents[1]/'bin/sync-magpie-subagents.py'
spec=importlib.util.spec_from_file_location('sync_magpie_subagents',path);sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
MANIFEST=json.loads((pathlib.Path(__file__).resolve().parents[1]/'pm-skills/manifest.json').read_text())

class Pack(unittest.TestCase):
 def test_opt_out_exports_only_mit_methods_and_retires_the_pack(self):
  specs,names,retired=sync.pack_skills(MANIFEST,False)
  self.assertEqual(names,['pm-research-core','pm-opportunities','pm-backlog-prioritization','pm-requirement-brief','pm-assumption-testing'])
  self.assertEqual(retired,['pm-investigation','pm-competitive-research'])
  self.assertEqual(len(specs),len(MANIFEST['skills']))
 def test_opt_in_exports_the_pack_and_retires_the_mit_base(self):
  specs,names,retired=sync.pack_skills(MANIFEST,True)
  self.assertEqual(sorted(names),['pm-assumption-testing','pm-backlog-prioritization','pm-competitive-research','pm-investigation','pm-opportunities','pm-requirement-brief'])
  self.assertEqual(retired,['pm-research-core'])
  self.assertEqual(len(specs),len(MANIFEST['skills']))

class Bindings(unittest.TestCase):
 def test_opt_out_prunes_pack_and_keeps_other_bindings(self):
  skills=['project-review-method','pm-investigation','pm-requirement-brief','pm-competitive-research']
  result,pruned=sync.role_skills(skills,['pm-research-core','pm-opportunities'],['pm-investigation','pm-competitive-research'])
  self.assertEqual(result,['project-review-method','pm-requirement-brief','pm-research-core','pm-opportunities'])
  self.assertEqual(pruned,['pm-investigation','pm-competitive-research'])
 def test_opt_in_unions_without_pruning_or_reordering_previous(self):
  skills=['project-review-method','pm-research-core','pm-investigation']
  result,pruned=sync.role_skills(skills,['pm-investigation','pm-opportunities'],['pm-research-core'])
  self.assertEqual(result,['project-review-method','pm-investigation','pm-opportunities'])
  self.assertEqual(pruned,['pm-research-core'])

class Ownership(unittest.TestCase):
 def test_only_own_export_folder_is_removed(self):
  self.assertTrue(sync.owns_export({'source':{'kind':'folder','dir':'/tmp/lib/pm-investigation'}},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({'source':{'kind':'folder','dir':'/tmp/other/pm-investigation'}},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({'source':'https://github.com/x/y'},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({},'/tmp/lib/pm-investigation'))
 def test_flattened_api_source_string_is_accepted_for_folders_only(self):
  self.assertTrue(sync.owns_export({'kind':'folder','source':'/tmp/lib/pm-investigation'},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({'kind':'folder','source':'/tmp/other/pm-investigation'},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({'kind':'github','source':'/tmp/lib/pm-investigation'},'/tmp/lib/pm-investigation'))
  self.assertFalse(sync.owns_export({'kind':'folder','source':''},'/tmp/lib/pm-investigation'))
 def test_relative_library_path_resolves_against_repository_root(self):
  folder=sync.ROOT/'data/magpie-pm-skills/pm-investigation'
  self.assertTrue(sync.owns_export({'source':{'kind':'folder','dir':'data/magpie-pm-skills/pm-investigation'}},folder))
