"""Real disposable Git/check pipeline; only harness and GitHub boundary are synthetic."""
import importlib.util,json,pathlib,subprocess,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import autonomy,delivery,lifecycle
import test_state_autonomy
from roles import resolve,fingerprints
from project_state import phase_of

class RecoveryCycle(unittest.TestCase):
 setUp=test_state_autonomy.SharedPlanning.setUp
 tearDown=test_state_autonomy.SharedPlanning.tearDown
 setup_tick=test_state_autonomy.SharedPlanning.setup_tick
 setup_shared=test_state_autonomy.SharedPlanning.setup_shared
 def test_planning_review_failure_resume_publication_merge_and_mainline(self):
  self.policy.update(github_repo='synthetic/recovery',base_branch=autonomy.git(self.repo,'branch','--show-current').decode().strip(),workflow=[{'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'}])
  self.setup_shared()
  bare=self.root/'remote.git';subprocess.run(['git','clone','--quiet','--bare',str(self.repo),str(bare)],check=True)
  autonomy.git(self.repo,'remote','add','origin',str(bare));(self.root/'profiles').mkdir()
  with patch.object(autonomy,'ROOT',self.root),patch.object(autonomy,'validate_profile',return_value={'repository_revision':self.sha}),patch.object(autonomy,'run',return_value=json.dumps(self.value)):
   autonomy.tick('test');autonomy.tick('test')
  delivery_id=sorted(path.stem for path in (self.root/'data/delivery-bindings').glob('*.json'))[0]
  binding=json.loads((self.root/'data/delivery-bindings'/(delivery_id+'.json')).read_text());packet=binding['packet'];policy=binding['policy']
  counts={'builder':0,'create':0,'merge':0};repaired=False;merged=False
  url='https://github.com/synthetic/recovery/pull/1';git=delivery.git;output=subprocess.check_output;run=subprocess.run
  def native(workspace,scratch,prompt,**kwargs):
   if kwargs['role']=='builder':counts['builder']+=1;(workspace/'test.py').write_text('assert 1 + 1 == 2\n')
   if scratch.name.startswith('reviewer-') and not repaired:return 'Review prose without a verdict'
   text='{"verdict":"approved","findings":[]}'
   scratch.mkdir(parents=True,exist_ok=True);(scratch/'result.md').write_text(text)
   return text
  def local_git(repo,*args):
   if args[:3]==('remote','set-url','origin'):args=(*args[:3],str(bare))
   return git(repo,*args)
  def github_output(argv,*a,**kw):
   if not str(argv[0]).endswith('/gh'):return output(argv,*a,**kw)
   if argv[1:3]==['pr','list']:return b'[]'
   if argv[1:3]==['pr','create']:counts['create']+=1;return url+'\n'
   if argv[1:3]==['pr','view']:
    state=json.loads((self.root/'data/deliveries'/delivery_id/'state.json').read_text());target=state['target_sha']
    value={'state':'MERGED' if merged else 'OPEN','url':url,'headRefOid':target,'baseRefOid':self.sha,'baseRefName':policy['base_branch'],'isDraft':False,'mergeable':'MERGEABLE','mergeStateStatus':'CLEAN','statusCheckRollup':[],'mergeCommit':{'oid':target},'mergedAt':'2026-10-18T00:00:00Z'}
    return json.dumps(value).encode()
   raise AssertionError(argv)
  def github_run(argv,*a,**kw):
   nonlocal merged
   if str(argv[0]).endswith('/gh'):
    self.assertEqual(argv[1:3],['pr','merge']);counts['merge']+=1
    target=json.loads((self.root/'data/deliveries'/delivery_id/'state.json').read_text())['target_sha']
    run(['git','--git-dir',str(bare),'update-ref','refs/heads/'+policy['base_branch'],target],check=True);merged=True
    return subprocess.CompletedProcess(argv,0,'')
   return run(argv,*a,**kw)
  with patch.object(delivery,'ROOT',self.root),patch.object(delivery,'run',side_effect=native),patch.object(delivery,'command',return_value=subprocess.CompletedProcess([],0,'Verifier Agent fixture pass')),patch.object(delivery,'git',side_effect=local_git),patch.object(subprocess,'check_output',side_effect=github_output),patch.object(subprocess,'run',side_effect=github_run):
   with self.assertRaises(ValueError):delivery.execute(packet,policy,delivery_id,emit=lambda *_:None)
   folder=self.root/'data/deliveries'/delivery_id;failed=json.loads((folder/'state.json').read_text());self.assertEqual(failed['failed_stage'],'review_standard');self.assertEqual(counts['create'],0)
   repaired=True
   with patch('process_owner.alive',return_value=False):state=delivery.execute(packet,policy,delivery_id,emit=lambda *_:None,resume_review=True)
   self.assertEqual(state['target_sha'],failed['target_sha']);self.assertEqual(state['builder_run'],failed['builder_run'])
   delivery.execute(packet,policy,delivery_id,emit=lambda *_:None)
   spec=importlib.util.spec_from_file_location('cycle_delivery_control',pathlib.Path(delivery.__file__).with_name('delivery-control.py'));control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
   (self.root/'data/merge-policies').mkdir();(self.root/'data/merge-policies/test.json').write_text(json.dumps({'mode':'review_approved','github_repo':'synthetic/recovery','review_role':'reviewer'}))
   def refresh_git(repo,*args):
    if args==('remote','get-url','origin'):return b'git@github.com:synthetic/recovery.git\n'
    return git(repo,*args)
   with patch('runtime.ROOT',self.root),patch.object(control,'ROOT',self.root),patch.object(lifecycle,'git',side_effect=refresh_git),patch.object(lifecycle,'command',return_value=subprocess.CompletedProcess([],0,'Verifier Agent mainline fixture pass')):control.sync_prs();control.sync_prs()
  final=json.loads((folder/'state.json').read_text());self.assertEqual(final['mainline_verified'],state['target_sha']);self.assertEqual(final['state'],'merged')
  self.store.transition('test',delivery_id,phase_of(final),{'mainline_verified':final['mainline_verified']},import_existing=True)
  self.assertEqual(self.store.read('test')['tasks'][delivery_id]['phase'],'completed');self.assertEqual(counts,{'builder':1,'create':1,'merge':1})
  self.assertEqual(autonomy.git(self.repo,'rev-parse','HEAD').decode().strip(),final['mainline_verified'])
