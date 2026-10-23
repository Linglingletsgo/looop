"""P1d: bindings without an executable packet are errors, and their receipts stay visible."""
import json,pathlib,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import job_migration
from jobs import Jobs

class Packets(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  self.write('data/control.json',{'projects':{'test':{'id':'project'}},'agents':{}})
 def write(self,name,value):
  path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path

 def test_invalid_packets_are_errors_and_their_receipts_are_orphans(self):
  cases={'missing':None,'empty-list':[],'zero':0,'empty-string':'','empty-object':{},'list':[1]}
  for name,packet in cases.items():
   binding={'lane':'test'} if packet is None else {'lane':'test','packet':packet}
   self.write('data/delivery-bindings/'+name+'.json',binding)
   self.write('data/deliveries/'+name+'/state.json',{'state':'merged'})
  self.write('data/delivery-bindings/good.json',{'lane':'test','packet':{'title':'Good'}})
  result=job_migration.migrate(self.root,apply=True)
  self.assertEqual([row['id'] for row in result['jobs']],['good'])
  self.assertEqual(result['counts']['errors'],len(cases))
  self.assertEqual(sorted(result['orphans']),sorted(cases))
  store=Jobs(self.root)
  for name in cases:self.assertIsNone(store.get(name))
  self.assertEqual(store.get('good')['status'],'todo')

 def test_binding_with_invalid_lane_leaves_its_receipt_as_orphan(self):
  self.write('data/delivery-bindings/bad.json',{'lane':'Bad Lane','packet':{'title':'x'}})
  self.write('data/deliveries/bad/state.json',{'state':'building'})
  result=job_migration.migrate(self.root)
  self.assertEqual(result['orphans'],['bad']);self.assertEqual(result['counts']['errors'],1)

if __name__=='__main__':unittest.main()
