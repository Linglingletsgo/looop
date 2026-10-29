"""P1c edge cases: broken job tables and receipts without local job rows."""
import importlib.util,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from jobs import Jobs
from tracker import LocalTracker

def load(name):
 path=pathlib.Path(__file__).resolve().parents[1]/'bin'/(name+'.py')
 spec=importlib.util.spec_from_file_location(name.replace('-','_')+'_edges',path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

health=load('health');launcher=load('launch_loops')

class Edges(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  for folder in ('data/delivery-policies','logs'):(self.root/folder).mkdir(parents=True)
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'test':{}},'agents':{}}))
  (self.root/'data/delivery-policies/test.json').write_text('{}')
  (self.root/'data/local-settings.json').write_text('{"tracker":"local"}')
 def write(self,relative,value):
  path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

 def test_broken_job_table_does_not_stop_the_launcher(self):
  (self.root/'data/jobs.sqlite').write_bytes(b'not a database')
  with patch('subprocess.run',return_value=type('R',(),{'returncode':1})()) as run:
   launcher.launch(self.root)
  self.assertFalse([c for c in run.call_args_list if c.args[0][:2]==['tmux','new-session']])

 def test_health_skips_receipts_without_local_job_rows(self):
  tracker=LocalTracker(Jobs(self.root),self.root)
  self.write('data/delivery-bindings/orphan.json',{'lane':'test'})
  self.write('data/deliveries/orphan/state.json',{'state':'building'})
  self.write('data/autonomy/test/old/state.json',{'state':'proposing','issue':'legacy-issue'})
  self.assertEqual(health.reconcile(self.root,tracker),0)

if __name__=='__main__':unittest.main()
