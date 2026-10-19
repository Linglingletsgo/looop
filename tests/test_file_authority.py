import json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict
from lifecycle_io import save

class FileAuthority(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name);self.store=Store(self.root);self.store.ensure('demo')
 def test_state_file_is_authority_not_an_export(self):
  p=self.store.document('demo');doc=json.loads(p.read_text());doc.update(revision=1,selection={'phase':'waiting','detail':'external file update'});save(p,doc)
  self.assertEqual(Store(self.root).read('demo')['selection']['detail'],'external file update')
  self.assertEqual(self.store.events('demo')[-1]['revision'],1)
 def test_multiple_projects_never_overwrite_each_other(self):
  self.store.ensure('other');self.store.selection('demo','waiting','one');self.store.selection('other','waiting','two')
  self.assertNotEqual(self.store.document('demo'),self.store.document('other'));self.assertEqual(json.loads(self.store.document('demo').read_text())['selection']['detail'],'one')
 def test_revision_conflict_preserves_file_and_database(self):
  p=self.store.document('demo');doc=json.loads(p.read_text());doc['selection']={'phase':'waiting','detail':'unversioned'};save(p,doc)
  with self.assertRaises(Conflict):self.store.read('demo')
  self.assertEqual(json.loads(p.read_text())['selection']['detail'],'unversioned')
 def test_invalid_json_is_never_overwritten(self):
  p=self.store.document('demo');p.write_text('{broken')
  with self.assertRaises(ValueError):self.store.read('demo')
  self.assertEqual(p.read_text(),'{broken')
 def test_commit_recovery_restores_file_after_interruption(self):
  self.store.selection('demo','waiting','committed');doc=self.store.read('demo');p=self.store.document('demo');save(p.parent/'.state-pending.json',{'lane':'demo','doc':doc});p.unlink()
  self.assertEqual(Store(self.root).read('demo'),doc);self.assertEqual(json.loads(p.read_text()),doc)
 def test_scheduler_and_standalone_share_project_owned_document(self):
  project=Store(self.root/'project');project.ensure('demo');controller=Store(self.root/'scheduler');controller.locations.write_text(json.dumps({'demo':str(project.path)}))
  controller.selection('demo','waiting','agent result');self.assertEqual(project.read('demo')['selection']['detail'],'agent result');self.assertEqual(controller.document('demo'),project.document('demo'))
