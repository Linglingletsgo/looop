import json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import test_state_autonomy
import binding_requests as requests
class Binding(unittest.TestCase):
 setUp=test_state_autonomy.SharedPlanning.setUp
 tearDown=test_state_autonomy.SharedPlanning.tearDown
 setup_tick=test_state_autonomy.SharedPlanning.setup_tick
 setup_shared=test_state_autonomy.SharedPlanning.setup_shared
 def setup_request(self):
  self.setup_shared();self.binding={'lane':'test','intent_ids':[self.intent],'packet':{**self.value['packet'],'baseline_sha':self.sha},'policy':self.policy,'publish':False,'owner':'owner'}
  self.folder=self.root/'data/autonomy/test/attempt';self.rows=[];parent=self
  class Board:
   lose=True
   posts=0
   def api(self,m,p,d=None):
    if m=='POST':
     self.posts+=1;parent.rows.append({'id':'issue','identifier':'T-1',**d})
     if self.lose:self.lose=False;raise ConnectionError('Response lost after issue creation')
     return parent.rows[-1]
    if m=='GET' and p.startswith('/issues/'):return parent.rows[-1]
    if m=='GET':return parent.rows
  self.board=Board()
 def begin(self):return requests.create(self.root,self.board,self.folder,self.binding,'company',{'projectId':'project','status':'backlog','title':'Task'},1)
 def test_remote_creation_succeeded_response_lost_reconciles_once(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'bound')
  self.assertEqual(requests.reconcile(self.root,self.board),[]);self.assertEqual(self.board.posts,1)
  self.assertEqual(self.store.read('test')['intents'][self.intent]['status'],'scheduled')
  self.assertTrue((self.root/'data/delivery-bindings/issue.json').exists())
 def test_no_match_or_duplicate_never_reposts(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  original=list(self.rows);self.rows.clear();self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'deferred')
  self.rows.extend(original*2);self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'deferred');self.assertEqual(self.board.posts,1)
 def test_manual_cancellation_and_changed_policy_preserved(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  self.rows[0]['status']='cancelled';self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'deferred')
  self.rows[0]['status']='backlog';p=self.root/'data/delivery-policies/test.json';p.write_text('{}')
  self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'deferred');self.assertFalse((self.root/'data/delivery-bindings/issue.json').exists())
 def test_new_decision_rejects_stale_unbound_packet(self):
  self.setup_request()
  with self.assertRaises(ConnectionError):self.begin()
  self.store.submit('test',{'type':'decision','title':'Changed','body':'Changed intent','human_confirmed':True},self.store.read('test')['revision'],'changed','human')
  self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'deferred');self.assertFalse((self.root/'data/delivery-bindings/issue.json').exists())
 def test_shared_bind_saved_but_file_write_interrupted_can_finish(self):
  self.setup_request();self.board.lose=False
  original=requests.save
  def save(path,value):
   if path.parent.name=='delivery-bindings':raise OSError('Disk interrupted')
   return original(path,value)
  with patch.object(requests,'save',side_effect=save),self.assertRaises(OSError):self.begin()
  self.assertIn('issue',self.store.read('test')['tasks']);self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'bound');self.assertEqual(self.board.posts,1)
 def test_final_journal_write_lost_after_dispatch_does_not_rebind(self):
  self.setup_request();self.board.lose=False;original=requests.save
  def save(path,value):
   if path.name=='binding-request.json' and value['state']=='bound':raise OSError('Final journal update lost')
   return original(path,value)
  with patch.object(requests,'save',side_effect=save),self.assertRaises(OSError):self.begin()
  self.rows[0]['status']='todo'
  self.assertEqual(requests.reconcile(self.root,self.board)[0]['state'],'bound');self.assertEqual(self.board.posts,1)
 def test_lost_create_response_full_planner_to_dispatch_cycle(self):
  import autonomy,dispatch
  self.setup_shared();rows=[];calls=[];value=self.value
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    if m=='POST':
     if d['status']=='backlog':rows.append({'id':'delivery-issue','identifier':'T-2',**d});raise ConnectionError('Create response lost')
     return {'id':'pm-issue','identifier':'T-1',**d}
    if m=='GET' and p.startswith('/companies/'):return rows
    if m=='GET':return dict(rows[0])
    calls.append((p,d))
    if p=='/issues/delivery-issue':rows[0].update(d)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(value)) as model:
   with self.assertRaises(ConnectionError):autonomy.tick('test')
   requests.reconcile(self.root,Board());dispatch.reconcile(self.root,Board());dispatch.reconcile(self.root,Board())
   autonomy.tick('test');self.assertEqual(model.call_count,1)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'todo');self.assertEqual(len(list((self.root/'data/delivery-bindings').glob('*.json'))),1)
  state=json.loads(next((self.root/'data/autonomy/test').glob('*/state.json')).read_text());self.assertEqual(state['state'],'queued')
 def test_identical_operator_submission_uses_same_journal(self):
  import importlib.util
  self.setup_request();self.board.lose=False
  path=pathlib.Path(__file__).resolve().parents[1]/'bin/delivery-control.py';spec=importlib.util.spec_from_file_location('control_binding_test',path);control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
  cfg=json.loads((self.root/'data/control.json').read_text());packet=self.root/'operator-packet.json';packet.write_text(json.dumps(self.binding['packet']))
  board=self.board;api=board.api
  def call(m,p,d=None):
   if p=='/auth/get-session':return {'user':{'id':'owner'}}
   if m=='PATCH':self.rows[0].update(d);return self.rows[0]
   return api(m,p,d)
  with patch.object(control,'ROOT',self.root),patch.object(control,'config',return_value=cfg),patch.object(control,'validate_profile'),patch.object(control,'Board',return_value=board),patch.object(board,'api',side_effect=call):
   control.submit('test',str(packet),False);control.submit('test',str(packet),False)
  self.assertEqual(self.board.posts,1);self.assertEqual(len(self.rows),1)
