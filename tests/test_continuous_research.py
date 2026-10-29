import json,pathlib,sys,unittest,subprocess
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy,test_autonomy

class Continuous(unittest.TestCase):
 setUp=test_autonomy.Autonomy.setUp
 tearDown=test_autonomy.Autonomy.tearDown
 setup_tick=test_autonomy.Autonomy.setup_tick
 def test_no_work_rechecks_immediately_without_manual_start(self):
  self.mandate['max_proposals_per_day']=None
  self.setup_tick()
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value='{"action":"no_work","reason":"No supported opportunity yet"}') as run,patch.object(autonomy.time,'time',return_value=10000):
   autonomy.tick('test');count=run.call_count
   self.assertEqual(autonomy.tick('test'),'continue');self.assertGreater(run.call_count,count)
   self.assertNotIn('next_research_at',json.loads((self.root/'data/autonomy/test-status.json').read_text()))
 def test_once_keeps_no_work_terminal_and_legacy_continuous_rechecks(self):
  receipt={'state':'no_work','started_at':100}
  self.assertIsNone(autonomy.recheck_at(receipt,'once'))
  self.assertEqual(autonomy.recheck_at(receipt,'continuous'),0)
  receipt.update(planning_protocol=3,finished_at=120)
  self.assertEqual(autonomy.recheck_at(receipt,'continuous'),0)
 def test_only_matching_mainline_is_planning_evidence(self):
  folder=self.root/'data/mainline-verification';folder.mkdir(parents=True)
  p=folder/'test.json';p.write_text(json.dumps({'sha':'other','status':'passed','checks':[]}))
  self.assertNotIn('mainline',autonomy.planning_evidence(self.root,'test',self.repo,self.sha,None))
  p.write_text(json.dumps({'sha':self.sha,'status':'passed','checks':[{'argv':['node','test'],'exit_code':0,'output':'PRIVATE-NOISE'}]}))
  evidence=autonomy.planning_evidence(self.root,'test',self.repo,self.sha,None)
  self.assertIn('mainline',evidence);self.assertNotIn('PRIVATE-NOISE',json.dumps(evidence))
 def test_planning_evidence_does_not_invent_test_commands(self):
  testdir=self.repo/'tests/integration';testdir.mkdir(parents=True)
  for name in ('old.test.ts','new.test.ts'):(testdir/name).write_text('// synthetic')
  autonomy.git(self.repo,'add','.');autonomy.git(self.repo,'commit','-qm','tests')
  sha=autonomy.git(self.repo,'rev-parse','HEAD').decode().strip()
  folder=self.root/'data/deliveries/one';folder.mkdir(parents=True)
  (folder/'state.json').write_text(json.dumps({'state':'merged','mainline_verified':sha,'target_sha':sha,'round':1}))
  runner=['npm','run','test:integration','--','--configLoader=runner','--no-cache']
  (folder/'checks-1.json').write_text(json.dumps([{'argv':runner+['tests/integration/old.test.ts'],'exit_code':0}]))
  bindings=self.root/'data/delivery-bindings';bindings.mkdir()
  (bindings/'one.json').write_text(json.dumps({'lane':'test','packet':{'allowed_paths':['tests/integration/new.test.ts']}}))
  shared={'product_goal':{'id':'goal','status':'active'},'tasks':{'one':{'goal_id':'goal'}}}
  evidence=autonomy.planning_evidence(self.root,'test',self.repo,sha,shared)
  self.assertNotIn(runner+['tests/integration/new.test.ts'],evidence['goal_checks'])
  # No shell commands or extra files outside the original Packet are inferred.
  self.assertEqual(len(evidence['goal_checks']),1)

 def test_only_current_native_agent_checks_are_forwarded(self):
  folder=self.root/'data/agent-checks/test';folder.mkdir(parents=True)
  for name,sha,executor in [('current',self.sha,'native-agent'),('stale','other','native-agent'),('legacy',self.sha,'controller')]:
   item=folder/name;item.mkdir();(item/'state.json').write_text(json.dumps({'lane':'test','sha':sha,'executor':executor,'state':'validated','argv':['npm','test'],'exit_code':0,'output':'Actual Agent execution'}))
  rows=autonomy.planning_evidence(self.root,'test',self.repo,self.sha,None)['agent_checks']
  self.assertEqual(len(rows),1);self.assertIn('/current/',rows[0]['receipt_path']);self.assertEqual(rows[0]['exit_code'],0)

 def test_continuous_worker_restarts_without_timer_or_sleep(self):
  with patch.object(autonomy,'tick',side_effect=['continue','continue',None]) as tick,patch('loop_control.settle'),patch('loop_control.view',return_value={'mode':'continuous'}),patch.object(autonomy.time,'sleep',side_effect=AssertionError('No research sleep')):
   autonomy.run_loop('test');self.assertEqual(tick.call_count,3)
 def test_worker_respects_pause_between_research_rounds(self):
  with patch.object(autonomy,'tick',return_value='continue') as tick,patch('loop_control.settle'),patch('loop_control.view',return_value={'mode':'paused'}):
   autonomy.run_loop('test');self.assertEqual(tick.call_count,1)
