import json,pathlib,sys,tempfile,time,unittest,sqlite3
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from lifecycle import failure,terminal
from health import progress,reconcile
class Lifecycle(unittest.TestCase):
 def test_failure_dispositions(self):
  self.assertTrue(failure('Connection reset by peer')['retryable'])
  for e in ['Provider unavailable/quota','Baseline moved','Round limit reached','Harness failed']:
   self.assertFalse(failure(e)['retryable'])
 def test_terminal_mapping(self):
  self.assertEqual(terminal('merged'),'done');self.assertIsNone(terminal('building'))
 def test_long_silent_run_is_observed_not_killed(self):
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp);(p/'state.json').write_text('{"state":"building"}')
   self.assertTrue(progress(p,time.time()+1000)['needs_attention'])
   self.assertEqual(json.loads((p/'state.json').read_text())['state'],'building')
 def test_completed_planning_cannot_remain_assigned_or_blocked(self):
  with tempfile.TemporaryDirectory() as temp:
   root=pathlib.Path(temp);(root/'data/runs/run').mkdir(parents=True);(root/'data/runs/run/handoff.md').write_text('report')
   with sqlite3.connect(root/'data/bridge.sqlite') as db:
    db.execute('CREATE TABLE jobs (issue TEXT,state TEXT,run_id TEXT,result TEXT)');db.execute("INSERT INTO jobs VALUES ('issue','completed','run','report')")
   patches=[]
   class Board:
    def api(self,method,path,data=None):
     if method=='GET':return {'status':'blocked','assigneeAgentId':'old'}
     patches.append(data)
   self.assertEqual(reconcile(root,Board()),1);self.assertEqual(patches[0]['status'],'done');self.assertIsNone(patches[0]['assigneeAgentId'])

 def test_repeated_commands_are_detected_without_stopping(self):
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp);(p/'state.json').write_text('{"state":"building"}');(p/'builder').mkdir()
   event={'type':'item.completed','item':{'type':'command_execution','command':'same-command'}}
   (p/'builder/events.jsonl').write_text('\n'.join(json.dumps(event) for _ in range(6)))
   self.assertTrue(progress(p)['needs_attention']);self.assertTrue(progress(p)['repeated_command'])
