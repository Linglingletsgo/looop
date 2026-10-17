import json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store
from retention import compact_state,trim_log,maintain
class ProjectStorage(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name)
 def tearDown(self):self.t.cleanup()
 def test_project_database_shared_without_controller(self):
  controller=self.root/'controller';project=self.root/'project';s=Store(controller);location=project/'data/project-state/state.sqlite';s.locations.write_text(json.dumps({'demo':str(location)}));s.ensure('demo',{'repository':str(project)})
  s.external_work('demo',{'action':'start','id':'one','summary':'work'},0,'one','chat')
  standalone=Store(project);self.assertEqual(standalone.read('demo')['phase'],'external_work');self.assertEqual(s.lanes(),['demo'])
  with s.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM projects').fetchone()[0],0)
 def test_compaction_keeps_unsynced_and_current_state(self):
  s=Store(self.root);s.ensure('demo')
  for i in range(12):s.selection('demo','waiting',str(i))
  with s.connection('demo') as c:c.execute('UPDATE outbox SET delivered=1 WHERE revision!=1')
  compact_state(s,'demo',3)
  self.assertEqual(s.read('demo')['revision'],12)
  self.assertEqual(len(s.events('demo')),4)
  self.assertTrue(any(e['revision']==1 for e in s.events('demo')))
 def test_log_bound_preserves_inode(self):
  p=self.root/'service.log';p.write_text('line\n'*1000);inode=p.stat().st_ino;self.assertTrue(trim_log(p,100));self.assertLessEqual(p.stat().st_size,100);self.assertEqual(p.stat().st_ino,inode)

 def test_maintenance_keeps_recent_backup_and_prunes_expired(self):
  import os,time
  backups=self.root/'data/backups';backups.mkdir(parents=True)
  for index in range(4):
   folder=backups/str(index);folder.mkdir();(folder/'copy').write_text('backup')
   modified=time.time()-(30-index)*86400;os.utime(folder,(modified,modified))
  report=maintain(self.root)
  self.assertEqual(len(list(backups.iterdir())),3)
  self.assertTrue((self.root/'data/retention-status.json').exists())
