import importlib.util,json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store
spec=importlib.util.spec_from_file_location('looop_console',pathlib.Path(__file__).resolve().parents[1]/'bin/console.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Console(unittest.TestCase):
 def test_projection_is_read_only_and_excludes_config_secrets(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'data').mkdir();(root/'data/control.json').write_text(json.dumps({'projects':{'demo':{'repo':'/private/path'},'validate-default':{'repo':'/private/other'}}}))
   s=Store(root);s.ensure('demo',{'secret':'NEVER-PUBLISH'});s.ensure('validate-default');s.selection('demo','waiting','Paused intentionally');before=s.read('demo')['revision']
   value=m.status(root);self.assertEqual(value['tracker'],'local');self.assertNotIn('NEVER-PUBLISH',json.dumps(value));self.assertNotIn('/private/path',json.dumps(value));self.assertEqual(s.read('demo')['revision'],before)
   self.assertFalse({'company','paperclip_id','company_prefix'}&set(value['projects'][0]))
   self.assertFalse(value['projects'][0]['attention']);self.assertTrue(value['projects'][1]['test'])
 def test_blocked_task_is_attention_and_completion_not_active(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'data').mkdir();(root/'data/control.json').write_text(json.dumps({'projects':{'demo':{}}}));s=Store(root);s.ensure('demo');s.bind('demo','one',{'title':'Regression'});s.transition('demo','one','blocked',{'error':'Check failed'})
   value=m.status(root)['projects'][0];self.assertEqual(value['active_count'],1);self.assertEqual(value['attention'][0]['reason'],'Check failed')

 def test_blocked_planning_receipt_overrides_stale_waiting_projection(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'data').mkdir();(root/'data/control.json').write_text(json.dumps({'projects':{'demo':{}}}))
   store=Store(root);store.ensure('demo');store.selection('demo','waiting','Unresolved planning attempt; inspect before replay')
   path=root/'data/autonomy/demo/pm-one/state.json';path.parent.mkdir(parents=True);path.write_text(json.dumps({'state':'blocked','error':'Completion protocol failed','issue':'pm-task'}))
   value=m.status(root)['projects'][0];self.assertEqual(value['phase'],'blocked');self.assertEqual(value['attention'][0]['job'],'pm-one');self.assertEqual(value['attention'][0]['reason'],'Completion protocol failed');self.assertEqual(len(value['attention']),1)
