"""Disposable repository integration: inherited config -> builder -> real checks -> reviewer."""
import json,pathlib,sys,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import delivery,test_delivery
from execution_config import inherited_policy

class InheritedDelivery(unittest.TestCase):
 setUp=test_delivery.Delivery.setUp
 tearDown=test_delivery.Delivery.tearDown
 def test_project_scope_real_npm_check_and_independent_review(self):
  (self.repo/'.agent').mkdir();(self.repo/'.agent/project.json').write_text(json.dumps({'version':1,'roles':{},'checks':[['npm','run','test']],'rules':{'common':[]}}))
  (self.repo/'package.json').write_text(json.dumps({'scripts':{'test':'node -e "if(require(\'fs\').readFileSync(\'app.py\',\'utf8\')!==\'value = 1\\n\')process.exit(1)"'}}))
  delivery.git(self.repo,'add','.');delivery.git(self.repo,'commit','-qm','project contract');delivery.git(self.repo,'remote','add','origin','git@github.com:fixture/project.git');(self.repo/'node_modules').mkdir()
  policy=inherited_policy(self.repo);self.packet['baseline_sha']=delivery.git(self.repo,'rev-parse','HEAD').decode().strip();seen=[]
  def model(workspace,*args,**kwargs):
   seen.append(kwargs['role'])
   if kwargs['role']=='builder':(pathlib.Path(workspace)/'app.py').write_text('value = 1\n')
   return '{"verdict":"approved","findings":[]}'
  with patch.object(delivery,'ROOT',self.root),patch.object(delivery,'run',side_effect=model),patch.object(delivery,'command',return_value=subprocess.CompletedProcess([],0,'Verification Agent fixture pass')):result=delivery.execute(self.packet,policy,'inherited-delivery',emit=lambda *_:None,publish=False)
  self.assertEqual(result['state'],'validated');self.assertEqual(seen,['builder','readonly']);self.assertEqual((self.repo/'app.py').read_text(),'value = 0\n')
