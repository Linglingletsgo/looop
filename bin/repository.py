"""Credential-filtered Git snapshots shared by all scheduling backends."""
import io,pathlib,subprocess,tarfile

def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args])
def snapshot(repo,sha,dest):
 dest=pathlib.Path(dest);dest.mkdir(parents=True,exist_ok=True)
 raw=git(repo,'archive','--format=tar',sha)
 with tarfile.open(fileobj=io.BytesIO(raw)) as t:
  for member in t:
   p=pathlib.PurePosixPath(member.name)
   if p.is_absolute() or '..' in p.parts:raise ValueError('Invalid archive path')
   if not member.isfile():continue
   if any(x in {'.git','node_modules','.venv','venv','.next','dist','build','__pycache__','secrets'} for x in p.parts):continue
   if any(x.startswith('.env') for x in p.parts) or p.suffix.lower() in {'.pem','.key','.p12','.sqlite','.db'}:continue
   target=dest/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(t.extractfile(member).read());target.chmod(0o755 if member.mode & 0o111 else 0o644)
 return dest

RUNTIME_DIRS={'.git','node_modules','.venv','__pycache__','.pytest_cache','.next','dist','build','coverage'}
def runtime_output(relative):
 """Caches and the project-local session area (.agent/local, gitignored) are not source."""
 parts=pathlib.PurePath(relative).parts
 return bool(set(parts)&RUNTIME_DIRS) or parts[:2]==('.agent','local')
def source_fingerprint(root):
 """Runtime outputs are not source; existing source changes still invalidate review."""
 import hashlib
 result={}
 for p in pathlib.Path(root).rglob('*'):
  relative=p.relative_to(root)
  if runtime_output(relative):continue
  if p.suffix=='.tsbuildinfo' and not p.is_symlink():continue
  if p.is_symlink():result[str(relative)]='link:'+str(p.readlink())
  elif p.is_file():result[str(relative)]=hashlib.sha256(p.read_bytes()).hexdigest()
 return result
