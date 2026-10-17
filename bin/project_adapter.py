"""Project-owned execution contract. No Paperclip client or scheduler dependencies."""
import hashlib,json,pathlib
NATIVE=('AGENTS.md','AGENT.md','Agent.md','agents.md')

def safe_file(root,name):
 p=pathlib.PurePosixPath(name)
 if not name or p.is_absolute() or any(x in ('.','..') for x in p.parts):raise ValueError('Invalid project instruction path: '+str(name))
 path=pathlib.Path(root)
 for part in p.parts:
  path=path/part
  if path.is_symlink():raise ValueError('Symlink instruction path: '+name)
 if not path.is_file():raise ValueError('Missing project instruction: '+name)
 return path

def validate(config):
 if not isinstance(config,dict) or config.get('version')!=1:raise ValueError('Unsupported project adapter version')
 if config.get('role_discovery','auto') not in ('auto','explicit'):raise ValueError('Invalid role discovery mode')
 if not isinstance(config.get('roles',{}),dict):raise ValueError('roles must map names to files')
 for name,paths in config.get('roles',{}).items():
  if not isinstance(paths,list) or not paths or not all(isinstance(p,str) for p in paths):raise ValueError('Role files must be nonempty string lists: '+name)
 if not isinstance(config.get('rules',{}),dict):raise ValueError('rules must be an object')
 for key in ('common','reference'):
  if not isinstance(config.get('rules',{}).get(key,[]),list) or not all(isinstance(n,str) for n in config.get('rules',{}).get(key,[])):raise ValueError('Invalid rule file list')
 if not isinstance(config.get('rules',{}).get('by_role',{}),dict):raise ValueError('by_role must map role names to file lists')
 if not isinstance(config.get('workflow_mapping',''),str):raise ValueError('workflow_mapping must be text')
 for role,paths in config.get('rules',{}).get('by_role',{}).items():
  if not isinstance(role,str) or not isinstance(paths,list) or not all(isinstance(n,str) for n in paths):raise ValueError('Invalid per-role rule list')
 return config

def load(root,explicit=None):
 path=pathlib.Path(root)/'.agent/project.json'
 found=json.loads(safe_file(root,'.agent/project.json').read_text()) if path.exists() or path.is_symlink() else None
 if explicit is not None:
  validate(explicit)
  if found is not None and validate(found)!=explicit:raise ValueError('Project adapter differs from bound controller configuration')
  return explicit
 return validate(found) if found is not None else None

def files(config):
 rules=config.get('rules',{});return set(rules.get('common',[])+rules.get('reference',[])+[p for v in rules.get('by_role',{}).values() for p in v]+[p for v in config.get('roles',{}).values() for p in v])

def evidence(root,config):
 result={n:hashlib.sha256(safe_file(root,n).read_bytes()).hexdigest() for n in files(config)|set(native_files(root,config.get('allowed_paths',[])))}
 if (pathlib.Path(root)/'.agent/project.json').is_file():result['.agent/project.json']=hashlib.sha256(safe_file(root,'.agent/project.json').read_bytes()).hexdigest()
 return result

def native_files(root,targets):
 root=pathlib.Path(root);names=[]
 # Native instructions remain mandatory even when role discovery is explicit.
 directories={pathlib.PurePosixPath('.')}
 for target in targets:
  p=pathlib.PurePosixPath(target)
  if p.is_absolute() or '..' in p.parts:raise ValueError('Invalid target')
  directories.update(p.parents)
 for directory in sorted(directories,key=lambda p:(len(p.parts),str(p))):
  for name in NATIVE:
   relative=str(directory/name);p=root/relative
   if p.is_file() or p.is_symlink():safe_file(root,relative);names.append(relative)
 return names

def context(root,config,role,targets=()):
 names=native_files(root,targets)
 if config:
  names+=config.get('rules',{}).get('common',[])
  from roles import canonical
  names+=config.get('rules',{}).get('by_role',{}).get(canonical(role),[])
 result='\n'.join('MANDATORY PROJECT RULE '+n+'\n'+safe_file(root,n).read_text() for n in dict.fromkeys(names))
 if config and config.get('workflow_mapping'):
  result+='\nUSER-APPROVED WORKFLOW RESPONSIBILITY MAPPING:\n'+config['workflow_mapping']
 return result

def check_policy(policy):
 config=policy.get('project_adapter')
 if not config:return
 validate(config)
 if config.get('execution_enabled') is False:raise ValueError('Project adapter is context-only; execution is disabled')
 for key in ('workflow','checks','allowed_paths'):
  if key in config and config[key]!=policy.get(key):raise ValueError('Project adapter / execution policy mismatch: '+key)

def summary(root,config,targets=()):
 from roles import resolve,fingerprints
 registry=resolve(root,config)
 return {'version':1,'adapter':config,'roles':fingerprints(registry),'project_roles':registry['project_roles'],'workflow':registry['workflow'],'mandatory_rules':native_files(root,targets),'instruction_evidence':evidence(root,config) if config else {},'notes':['Native AGENTS instructions are mandatory; explicit role selection does not disable harness auto-loading.','Reference files are discoverable context, not injected into every role prompt.']}
