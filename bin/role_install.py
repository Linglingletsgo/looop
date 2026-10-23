"""Install missing looop default roles as project-owned files; never overwrite project roles."""
import hashlib,pathlib
from runtime import CODE_ROOT
from roles import DEFAULTS,canonical,resolve
CORE=('product-manager','product','builder','reviewer')
DEFAULT_WORKFLOW=({'stage':'build','role':'builder'},{'stage':'review','role':'reviewer'})
HEADER='<!-- looop default role v1 ({name}); project-owned copy, edit freely -->\n\n'

def _text(name):
 file=CODE_ROOT/'default-roles'/(name+'.md')
 return file.read_text(encoding='utf-8') if file.is_file() else DEFAULTS[name]

def blocked(repo):
 """Reason the role directory cannot be written, or None."""
 for name in ('.agent','.agent/roles'):
  path=pathlib.Path(repo)/name
  if path.is_symlink():return 'Refusing symlinked '+name
  if path.exists() and not path.is_dir():return name+' is not a directory'
 return None

def _content(name):
 return HEADER.format(name=name)+_text(name)

def plan_default_roles(repo,adapter=None,include_all=False):
 """Defaults the project does not define: core duties, workflow roles, optionally every default."""
 if blocked(repo):return []
 registry=resolve(repo,adapter);defined=set(registry['project_roles'])
 workflow=registry['workflow'] or DEFAULT_WORKFLOW
 names=list(CORE)+[canonical(step['role']) for step in workflow if isinstance(step,dict) and isinstance(step.get('role'),str) and step['role'].strip()]
 if include_all:names+=list(DEFAULTS)
 plan=[]
 for name in dict.fromkeys(canonical(n) for n in names):
  if name in DEFAULTS and name not in defined:
   value=_content(name)
   plan.append({'role':name,'path':'.agent/roles/'+name+'.md','sha256':hashlib.sha256(value.encode()).hexdigest()})
 return plan

def install_default_roles(repo,include_all=False):
 """Write missing default role files, map them, and report conflicts instead of overwriting."""
 repo=pathlib.Path(repo).resolve(strict=True);result={'installed':[],'skipped':[],'mapped':[],'adapter_missing':False}
 reason=blocked(repo)
 if reason:raise ValueError(reason)
 adapter_file=repo/'.agent/project.json'
 if not adapter_file.is_file() and not adapter_file.is_symlink():
  result['adapter_missing']=True;return result
 from project_adapter import load
 from lifecycle import save
 adapter=load(repo);plan=plan_default_roles(repo,adapter,include_all)
 if plan:(repo/'.agent/roles').mkdir(parents=True,exist_ok=True)
 mapping=adapter.setdefault('roles',{});writes=[]
 # Decide every target before writing any, so a bad file cannot leave a partial install.
 for item in plan:
  name=item['role'];path=item['path'];target=repo/path;value=_content(name).encode('utf-8')
  if target.is_symlink():result['skipped'].append({'role':name,'path':path,'reason':'symlink'});continue
  if target.exists() and (not target.is_file() or target.read_bytes()!=value):
   result['skipped'].append({'role':name,'path':path,'reason':'existing_different'});continue
  writes.append((name,path,target,value))
 for name,path,target,value in writes:
  if not target.exists():target.write_bytes(value);result['installed'].append(name)
  if name not in mapping:mapping[name]=[path];result['mapped'].append(name)
 if result['mapped']:save(adapter_file,adapter)
 return result
