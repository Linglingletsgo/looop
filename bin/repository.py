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

