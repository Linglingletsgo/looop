import json,pathlib,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'bin'))
import lifecycle
from roles import resolve,fingerprints
class Refresh(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.repo=self.root/'data/execution-repos/lane';self.repo.mkdir(parents=True)
  subprocess.run(['git','init','-q',str(self.repo)],check=True)
  for k,v in [('user.name','Test'),('user.email','test@example.test')]:lifecycle.git(self.repo,'config',k,v)
  (self.repo/'app.py').write_text('value = 1\n');lifecycle.git(self.repo,'add','.');lifecycle.git(self.repo,'commit','-qm','old');self.old=lifecycle.git(self.repo,'rev-parse','HEAD').decode().strip()
  self.bare=self.root/'remote.git';subprocess.run(['git','clone','--bare','-q',str(self.repo),str(self.bare)],check=True)
  lifecycle.git(self.repo,'remote','add','origin',str(self.bare));self.branch=lifecycle.git(self.repo,'branch','--show-current').decode().strip()
  (self.repo/'app.py').write_text('value = 2\n');lifecycle.git(self.repo,'add','.');lifecycle.git(self.repo,'commit','-qm','new');self.new=lifecycle.git(self.repo,'rev-parse','HEAD').decode().strip();lifecycle.git(self.repo,'push','-q','origin',self.branch);lifecycle.git(self.repo,'checkout','--detach',self.old)
  (self.root/'bin').mkdir();shutil.copy2(pathlib.Path(lifecycle.__file__).parent/'project-profile.py',self.root/'bin/project-profile.py');(self.root/'profiles').mkdir()
  (self.root/'data/control.json').write_text(json.dumps({'projects':{'lane':{'repo':str(self.repo),'profile':'old'}}}))
  self.binding={'policy':{'repo':str(self.repo),'github_repo':'synthetic/repo','base_branch':self.branch,'checks':[['python3','-c','assert True']],'role_registry':fingerprints(resolve(self.repo))}}
 def tearDown(self):self.tmp.cleanup()
 def git(self,repo,*args):
  if args==('remote','get-url','origin'):return b'git@github.com:synthetic/repo.git\n'
  return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL)
 def test_verified_mainline_fastforwards_only_managed_checkout(self):
  with patch.object(lifecycle,'git',side_effect=self.git):result=lifecycle.refresh(self.root,'lane',self.binding,self.new)
  self.assertEqual(result['status'],'passed');self.assertEqual(self.git(self.repo,'rev-parse','HEAD').decode().strip(),self.new)
  profile=json.loads((self.root/'data/control.json').read_text())['projects']['lane']['profile'];self.assertEqual(json.loads((self.root/'profiles'/profile).read_text())['repository_revision'],self.new)
 def test_failed_postmerge_check_does_not_advance_baseline(self):
  self.binding['policy']['checks']=[['python3','-c','raise Exception("regression")']]
  with patch.object(lifecycle,'git',side_effect=self.git),self.assertRaisesRegex(ValueError,'verification failed'):lifecycle.refresh(self.root,'lane',self.binding,self.new)
  self.assertEqual(self.git(self.repo,'rev-parse','HEAD').decode().strip(),self.old)
 def test_original_workspace_cannot_be_refreshed(self):
  self.binding['policy']['repo']=str(self.root)
  with self.assertRaisesRegex(ValueError,'dedicated execution'):lifecycle.refresh(self.root,'lane',self.binding,self.new)
