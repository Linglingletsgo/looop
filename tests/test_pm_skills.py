import copy,json,pathlib,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import product_research as research
import autonomy,loop_control
from project_state import Store
from jobs import Jobs
from tracker import LocalTracker
import test_autonomy as fixtures
from looop_support import setUpModule  # noqa: F401

class DefaultMethods(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.repo=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def opt_in(self,value=True):
  settings=self.repo/'data';settings.mkdir(exist_ok=True)
  (settings/'local-settings.json').write_text(json.dumps({'pm_skills':{'noncommercial':value}}))
  return patch.object(research,'ROOT',self.repo)
 def test_noncommercial_pack_is_disabled_without_local_opt_in(self):
  with patch.object(research,'ROOT',self.repo):
   available=research.catalog(self.repo)
   result=research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skill exists'},available)
  self.assertNotIn('looop:investigation',[s['path'] for s in available]);self.assertNotIn('looop:competitive-research',[s['path'] for s in available])
  self.assertEqual(result[0]['path'],'looop:research-core');self.assertEqual(result[0]['license'],'MIT');self.assertIsNone(result[0]['upstream'])
 def test_opt_in_enables_noncommercial_pack_and_original_base_method(self):
  with self.opt_in():
   available=research.catalog(self.repo)
   selected=research.load_skills(self.repo,{'skills':['looop:competitive-research'],'fallback_reason':'Project method lacks public competitor comparison'},available)
   result=research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skill exists'},available)
  self.assertEqual([s['path'] for s in selected],['looop:investigation','looop:competitive-research'])
  self.assertEqual(result[0]['path'],'looop:investigation');self.assertEqual(result[0]['license'],'CC-BY-NC-SA-4.0')
  self.assertIn('cfcb697',result[0]['upstream']['commit'])
 def test_explicit_base_method_survives_after_opt_in(self):
  with self.opt_in():
   available=research.catalog(self.repo)
   kept=research.load_skills(self.repo,{'skills':['looop:research-core']},available)
   inherited=research.load_skills(self.repo,{'skills':['looop:investigation']},available)
   configured=research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skill exists'},available)
   inserted=research.load_skills(self.repo,{'skills':['looop:backlog-prioritization'],'fallback_reason':'No project prioritization method'},available)
  self.assertEqual([s['path'] for s in kept],['looop:research-core']);self.assertEqual(kept[0]['license'],'MIT')
  self.assertEqual([s['path'] for s in inherited],['looop:investigation'])
  self.assertEqual([s['path'] for s in configured],['looop:investigation'])
  self.assertEqual([s['path'] for s in inserted],['looop:investigation','looop:backlog-prioritization'])
 def test_explicit_research_core_without_opt_in_is_not_swapped(self):
  with patch.object(research,'ROOT',self.repo):
   available=research.catalog(self.repo)
   kept=research.load_skills(self.repo,{'skills':['looop:research-core']},available)
   configured=research.load_skills(self.repo,{'skills':[],'skill_reason':'No project skill exists'},available)
  self.assertEqual([s['path'] for s in kept],['looop:research-core']);self.assertEqual([s['path'] for s in configured],['looop:research-core'])
 def test_two_base_methods_are_never_loaded_together(self):
  with self.opt_in(),self.assertRaisesRegex(ValueError,'at most one base method'):
   research.load_skills(self.repo,{'skills':['looop:research-core','looop:investigation']},research.catalog(self.repo))
 def test_missing_or_false_setting_keeps_pack_disabled(self):
  with patch.object(research,'ROOT',self.repo):self.assertFalse(research.noncommercial_enabled())
  with self.opt_in(False):self.assertFalse(research.noncommercial_enabled())
  with self.opt_in(True):self.assertTrue(research.noncommercial_enabled())
  (self.repo/'data/local-settings.json').write_text('{not json')
  with patch.object(research,'ROOT',self.repo):self.assertFalse(research.noncommercial_enabled())
 def test_project_methods_win_and_defaults_require_specific_gap(self):
  p=self.repo/'.agents/skills/pm/SKILL.md';p.parent.mkdir(parents=True);p.write_text('Project mandatory discovery method')
  with self.opt_in():
   available=research.catalog(self.repo)
   selected=research.load_skills(self.repo,{'skills':['.agents/skills/pm/SKILL.md']},available)
   self.assertEqual([s['origin'] for s in selected],['project'])
   with self.assertRaisesRegex(ValueError,'explicit gap'):research.load_skills(self.repo,{'skills':['looop:competitive-research']},available)
   selected=research.load_skills(self.repo,{'skills':['looop:competitive-research'],'fallback_reason':'Project method lacks public competitor comparison'},available)
  self.assertEqual([s['path'] for s in selected],['looop:investigation','looop:competitive-research'])
 def test_disabled_pack_never_loads_reviewed_noncommercial_protocol(self):
  with patch.object(research,'ROOT',self.repo):
   available=research.catalog(self.repo)
   result=research.load_skills(self.repo,{'skills':['looop:backlog-prioritization'],'fallback_reason':'No project prioritization method'},available)
   with self.assertRaisesRegex(ValueError,'existing catalog'):research.load_skills(self.repo,{'skills':['looop:investigation']},available)
  self.assertEqual([s['path'] for s in result],['looop:research-core','looop:backlog-prioritization'])
 def test_modified_default_bytes_are_rejected(self):
  folder=self.repo/'defaults';folder.mkdir();source=research.DEFAULT_ROOT
  import shutil
  shutil.copytree(source,folder,dirs_exist_ok=True)
  (folder/'research-core/SKILL.md').write_text('Unreviewed replacement')
  with patch.object(research,'DEFAULT_ROOT',folder):
   with self.assertRaisesRegex(ValueError,'reviewed manifest'):research.default_catalog()
 def test_originals_licenses_and_hashes_match_pinned_manifest(self):
  import hashlib
  manifest=json.loads((research.DEFAULT_ROOT/'manifest.json').read_text())
  self.assertEqual(len(manifest['skills']),7)
  for item in manifest['skills']:
   digest=hashlib.sha256((research.DEFAULT_ROOT/item['path']).read_bytes()).hexdigest()
   self.assertEqual(digest,item['sha256'],item['id'])
   if item['upstream'] is None:
    self.assertEqual(item['license'],'MIT');self.assertEqual(item['pack'],'default')
    continue
   owner=item['upstream']['repo'].split('/')[0];original=research.DEFAULT_ROOT/'upstream'/owner/item['upstream']['path']
   self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),item['upstream']['sha256'])
  self.assertTrue((research.DEFAULT_ROOT/'upstream'/owner/'LICENSE').is_file())
  self.assertEqual({i['id'] for i in manifest['skills'] if i['pack']=='noncommercial'},{'looop:investigation','looop:competitive-research'})
 def test_mit_skills_declare_configured_base_placeholder(self):
  manifest=json.loads((research.DEFAULT_ROOT/'manifest.json').read_text())
  for item in manifest['skills']:
   if item['pack']!='default' or item['id']=='looop:research-core':continue
   self.assertEqual(item['dependencies'],['looop:base'],item['id'])
  self.assertEqual(next(i for i in manifest['skills'] if i['id']=='looop:competitive-research')['dependencies'],['looop:investigation'])
 def test_network_gap_does_not_become_feature_or_controller_failure(self):
  report={'status':'supported','question':'Does the public source support the need?','finding':'Provisional finding','counterevidence':'User demand not established','recommendation':'Wait if unverifiable','sources':[{'kind':'public','url':'https://example.com/research','quote':'This is an exact quote that needs independent checking.'}]}
  with patch.object(research,'fetch',side_effect=TimeoutError('unavailable')):
   value=research.verify(report,self.repo,True)
  self.assertEqual(value['status'],'insufficient_evidence');self.assertNotIn('unavailable',json.dumps(value))
 def test_default_protocol_and_usage_actually_enter_model_call(self):
  (self.repo/'spec.md').write_text('The existing export omits the date needed for comparison.')
  responses=[{'question':'Is the existing date export incomplete?','stop_condition':'Read current export and specification','skills':['looop:backlog-prioritization']}, {'status':'supported','question':'Is the existing date export incomplete?','finding':'Specification shows a gap','counterevidence':'No live user study','recommendation':'Continue existing authorized backlog','skill_usage':[{'path':p,'impact':'Used method to validate the selected backlog problem'} for p in ['looop:research-core','looop:backlog-prioritization']],'sources':[{'kind':'repository','path':'spec.md','quote':'The existing export omits the date needed for comparison.'}]}]
  prompts=[]
  def run(*args,**kwargs):prompts.append(args[2]);return json.dumps(responses.pop(0))
  with patch.object(research,'ROOT',self.repo):
   value=research.perform(run,self.repo,self.repo/'run','PM','Backlog only',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(prompts[0].count('Catalog: '),1);self.assertEqual(len(value['loaded_skills']),2);self.assertIn('Every factual claim carries its own attributable source',prompts[1]);self.assertNotIn('Content not loaded',prompts[1]);self.assertNotIn('content',value['loaded_skills'][0]);self.assertEqual(value['loaded_skills'][0]['path'],'looop:research-core');self.assertEqual(value['loaded_skills'][0]['license'],'MIT')

 def test_wrong_phase_packet_is_corrected_before_any_research(self):
  calls=[]
  responses=[{'status':'proposal','packet':{'title':'Wrong phase'}},{'question':'Is export evidence sufficient?','stop_condition':'Read specification and stop','skills':['looop:research-core']},{'status':'insufficient_evidence','question':'Is export evidence sufficient?','finding':'No specification exists','counterevidence':'No factual basis','recommendation':'Wait for evidence','next_step':{'kind':'human_decision','detail':'Provide the missing product specification'},'skill_usage':[{'path':'looop:research-core','impact':'Identified missing evidence instead of guessing'}]}]
  def run(*args,**kwargs):calls.append(args);return json.dumps(responses.pop(0))
  value=research.perform(run,self.repo,self.repo/'run','PM proposes tasks','Current state',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(value['status'],'insufficient_evidence');self.assertEqual(len(calls),3)
  self.assertIn('OUTPUT CORRECTION',calls[1][2]);self.assertIn('research-plan-retry-1',str(calls[1][1]));self.assertEqual(calls[2][1].name,'research')
  self.assertNotIn('packet',value)

 def test_citation_path_format_and_evidence_correction_remain_separate(self):
  quote='Confirmed export must contain the record date.'
  (self.repo/'spec.md').write_text(quote)
  plan={'question':'Does export preserve dates?','stop_condition':'Check spec','skills':['looop:research-core']}
  report={'status':'supported','question':plan['question'],'finding':'A date is required','counterevidence':'No user study','recommendation':'Continue scoped requirement','skill_usage':[{'path':'looop:research-core','impact':'Compared implementation to specification'}],'sources':[{'kind':'repository','path':'spec.md:1','quote':quote}]}
  repaired=copy.deepcopy(report);repaired['sources'][0]['path']='spec.md'
  calls=[];responses=[plan,report,repaired]
  def run(*a,**k):calls.append(a);return json.dumps(responses.pop(0))
  value=research.perform(run,self.repo,self.repo/'run','PM','state',lambda:None,{'harness':'codex','provider':'codex'})
  self.assertEqual(value['sources'][0]['path'],'spec.md');self.assertEqual(len(calls),3);self.assertIn('without line-number suffixes',calls[2][2])
  repaired['sources'][0]['quote']='An invented quotation that is absent from the actual specification.'
  with patch.object(research,'invoke',side_effect=[plan,repaired]) as model:
   value=research.perform(run,self.repo,self.repo/'bad','PM','state',lambda:None,{'harness':'codex','provider':'codex'})
   self.assertEqual(value['evidence_basis']['assessed_by'],'product-manager-agent')
  self.assertEqual(model.call_count,2)

class GoalPlanning(unittest.TestCase):
 setUp=fixtures.Autonomy.setUp
 tearDown=fixtures.Autonomy.tearDown
 setup_tick=fixtures.Autonomy.setup_tick
 def configure(self):
  self.mandate['scope_approval']='pm';self.mandate['enabled']=False;self.setup_tick()
  (self.root/'data/project-state').mkdir();(self.root/'data/project-state/enabled').touch()
  store=Store(self.root);store.ensure('test')
  with patch('project_adapter.validate_profile',return_value={}):loop_control.switch(self.root,'test','once',0,'start')
  self.jobs=Jobs(self.root);return store
 def test_real_tick_continues_goal_across_two_slices_then_completes_without_research_repeat(self):
  store=self.configure();responses=[json.dumps(self.value)]
  tracker=LocalTracker(self.jobs,self.root)
  def complete(index):
   pending=[path.stem for path in (self.root/'data/delivery-bindings').glob('*.json') if not (self.root/'data/deliveries'/path.stem/'state.json').exists()]
   self.assertEqual(len(pending),1,index);task=pending[0]
   head=autonomy.git(self.repo,'rev-parse','HEAD').decode().strip()
   path=self.root/'data/deliveries'/task/'state.json';path.parent.mkdir(parents=True,exist_ok=True)
   path.write_text(json.dumps({'state':'merged','mainline_verified':head,'target_sha':head,'round':1}))
   (path.parent/'checks-1.json').write_text(json.dumps([{'argv':['python3','test.py'],'exit_code':0}]))
   store.transition('test',task,'completed',import_existing=True)
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'open_tracker',lambda *a,**k:tracker),patch.object(autonomy,'validate_profile',side_effect=lambda _: {'repository_revision':autonomy.git(self.repo,'rev-parse','HEAD').decode().strip()}),patch.object(autonomy,'run',side_effect=lambda *a,**k:responses.pop(0)) as model:
   autonomy.tick('test');goal=store.read('test')['product_goal'];complete(1)
   (self.repo/'test.py').write_text('slice = 1\n');autonomy.git(self.repo,'add','test.py');autonomy.git(self.repo,'commit','-qm','slice one')
   self.assertEqual(loop_control.settle(self.root,'test')['mode'],'once')
   next_value=copy.deepcopy(self.value);next_value['packet']['requirements']=['Verify next source relationship'];next_value['product_goal']['progress']='First slice delivered';responses.append(json.dumps(next_value))
   autonomy.tick('test');complete(2)
   responses.append(json.dumps({'action':'goal_complete','goal_id':goal['id'],'reason':'Every specified source criterion checked','completion_evidence':[{'criterion':goal['success_criteria'][0],'path':'spec.py','quote':'Existing behavior returns stable known values.'}]*2}))
   autonomy.tick('test')
   self.assertEqual(model.call_count,3)
   self.assertEqual(self.research_mock.call_count,1)
  self.assertEqual(store.read('test')['product_goal']['status'],'completed');self.assertEqual(store.read('test')['product_goal']['completed_slices'],2)
  self.assertEqual(loop_control.settle(self.root,'test')['mode'],'paused')
 def test_insufficient_research_never_dispatches_or_calls_proposal(self):
  store=self.configure();self.research_mock.return_value={'status':'insufficient_evidence','recommendation':'Need actual evidence','next_step':{'kind':'human_decision','detail':'Choose a concrete product policy'}}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   with self.assertRaises(autonomy.ResearchIncomplete):autonomy.tick('test')
   model.assert_not_called()
  self.assertFalse(store.read('test')['tasks']);self.assertEqual(store.read('test')['selection']['phase'],'blocked');self.assertEqual(next(json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json'))['failure']['category'],'research_incomplete');self.assertEqual(store.read('test')['research']['status'],'insufficient_evidence');self.assertEqual(loop_control.settle(self.root,'test')['mode'],'paused')
 def check_automatic_research_gap(self,kind):
  store=self.configure();doc=store.read('test')
  with patch('project_adapter.validate_profile',return_value={'repository_revision':self.sha}):loop_control.switch(self.root,'test','continuous',doc['revision'],'continuous-'+kind)
  self.research_mock.return_value={'status':'insufficient_evidence','recommendation':'Public sample does not support this candidate','next_step':{'kind':kind,'detail':'Check public samples or choose another opportunity'}}
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   autonomy.tick('test');model.assert_not_called()
  self.assertFalse(store.read('test')['tasks']);self.assertEqual(store.read('test')['selection']['phase'],'no_work')
  from planning_intervention import unresolved
  self.assertFalse(unresolved(self.root,'test'));self.assertEqual(loop_control.view(self.root,'test')['mode'],'continuous')
  receipts=[json.loads(p.read_text()) for p in (self.root/'data/autonomy/test').glob('*/state.json')]
  self.assertTrue(all(v['state']=='no_work' for v in receipts));self.assertIsNotNone(autonomy.recheck_at(receipts[-1],'continuous'))
 def test_evidence_gap_waits_without_human_retry(self):self.check_automatic_research_gap('investigate')
 def test_source_wait_rechecks_without_human_retry(self):self.check_automatic_research_gap('wait_source')
 def test_decision_changed_during_research_prevents_dispatch(self):
  store=self.configure()
  def research_result(*a,**kw):
   store.submit('test',{'type':'decision','title':'New scope','body':'Pause the proposed direction','human_confirmed':True},store.read('test')['revision'],'new-decision','test')
   return {'status':'supported','sources':[]}
  self.research_mock.side_effect=research_result
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run') as model:
   with self.assertRaisesRegex(Exception,'decisions changed'):autonomy.tick('test')
   model.assert_not_called()
  self.assertFalse(store.read('test')['tasks'])
