"""Synthetic research probes run on disposable source copies, never delivery workspaces."""
import hashlib,json,pathlib,shutil,subprocess
from lifecycle import save
from repository import source_fingerprint
from sandbox import workspace_environment,execution_environment


def validate(probe):
 if not isinstance(probe,dict) or probe.get('runtime') not in ('python','node','node_ts'):raise ValueError('Experiment runtime must be python, node or node_ts')
 for key,limit in (('script',32000),('purpose',2000)):
  if not isinstance(probe.get(key),str) or not probe[key].strip() or len(probe[key])>limit:raise ValueError('Experiment requires bounded '+key)


def execute(repo,folder,probe,dependencies,fresh):
 validate(probe);fresh();folder=pathlib.Path(folder);workspace=folder/'workspace'
 folder.mkdir(parents=True,exist_ok=True)
 shutil.copytree(repo,workspace,ignore=shutil.ignore_patterns('.git','node_modules','.env*','.venv','__pycache__','.next','coverage','secrets','var'),symlinks=True)
 # Snapshots are controller-created files; reject unexpected links before attaching dependencies.
 if any(p.is_symlink() for p in workspace.rglob('*')):raise ValueError('Research snapshot must not contain symlinks')
 runtime=probe['runtime'];name={'python':'.looop-research-probe.py','node':'.looop-research-probe.mjs','node_ts':'.looop-research-probe.ts'}[runtime]
 script=workspace/name
 if script.exists():raise ValueError('Research probe path already exists')
 script.write_text(probe['script']);before=source_fingerprint(workspace)
 result_path=folder.resolve()/'observations.json'
 argv={'python':['python3',name],'node':['node',name],'node_ts':['node','--import','tsx',name]}[runtime]
 # Probes receive runtime discovery, not provider, database, mail or scheduler credentials.
 base=execution_environment();env={k:base[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in base}
 env.update(HOME=str(folder.resolve()),PYTHONDONTWRITEBYTECODE='1',LOOOP_EXPERIMENT_RESULT=str(result_path))
 fresh()
 with workspace_environment(workspace,dependencies):
  process=subprocess.Popen(argv,cwd=workspace,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  tail=bytearray()
  try:
   while block:=process.stdout.read(65536):
    tail.extend(block)
    if len(tail)>12000:del tail[:-12000]
   process.wait()
  finally:
   if process.poll() is None:process.terminate();process.wait()
   process.stdout.close()
  output=tail.decode(errors='ignore');(folder/'output.log').write_text(output)

 fresh()
 if source_fingerprint(workspace)!=before:raise ValueError('Research experiment modified source; evidence rejected')
 observations=None
 if result_path.exists() or result_path.is_symlink():
  if result_path.is_symlink() or not result_path.is_file() or result_path.stat().st_size>12000:raise ValueError('Experiment observations must be a regular JSON file of at most 12000 bytes')
  observations=json.loads(result_path.read_text())
 receipt={'observations':observations,'purpose':probe['purpose'],'argv':argv,'exit_code':process.returncode,'output':output,'evidence_path':str(folder),'script_sha256':hashlib.sha256(probe['script'].encode()).hexdigest(),'source_fingerprint':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),'scope':'synthetic isolated probe; not delivery validation or approval'}
 save(folder/'result.json',receipt)
 return receipt


def restored(repo,checkpoint):
 """Re-use only controller receipts whose recorded script and source still match."""
 result=[];current=source_fingerprint(repo)
 checkpoint=pathlib.Path(checkpoint)
 paths=list(sorted(checkpoint.glob('experiment-*/result.json')))
 report=checkpoint/'research.json'
 if report.is_file():
  for item in json.loads(report.read_text()).get('experiments',[])[:4]:
   candidate=pathlib.Path(item.get('evidence_path',''))/'result.json'
   if candidate.resolve().is_relative_to(checkpoint.parent.resolve()) and candidate.is_file() and candidate not in paths:paths.append(candidate)
 for path in paths[-4:]:
  value=json.loads(path.read_text());workspace=path.parent/'workspace'
  if not workspace.is_dir():continue
  before=source_fingerprint(workspace);argv=value.get('argv',[])
  if not argv:continue
  name=argv[-1]
  if pathlib.PurePath(name).name!=name or not name.startswith('.looop-research-probe.'):continue
  script=workspace/name
  if script.is_symlink() or not script.is_file():continue
  if hashlib.sha256(script.read_bytes()).hexdigest()!=value.get('script_sha256'):continue
  if hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()!=value.get('source_fingerprint'):continue
  before.pop(name,None)
  if current!=before:continue
  result.append(value)
 return result
