import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import product_research as research
import autonomy,loop_control
from project_state import Store
import test_autonomy as fixtures

class DefaultMethods(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.repo=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_project_methods_win_and_defaults_require_specific_gap(self):
  p=self.repo/'.agents/skills/pm/SKILL.md';p.parent.mkdir(parents=True);p.write_text('Project mandatory discovery method')
  available=research.catalog(self.repo)
  selected=research.load_skills(self.repo,{'skills':['.agents/skills/pm/SKILL.md']},available)
  self.assertEqual([s['origin'] for s in selected],['project'])
  with self.assertRaisesRegex(ValueError,'explicit gap'):research.load_skills(self.repo,{'skills':['looop:competitive-research']},available)
  selected=research.load_skills(self.repo,{'skills':['looop:competitive-research'],'fallback_reason':'Project method lacks public competitor comparison'},available)
  self.assertEqual([s['path'] for s in selected],['looop:investigation','looop:competitive-research'])
 def test_no_project_methods_loads_reviewed_protocol_even_when_model_skips(self):
  result=research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skill exists'},research.catalog(self.repo))
  self.assertEqual(result[0]['path'],'looop:investigation');self.assertEqual(result[0]['license'],'CC-BY-NC-SA-4.0')
  self.assertIn('cfcb697',result[0]['upstream']['commit'])
 def test_modified_default_bytes_are_rejected(self):
  folder=self.repo/'defaults';folder.mkdir();source=research.DEFAULT_ROOT
  import shutil
  shutil.copytree(source,folder,dirs_exist_ok=True)
  (folder/'investigation/SKILL.md').write_text('Unreviewed replacement')
  with patch.object(research,'DEFAULT_ROOT',folder):
   with self.assertRaisesRegex(ValueError,'reviewed manifest'):research.default_catalog()
 def test_originals_and_licenses_match_pinned_manifest(self):
  import hashlib
  for item in json.loads((research.DEFAULT_ROOT/'manifest.json').read_text())['skills']:
   owner=item['upstream']['repo'].split('/')[0];original=research.DEFAULT_ROOT/'upstream'/owner/item['upstream']['path']
   self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),item['upstream']['sha256'])
   self.assertTrue((research.DEFAULT_ROOT/'upstream'/owner/'LICENSE').is_file())
 def test_network_gap_does_not_become_feature_or_controller_failure(self):
  report={'status':'supported','question':'Does the public source support the need?','finding':'Provisional finding','counterevidence':'User demand not established','recommendation':'Wait if unverifiable','sources':[{'kind':'public','url':'https://example.com/research','quote':'This is an exact quote that needs independent checking.'}]}
  with patch.object(research,'fetch',side_effect=TimeoutError('unavailable')):
   value=research.verify(report,self.repo,True)
  self.assertEqual(value['status'],'insufficient_evidence');self.assertNotIn('unavailable',json.dumps(value))
 def test_default_protocol_and_usage_actually_enter_model_call(self):
  (self.repo/'spec.md').write_text('The existing export omits the date needed for comparison.')
  responses=[{'question':'Is the existing date export incomplete?','stop_condition':'Read current export and specification','skills':['looop:backlog-prioritization']}, {'status':'supported','question':'Is the existing date export incomplete?','finding':'Specification shows a gap','counterevidence':'No live user study','recommendation':'Continue existing authorized backlog','skill_usage':[{'path':p,'impact':'Used method to validate the selected backlog problem'} for p in ['looop:investigation','looop:backlog-prioritization']],'sources':[{'kind':'repository','path':'spec.md','quote':'The existing export omits the date needed for comparison.'}]}]
  prompts=[]
  def run(*args,**kwargs):prompts.append(args[2]);return json.dumps(responses.pop(0))
  value=research.perform(run,self.repo,self.repo/'run','PM','Backlog only',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(prompts[0].count('Catalog: '),1);self.assertEqual(len(value['loaded_skills']),2);self.assertIn('Source count is not a proof threshold',prompts[1]);self.assertNotIn('Content not loaded',prompts[1]);self.assertNotIn('content',value['loaded_skills'][0])

 def test_wrong_phase_packet_is_corrected_before_any_research(self):
  calls=[]
  responses=[{'status':'proposal','packet':{'title':'Wrong phase'}},{'question':'Is export evidence sufficient?','stop_condition':'Read specification and stop','skills':['looop:investigation']},{'status':'insufficient_evidence','question':'Is export evidence sufficient?','finding':'No specification exists','counterevidence':'No factual basis','recommendation':'Wait for evidence','next_step':{'kind':'human_decision','detail':'Provide the missing product specification'},'skill_usage':[{'path':'looop:investigation','impact':'Identified missing evidence instead of guessing'}]}]
  def run(*args,**kwargs):calls.append(args);return json.dumps(responses.pop(0))
  value=research.perform(run,self.repo,self.repo/'run','PM proposes tasks','Current state',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(value['status'],'insufficient_evidence');self.assertEqual(len(calls),3)
  self.assertIn('OUTPUT CORRECTION',calls[1][2]);self.assertIn('research-plan-retry-1',str(calls[1][1]));self.assertEqual(calls[2][1].name,'research')
  self.assertNotIn('packet',value)

 def test_citation_path_format_is_corrected_but_quote_evidence_is_not_retried(self):
  quote='Confirmed export must contain the record date.'
  (self.repo/'spec.md').write_text(quote)
  plan={'question':'Does export preserve dates?','stop_condition':'Check spec','skills':['looop:investigation']}
  report={'status':'supported','question':plan['question'],'finding':'A date is required','counterevidence':'No user study','recommendation':'Continue scoped requirement','skill_usage':[{'path':'looop:investigation','impact':'Compared implementation to specification'}],'sources':[{'kind':'repository','path':'spec.md:1','quote':quote}]}
  repaired=copy.deepcopy(report);repaired['sources'][0]['path']='spec.md'
  calls=[];responses=[plan,report,repaired]
  def run(*a,**k):calls.append(a);return json.dumps(responses.pop(0))
  value=research.perform(run,self.repo,self.repo/'run','PM','state',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(value['sources'][0]['path'],'spec.md');self.assertEqual(len(calls),3);self.assertIn('without line-number suffixes',calls[2][2])
  repaired['sources'][0]['quote']='An invented quotation that is absent from the actual specification.'
  with patch.object(research,'invoke',side_effect=[plan,repaired]) as model:
   with self.assertRaisesRegex(ValueError,'quotation not found'):research.perform(run,self.repo,self.repo/'bad','PM','state',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(model.call_count,2)

class GoalPlanning(unittest.TestCase):
 setUp=fixtures.Autonomy.setUp
 tearDown=fixtures.Autonomy.tearDown
 setup_tick=fixtures.Autonomy.setup_tick
 def configure(self):
  self.mandate['scope_approval']='pm';self.mandate['enabled']=False;self.setup_tick()
  (self.root/'data/project-state').mkdir();(self.root/'data/project-state/enabled').touch()
  store=Store(self.root);store.ensure('test')
  with patch('bridge.validate_profile',return_value={}):loop_control.switch(self.root,'test','once',0,'start')
  return store
 def board(self):
  counts={'pm':0,'delivery':0}
  class Board:
   def api(self,method,path,data=None):
    if path=='/auth/get-session':return {'user':{'id':'owner'}}
    if method=='POST':
     kind='delivery' if data['status']=='backlog' else 'pm';counts[kind]+=1
     return {'id':kind+'-'+str(counts[kind]),'identifier':'T-'+str(sum(counts.values()))}
  return Board
 def test_real_tick_continues_goal_across_two_slices_then_completes_without_research_repeat(self):
  store=self.configure();Board=self.board();responses=[json.dumps(self.value)]
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',Board),patch.object(autonomy,'validate_profile',side_effect=lambda _: {'repository_revision':autonomy.git(self.repo,'rev-parse','HEAD').decode().strip()}),patch.object(autonomy,'run',side_effect=lambda *a,**k:responses.pop(0)) as model:
   autonomy.tick('test');goal=store.read('test')['product_goal']
   for index in (1,2):
    task='delivery-'+str(index)
    store.transition('test',task,'completed',import_existing=True)
    path=self.root/'data/deliveries'/task/'state.json';path.parent.mkdir(parents=True);path.write_text('{"state":"merged","mainline_verified":true}')
    if index==1:
     (self.repo/'test.py').write_text('slice = 1\n');autonomy.git(self.repo,'add','test.py');autonomy.git(self.repo,'commit','-qm','slice one')
    self.assertEqual(loop_control.settle(self.root,'test')['mode'],'once')
    if index==1:
     next_value=copy.deepcopy(self.value);next_value['packet']['requirements']=['Verify next source relationship'];next_value['product_goal']['progress']='First slice delivered';responses.append(json.dumps(next_value))
    else:responses.append(json.dumps({'action':'goal_complete','goal_id':goal['id'],'reason':'Every specified source criterion checked','completion_evidence':[{'criterion':goal['success_criteria'][0],'path':'spec.py','quote':'Existing behavior returns stable known values.'}]*2}))
    autonomy.tick('test')
   self.assertEqual(model.call_count,3);self.research_mock.assert_called_once()
  self.assertEqual(store.read('test')['product_goal']['status'],'completed');self.assertEqual(store.read('test')['product_goal']['completed_slices'],2)
  self.assertEqual(loop_control.settle(self.root,'test')['mode'],'paused')
 def test_insufficient_research_never_dispatches_or_calls_proposal(self):
  store=self.configure();self.research_mock.return_value={'status':'insufficient_evidence','recommendation':'Need actual evidence'}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   with self.assertRaises(autonomy.ResearchIncomplete):autonomy.tick('test')
   model.assert_not_called()
  self.assertFalse(store.read('test')['tasks']);self.assertEqual(store.read('test')['selection']['phase'],'blocked');self.assertEqual(next(json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json'))['failure']['category'],'research_incomplete');self.assertEqual(store.read('test')['research']['status'],'insufficient_evidence');self.assertEqual(loop_control.settle(self.root,'test')['mode'],'paused')
 def test_decision_changed_during_research_prevents_dispatch(self):
  store=self.configure()
  def research_result(*a,**kw):
   store.submit('test',{'type':'decision','title':'New scope','body':'Pause the proposed direction','human_confirmed':True},store.read('test')['revision'],'new-decision','test')
   return {'status':'supported','sources':[]}
  self.research_mock.side_effect=research_result
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'Board',self.board()),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   with self.assertRaisesRegex(Exception,'decisions changed'):autonomy.tick('test')
   model.assert_not_called()
  self.assertFalse(store.read('test')['tasks'])
