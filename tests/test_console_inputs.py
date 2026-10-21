import concurrent.futures,json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict
from console_actions import execute

class ConsoleInputs(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  (self.root/'data').mkdir();(self.root/'data/control.json').write_text(json.dumps({'projects':{'demo':{}},'agents':{}}))
  self.s=Store(self.root);self.s.ensure('demo')
  self.input={'action':'intent','lane':'demo','revision':0,'request_id':'input-one','kind':'decision','title':'Commercialization','body':'Paid public SaaS and a consistent UI','priority':'high'}
 def test_progress_does_not_block_independent_new_input(self):
  self.s.selection('demo','discovering','PM working')
  before=self.s.read('demo');value=execute(self.input,self.root)
  after=self.s.read('demo');item=after['intents'][value['event']['data']['id']]
  self.assertEqual(item['body'],self.input['body']);self.assertEqual(item['kind'],'decision');self.assertEqual(item['status'],'ready')
  self.assertEqual(after['planning_revision'],before['planning_revision']+1)
  self.assertEqual(after['tasks'],before['tasks']);self.assertEqual(after['config'],before['config'])
  self.assertEqual(after.get('loop_control'),before.get('loop_control'))
 def test_concurrent_independent_inputs_are_preserved(self):
  commands=[{**self.input,'kind':kind,'request_id':kind} for kind in ('decision','requirement')]
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda v:execute(v,self.root),commands))
  self.assertEqual(len(self.s.read('demo')['intents']),2)
  self.assertEqual({r['revision'] for r in results},{1,2})
 def test_uncertain_response_replay_creates_only_one_input(self):
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:execute(self.input,self.root),range(2)))
  self.assertEqual(len(self.s.read('demo')['intents']),1);self.assertEqual(sum(bool(r.get('replayed')) for r in results),1)
  with self.assertRaises(Conflict):execute({**self.input,'body':'Different product direction'},self.root)
 def test_controls_and_existing_intent_edits_still_conflict(self):
  value=execute(self.input,self.root);item=value['event']['data']['id']
  with self.assertRaises(Conflict):
   execute({'action':'loop','lane':'demo','revision':0,'request_id':'stale-pause','mode':'paused'},self.root)
  with self.assertRaises(Conflict):
   self.s.submit('demo',{'type':'priority','intent_id':item,'priority':'urgent','human_confirmed':True},0,'stale-edit','looop-console')
  with self.assertRaises(Conflict):
   self.s.submit('demo',{'type':'supersede_decision','intent_id':item,'title':'Replace','body':'New policy','human_confirmed':True},0,'stale-replace','looop-console')
 def test_other_clients_remain_revision_checked(self):
  execute(self.input,self.root)
  with self.assertRaises(Conflict):
   self.s.submit('demo',{'type':'decision','title':'Terminal input','body':'Policy','human_confirmed':True},0,'terminal','tmux:product')
 def test_future_and_negative_revisions_refused(self):
  for revision in (-1,100):
   with self.assertRaises(Conflict):execute({**self.input,'revision':revision,'request_id':'bad-'+str(revision)},self.root)
  self.assertFalse(self.s.read('demo')['intents'])
