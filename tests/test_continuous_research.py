import json,pathlib,sys,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy,test_autonomy

class Continuous(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_no_work_rechecks_after_interval_without_manual_start(self):
  self.mandate['max_proposals_per_day']=None
  self.setup_tick()
  class Board:
   def api(self,m,p,d=None):
    if p=='/auth/get-session':return {'user':{'id':'owner'}}
    if m=='POST':return {'id':'pm','identifier':'T-1'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"No supported opportunity yet"}') as run,patch.object(autonomy.time,'time',return_value=10000):
   autonomy.tick('test');count=run.call_count
   autonomy.tick('test');self.assertEqual(run.call_count,count)
   self.assertIn('next_research_at',json.loads((self.root/'data/autonomy/test-status.json').read_text()))
   with patch.object(autonomy.time,'time',return_value=11000):
    autonomy.tick('test')
   self.assertGreater(run.call_count,count)
 def test_once_keeps_no_work_terminal_and_legacy_continuous_rechecks(self):
  receipt={'state':'no_work','started_at':100}
  self.assertIsNone(autonomy.recheck_at(receipt,'once'))
  self.assertEqual(autonomy.recheck_at(receipt,'continuous'),0)
  receipt.update(planning_protocol=2,finished_at=120)
  self.assertEqual(autonomy.recheck_at(receipt,'continuous'),1020)
 def test_only_matching_mainline_is_planning_evidence(self):
  folder=self.root/'data/mainline-verification';folder.mkdir(parents=True)
  p=folder/'test.json';p.write_text(json.dumps({'sha':'other','status':'passed','checks':[]}))
  self.assertNotIn('mainline',autonomy.planning_evidence(self.root,'test',self.repo,self.sha,None))
  p.write_text(json.dumps({'sha':self.sha,'status':'passed','checks':[{'argv':['node','test'],'exit_code':0,'output':'PRIVATE-NOISE'}]}))
  evidence=autonomy.planning_evidence(self.root,'test',self.repo,self.sha,None)
  self.assertIn('mainline',evidence);self.assertNotIn('PRIVATE-NOISE',json.dumps(evidence))
 def test_goal_checks_are_unioned_executed_and_cached_on_exact_sha(self):
  evidence={'mainline':{'checks':[{'argv':['unit'],'exit_code':0}]},'deliveries':[{'checks':[{'argv':['unit'],'exit_code':0},{'argv':['integration'],'exit_code':0}]}]}
  with patch('executor.command',return_value=subprocess.CompletedProcess([],0,'passed')) as run:
   result=autonomy.verify_goal(self.root,'test',self.repo,self.sha,evidence,{'dependencies':'deps'})
   self.assertEqual(run.call_count,2);self.assertEqual(result['status'],'passed')
   autonomy.verify_goal(self.root,'test',self.repo,self.sha,evidence,{'dependencies':'deps'});self.assertEqual(run.call_count,2)
   autonomy.verify_goal(self.root,'test',self.repo,'new',evidence,{'dependencies':'deps'});self.assertEqual(run.call_count,4)
 def test_failed_goal_check_never_becomes_completion_evidence(self):
  evidence={'mainline':{'checks':[{'argv':['integration'],'exit_code':0}]},'deliveries':[]}
  with patch('executor.command',return_value=subprocess.CompletedProcess([],1,'failure')):
   with self.assertRaisesRegex(ValueError,'verification failed'):autonomy.verify_goal(self.root,'test',self.repo,self.sha,evidence,{})
  self.assertEqual(json.loads((self.root/'data/goal-verification/test.json').read_text())['status'],'failed')
