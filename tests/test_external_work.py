import importlib.util,json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Held,Conflict
spec=importlib.util.spec_from_file_location('session',pathlib.Path(__file__).resolve().parents[1]/'bin/project-session.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ExternalWork(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name);self.store=Store(self.root);self.store.ensure('demo')
 def tearDown(self):self.t.cleanup()
 def test_manual_blocks_dispatch_and_preserves_task_gates(self):
  s=self.store;s.external_work('demo',{'action':'start','id':'one','summary':'Implement manual task'},0,'start','chat')
  self.assertEqual(s.read('demo')['phase'],'external_work')
  with self.assertRaises(Held):s.project_guard('demo')
  with self.assertRaises(Held):s.bind('demo','job',{'title':'task'})
  s.external_work('demo',{'action':'finish','id':'one','summary':'Changed code; tests not run'},1,'finish','chat')
  self.assertEqual(s.read('demo')['external_work']['one']['verification'],'self_reported');s.project_guard('demo');self.assertEqual(s.read('demo')['tasks'],{})
 def test_active_task_rejects_manual_start(self):
  self.store.bind('demo','job',{'title':'existing'})
  with self.assertRaises(Held):self.store.external_work('demo',{'action':'start','id':'one','summary':'manual'},1,'start','chat')
 def test_source_revision_and_idempotence(self):
  c={'action':'start','id':'one','summary':'manual'};s=self.store;s.external_work('demo',c,0,'same','chat');self.assertTrue(s.external_work('demo',c,0,'same','chat')['replayed'])
  with self.assertRaises(Conflict):s.external_work('demo',{'action':'finish','id':'one','summary':'done'},1,'other','different')
  with self.assertRaises(Conflict):s.external_work('demo',{'action':'progress','id':'one','summary':'progress'},0,'stale','chat')
 def test_standalone_without_paperclip(self):
  repo=self.root/'repo';repo.mkdir();m.operate(repo,'init');m.operate(repo,'start','one','manual');r=m.operate(repo,'finish','one','Finished, self-reported')
  self.assertEqual(r['pending_events'],0);self.assertEqual(m.operate(repo,'context')['project_state']['external_work']['one']['status'],'completed')
 def test_offline_records_survive_and_sync(self):
  repo=self.root/'repo';repo.mkdir();remote=self.root/'remote';Store(remote).ensure('demo');m.operate(repo,'init',runtime=str(remote),lane='demo')
  moved=self.root/'unavailable';remote.rename(moved);r=m.operate(repo,'start','one','offline work');self.assertEqual(r['pending_events'],1);self.assertEqual(m.operate(repo,'context')['local_pending_work']['one']['status'],'active')
  moved.rename(remote);r=m.operate(repo,'sync');self.assertEqual(len(r['accepted']),1);self.assertEqual(m.operate(repo,'context')['project_state']['phase'],'external_work')

 def test_board_mirrors_external_work_without_delivery_task(self):
  spec=importlib.util.spec_from_file_location('state_sync',pathlib.Path(__file__).resolve().parents[1]/'bin/state-sync.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  class Board:
   def __init__(self):self.issues=[];self.posts=0
   def api(self,method,path,data=None):
    if method=='GET':return self.issues
    if method=='POST':self.posts+=1;issue={'id':'issue-one',**data};self.issues.append(issue);return issue
    if method=='PATCH':self.issues[0].update(data);return self.issues[0]
  (self.root/'data/delivery-bindings').mkdir();(self.root/'data/control.json').write_text(json.dumps({'company':'company','projects':{'demo':{'id':'project'}}}))
  s=self.store;s.external_work('demo',{'action':'start','id':'one','summary':'manual'},0,'start','chat');board=Board();module.sync(self.root,board)
  self.assertEqual(board.posts,1);self.assertIn('自述',board.issues[0]['description'])
  s.external_work('demo',{'action':'finish','id':'one','summary':'finished'},1,'finish','chat');module.sync(self.root,board)
  self.assertEqual(board.posts,1);self.assertEqual(board.issues[0]['status'],'done');self.assertEqual(s.read('demo')['tasks'],{})

 def test_standalone_connect_imports_progress_without_duplicate(self):
  repo=self.root/'repo';repo.mkdir();m.operate(repo,'init');m.operate(repo,'start','one','Started locally');m.operate(repo,'finish','one','Finished locally')
  r=m.operate(repo,'connect',runtime=str(self.root),lane='demo');self.assertEqual(len(r['accepted']),2)
  self.assertEqual(self.store.read('demo')['external_work']['one']['status'],'completed');self.assertEqual(m.operate(repo,'sync')['accepted'],[])
