import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
from project_state import Store,Conflict,Held
from product_goals import proposal,summary,completion_coverage
from source_evidence import verify_completion
import product_research as research
import loop_control
from looop_support import setUpModule  # noqa: F401

GOAL={'title':'比较机会时能核对日期和费用的来源','user_value':'用户可以可靠比较机会，避免按错配日期和费用行动。','success_criteria':['日期费用关联到同一机会的可追溯来源','比较页面展示缺失证据状态'],'remaining':['来源关联','比较页面与异常提示'],'progress':'已确认现有产品缺口，尚未开发','slice_value':'先保留结构化来源，为比较界面提供可靠输入'}

class Goals(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.s=Store(self.root);self.s.ensure('demo')
 def tearDown(self):self.tmp.cleanup()
 def intent(self):return self.s.submit('demo',{'type':'requirement','title':GOAL['title'],'body':GOAL['user_value'],'human_confirmed':True},self.s.read('demo')['revision'],'request','chat')['event']['data']['id']
 def test_many_slices_keep_requirement_open_until_goal_evidence(self):
  intent=self.intent();self.s.bind('demo','one',{'title':'第一切片'},[intent],{'product_goal':GOAL},planning_revision=1)
  self.s.transition('demo','one','completed',{'target_sha':'one','mainline_verified':True},import_existing=True)
  doc=self.s.read('demo');self.assertEqual(doc['intents'][intent]['status'],'scheduled');self.assertEqual(doc['product_goal']['completed_slices'],1);self.assertEqual(doc['phase'],'ready')
  self.s.transition('demo','one','completed',{'extra':'new evidence'});self.assertEqual(self.s.read('demo')['product_goal']['completed_slices'],1)
  next_goal={**GOAL,'remaining':['比较页面与异常提示'],'progress':'来源关联已交付','slice_value':'让用户在页面核对来源'}
  self.s.bind('demo','two',{'title':'第二切片'},[intent],{'product_goal':next_goal},planning_revision=1)
  self.s.transition('demo','two','completed',import_existing=True);current=self.s.read('demo')['product_goal'];self.assertEqual(current['id'],doc['product_goal']['id'])
  with self.assertRaises(ValueError):self.s.finish_goal('demo',current['id'],'已完成',[],1)
  self.s.finish_goal('demo',current['id'],'已核验全部结果',[{'criterion':v,'path':'proof','quote':'actual outcome evidence'} for v in GOAL['success_criteria']],1)
  doc=self.s.read('demo');self.assertEqual(doc['product_goal']['status'],'completed');self.assertEqual(doc['intents'][intent]['status'],'completed');self.assertEqual(doc['planning_revision'],2)
 def test_cannot_swap_goal_or_finish_while_slice_active(self):
  self.s.bind('demo','one',{},provenance={'product_goal':GOAL});current=self.s.read('demo')['product_goal']
  with self.assertRaises(ValueError):self.s.bind('demo','two',{},provenance={'product_goal':{**GOAL,'title':'Unrelated'}})
  with self.assertRaises(Conflict):self.s.bind('demo','two',{})
  with self.assertRaises(Held):self.s.finish_goal('demo',current['id'],'done',[{},{}],0)
  self.s.transition('demo','one','blocked',{'error':'check failed'});self.assertEqual(self.s.read('demo')['product_goal']['status'],'blocked')
  self.s.transition('demo','one','queued');self.assertEqual(self.s.read('demo')['product_goal']['status'],'active')
 def test_one_shot_continues_same_goal_but_pause_is_respected(self):
  self.s.bind('demo','one',{},provenance={'product_goal':GOAL});self.s.transition('demo','one','completed',import_existing=True)
  def control(doc):doc['loop_control']={'mode':'once','run_id':'run','attempt':'pm-one','status':'running'};return {}
  self.s.mutate('demo','switch',{'type':'test'},control)
  p=self.root/'data/autonomy/demo/pm-one/state.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'delivery_issue':'one','state':'queued'}))
  p=self.root/'data/deliveries/one/state.json';p.parent.mkdir(parents=True);p.write_text('{"state":"merged","mainline_verified":true}')
  value=loop_control.settle(self.root,'demo');self.assertEqual(value['mode'],'once');self.assertNotIn('attempt',value)
  loop_control.switch(self.root,'demo','paused',self.s.read('demo')['revision'],'pause');self.assertEqual(loop_control.settle(self.root,'demo')['mode'],'paused')
 def test_read_same_project_state_without_paperclip_and_external_progress(self):
  self.s.bind('demo','one',{},provenance={'product_goal':GOAL});self.s.transition('demo','one','completed',import_existing=True)
  self.s.external_work('demo',{'action':'start','id':'manual','summary':'正在核对比较页面'},self.s.read('demo')['revision'],'manual','cli')
  self.assertEqual(Store(self.root).context('demo')['product_goal']['progress'],'正在核对比较页面')
  self.assertEqual(Store(self.root).context('demo')['product_goal']['progress_verification'],'self_reported')

 def experience_goal(self):
  return {**GOAL,'experience':{'journey':'描述需求、比较候选、打开投稿入口','before':'难以判断下一步','after':'无需说明即可选择候选并行动','criterion':GOAL['success_criteria'][1]}}
 def test_experience_contract_is_visible_and_immutable_across_slices(self):
  goal=self.experience_goal();self.s.bind('demo','one',{},provenance={'product_goal':goal})
  current=self.s.read('demo')['product_goal']
  self.assertEqual(summary({'product_goal':current})['experience'],goal['experience'])
  self.assertEqual(proposal(GOAL,current)['experience'],goal['experience'])
  with self.assertRaisesRegex(ValueError,'cannot change'):proposal({**goal,'experience':{**goal['experience'],'after':'Different outcome'}},current)
  with self.assertRaisesRegex(ValueError,'cannot change'):proposal(goal,{**current,'experience':None})
  with self.assertRaisesRegex(ValueError,'exact success criterion'):proposal({**goal,'experience':{**goal['experience'],'criterion':'Invented'}})
 def test_experience_completion_rejects_only_code_counts_stale_or_invented_proof(self):
  goal=self.experience_goal();repo=self.root/'repo';repo.mkdir();(repo/'proof.md').write_text('Source implementation')
  artifacts=self.root/'run';artifacts.mkdir();(artifacts/'walkthrough.txt').write_text('Agent exercised comparison and opened the selected entry; loading and recovery checked. No real user study.')
  evidence=[{'criterion':v,'path':'proof.md','quote':'Source implementation'} for v in goal['success_criteria']]
  with self.assertRaisesRegex(ValueError,'walkthrough'):completion_coverage(evidence,goal['success_criteria'],goal['experience'])
  evidence[1].update(kind='agent_walkthrough',path='walkthrough.txt',quote='Agent exercised comparison and opened the selected entry',target_sha='a'*40)
  verify_completion(repo,artifacts,goal,evidence,'a'*40)
  with self.assertRaisesRegex(ValueError,'another revision'):verify_completion(repo,artifacts,goal,evidence,'b'*40)
  evidence[1]['quote']='Users loved the experience'
  with self.assertRaisesRegex(ValueError,'not found'):verify_completion(repo,artifacts,goal,evidence,'a'*40)
  evidence[1]['path']='../repo/proof.md'
  with self.assertRaises(ValueError):verify_completion(repo,artifacts,goal,evidence,'a'*40)
 def test_legacy_goal_needs_no_experience_and_manual_finish_cannot_skip_it(self):
  legacy=proposal(GOAL);self.assertNotIn('experience',legacy)
  self.s.bind('demo','one',{},provenance={'product_goal':self.experience_goal()});self.s.transition('demo','one','completed',import_existing=True)
  goal=self.s.read('demo')['product_goal']
  with self.assertRaisesRegex(ValueError,'walkthrough'):self.s.finish_goal('demo',goal['id'],'Merged and tests passed',[{'criterion':v,'path':'proof'} for v in goal['success_criteria']],0)
  self.assertEqual(self.s.read('demo')['product_goal']['status'],'active')

 def test_active_slice_can_omit_contract_and_cannot_alias_current_state(self):
  current={**self.experience_goal(),'id':'goal-existing'}
  result=proposal({'remaining':['Remaining journey'],'progress':'Prior slice verified','slice_value':'Finish the same journey'},current)
  for key in ('title','user_value','success_criteria','experience'):self.assertEqual(result[key],current[key])
  result['experience']['after']='Mutated return'
  self.assertNotEqual(result['experience'],current['experience'])

 def test_drift_reports_all_fields_and_native_repair_inherits_contract(self):
  from product_goals import ContractChanged,planning_context
  from planning_runtime import invoke
  from unittest.mock import Mock
  current={**self.experience_goal(),'id':'goal-existing'}
  drift={**current,'user_value':'Reworded value','experience':{**current['experience'],'after':'Slice-specific improvement'}}
  with self.assertRaises(ContractChanged) as failure:proposal(drift,current)
  self.assertIn('user_value, experience',str(failure.exception))
  correction=failure.exception.recovery_instruction
  self.assertIn(current['user_value'],correction)
  self.assertIn(current['experience']['after'],correction)
  self.assertIn('packet',correction)
  original=copy.deepcopy(drift)
  dynamic={'remaining':['Remaining journey'],'progress':'Prior slice verified','slice_value':'Finish current journey'}
  run=Mock(side_effect=[json.dumps(drift),json.dumps(dynamic)])
  result=invoke(run,self.root,self.root/'pm',planning_context(current),lambda:None,validate=lambda v:proposal(v,current))
  self.assertEqual(proposal(result,current)['experience'],current['experience'])
  self.assertIn('ACTIVE GOAL CORRECTION',run.call_args.args[2])
  self.assertNotIn('repair its representation only',run.call_args.args[2])
  self.assertEqual(drift,original)


class Research(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.repo=pathlib.Path(self.tmp.name);(self.repo/'spec.md').write_text('Current users cannot compare dated opportunities with reliable source attribution.')
 def tearDown(self):self.tmp.cleanup()
 def report(self):return {'status':'supported','question':'Where does comparison lose its source?','finding':'Missing association','counterevidence':'No user interviews; demand remains uncertain','recommendation':'Preserve existing source relationships','sources':[{'kind':'repository','path':'spec.md','quote':'Current users cannot compare dated opportunities with reliable source attribution.'}]}
 def test_source_claims_are_checked_and_invention_cannot_start_research_work(self):
  report=self.report();self.assertEqual(research.verify(report,self.repo)['status'],'supported')
  with self.assertRaisesRegex(ValueError,'public research'):research.verify(report,self.repo,True)
  report['sources'][0]['quote']='Invented evidence does not exist in this repository.'
  with self.assertRaisesRegex(ValueError,'not found'):research.verify(report,self.repo)
 def test_project_skill_is_loaded_and_method_impact_recorded(self):
  p=self.repo/'.agents/skills/competitor/SKILL.md';p.parent.mkdir(parents=True);p.write_text('Compare alternatives and actively seek disconfirming evidence.')
  report=self.report();report['skill_usage']=[{'path':str(p.relative_to(self.repo)),'impact':'Used disconfirming evidence to bound the finding'}]
  plan={'question':'Which comparison gap is evidenced?','stop_condition':'Current code and one counterexample checked','skills':[str(p.relative_to(self.repo))]};prompts=[]
  def model(work,scratch,prompt,**kw):prompts.append(prompt);return json.dumps(plan if len(prompts)==1 else report)
  value=research.perform(model,self.repo,self.repo/'run','PM research-only','No dispatch',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertIn(p.read_text(),prompts[1]);self.assertEqual(len(value['loaded_skills']),1);self.assertNotIn('content',value['loaded_skills'][0]);self.assertEqual(value['evidence_basis']['assessed_by'],'product-manager-agent')
  report['skill_usage']=[];prompts.clear()
  with self.assertRaisesRegex(ValueError,'impact'):research.perform(model,self.repo,self.repo/'retry','PM','Context',lambda:None,{'harness':'omp','provider':'codex'})
 def test_no_skills_is_explicit_not_invented_and_missing_files_fail(self):
  self.assertEqual(research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skills exist'},[]),[])
  with self.assertRaises(ValueError):research.load_skills(self.repo,{'skills':['.agents/skills/missing/SKILL.md']},[])
 def test_public_citations_retrieved_and_verified_independently(self):
  report=self.report();report['sources'].append({'kind':'public','url':'https://example.com/study','quote':'Comparison requires clear dates and trustworthy source links.'})
  with patch.object(research,'fetch',return_value=('https://example.com/study','<p>Comparison requires clear dates and trustworthy source links.</p>')) as fetch:
   value=research.verify(report,self.repo,True);fetch.assert_called_once();self.assertEqual(value['sources'][1]['verified_source'],'https://example.com/study')
