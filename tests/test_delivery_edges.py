"""P1c edge cases: local-mode robustness and Paperclip company fallback."""
import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from jobs import Jobs
from tracker import LocalTracker,PaperclipTracker

def load(name):
 path=pathlib.Path(__file__).resolve().parents[1]/'bin'/(name+'.py')
 spec=importlib.util.spec_from_file_location(name.replace('-','_')+'_edges',path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

health=load('health');launcher=load('launch_loops')

class Board:
 def __init__(self):self.calls=[]
 def api(self,method,path,data=None):self.calls.append((method,path,data));return []

class Edges(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  for folder in ('data/delivery-policies','logs'):(self.root/folder).mkdir(parents=True)
  (self.root/'data/control.json').write_text(json.dumps({'company':'global-co','projects':{'test':{'id':'project','company':None}},'agents':{'test:delivery':'agent'}}))
  (self.root/'data/delivery-policies/test.json').write_text('{}')
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
 def write(self,relative,value):
  path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

 def test_null_project_company_falls_back_to_global_company(self):
  board=Board();PaperclipTracker(board,self.root).assigned('test','test:delivery',('todo',))
  self.assertTrue(board.calls[-1][1].startswith('/companies/global-co/issues?'))

 def test_broken_job_table_does_not_stop_the_launcher(self):
  (self.root/'data/jobs.sqlite').write_bytes(b'not a database')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root)
  self.assertFalse([c for c in run.call_args_list if c.args[0][:2]==['tmux','new-session']])

 def test_health_local_mode_skips_receipts_without_job_rows(self):
  tracker=LocalTracker(Jobs(self.root),self.root)
  self.write('data/delivery-bindings/orphan.json',{'lane':'test'})
  self.write('data/deliveries/orphan/state.json',{'state':'building'})
  self.write('data/autonomy/test/old/state.json',{'state':'proposing','issue':'paperclip-era-issue'})
  self.assertEqual(health.reconcile(self.root,tracker),0)

if __name__=='__main__':unittest.main()
