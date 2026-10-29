import concurrent.futures,importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict,Held,digest
class State(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.s=Store(self.root);self.s.ensure('test')
 def tearDown(self):self.tmp.cleanup()
 def submit(self,kind='requirement',key='r1',**extra):
  return self.s.submit('test',{'type':kind,'title':'Requirement','body':'Explicitly confirmed small requirement','human_confirmed':True,**extra},self.s.read('test')['revision'],key,'tmux:test')
 def test_draft_confirmation_and_idempotency(self):
  result=self.submit('propose');i=result['event']['data']['id'];self.assertEqual(self.s.read('test')['planning_revision'],0)
  command={'type':'confirm','intent_id':i,'human_confirmed':True}
  a=self.s.submit('test',command,1,'confirm','test');b=self.s.submit('test',command,1,'confirm','test');self.assertTrue(b['replayed']);self.assertEqual(a['revision'],b['revision'])
  with self.assertRaises(Conflict):self.s.submit('test',{**command,'intent_id':'different'},1,'confirm','test')
  self.assertEqual(self.s.read('test')['intents'][i]['status'],'ready')
 def test_conflict_and_concurrent_writers(self):
  def submit(n):
   try:return self.s.submit('test',{'type':'propose','title':str(n),'body':'Draft'},0,'key-'+str(n),'test')
   except Conflict:return None
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(submit,[1,2]))
  self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(self.s.read('test')['revision'],1)
 def test_no_execution_or_unconfirmed_effective_intent(self):
  for command in ({'type':'task_transition'},{'type':'requirement','title':'x','body':'x'}):
   with self.assertRaises(ValueError):self.s.submit('test',command,0,'bad','test')
 def test_immutable_contract_transitions_and_terminal(self):
  self.s.bind('test','job',{'title':'old'})
  with self.assertRaises(Conflict):self.s.bind('test','job',{'title':'new'})
  with self.assertRaises(Conflict):self.s.transition('test','job','completed')
  self.s.transition('test','job','completed',import_existing=True)
  with self.assertRaises(Conflict):self.s.transition('test','job','building',import_existing=True)
 def test_stale_plan_cannot_bind(self):
  self.submit()
  with self.assertRaises(Conflict):self.s.bind('test','job',{},planning_revision=0)
  self.assertEqual(self.s.read('test')['tasks'],{})
 def test_change_holds_merge_until_explicit_disposition(self):
  self.s.bind('test','job',{'title':'old'});self.s.transition('test','job','waiting_merge',import_existing=True)
  i=self.submit('change',target_task='job')['event']['data']['id'];calls=[]
  with self.assertRaises(Held):self.s.merge_gate('test','job','sha',lambda:calls.append(1))
  self.assertEqual(calls,[])
  self.s.submit('test',{'type':'resolve_change','intent_id':i,'human_confirmed':True,'resolution':'follow_up'},self.s.read('test')['revision'],'resolve','test')
  self.assertEqual(self.s.read('test')['intents'][i]['status'],'ready')
  self.s.merge_gate('test','job','sha',lambda:{'state':'MERGED'})
  self.assertEqual(self.s.read('test')['tasks']['job']['phase'],'verifying')
  with self.assertRaises(ValueError):self.submit('change',key='late',target_task='job')
 def test_recovery_notes_dont_replace_contract(self):
  self.s.bind('test','job',{'title':'old'})
  self.s.bind('test','job',{'title':'old','execution_notes':'untrusted draft'})
  self.assertNotIn('execution_notes',self.s.read('test')['tasks']['job']['packet'])
 def test_sync_acknowledges_created_intent_outbox_rows(self):
  path=pathlib.Path(__file__).resolve().parents[1]/'bin/state-sync.py';spec=importlib.util.spec_from_file_location('state_sync',path);sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{'id':None}}}))
  self.submit()
  with self.s.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE delivered=0').fetchone()[0],1)
  sync.sync(self.root)
  with self.s.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox WHERE delivered=0').fetchone()[0],0)
  self.assertEqual(len(self.s.read('test')['intents']),1)
  sync.sync(self.root);self.assertEqual(len(self.s.read('test')['intents']),1)

 def test_uncertain_merge_does_not_reopen_change_window(self):
  self.s.bind('test','job',{});self.s.transition('test','job','waiting_merge',import_existing=True)
  def fail():raise ConnectionError('Merge response lost')
  with self.assertRaisesRegex(Held,'uncertain'):self.s.merge_gate('test','job','sha',fail)
  self.assertEqual(self.s.read('test')['tasks']['job']['phase'],'verifying')
  with self.assertRaises(ValueError):self.submit('change',target_task='job')
