"""Resolve arbitrary project roles; defaults fill missing responsibilities only."""
import hashlib,json,pathlib,re,subprocess

from runtime import ROOT,CODE_ROOT
ROLE_DIRS=('docs/project/agent-roles','.agents/roles','.codex/agents')
ALIASES={'pm':'product-manager','product-owner':'product','developer':'builder','engineer':'builder','qa':'qa','ux-designer':'ux-designer'}
DEFAULTS={'product-manager': "Select and define the next valuable task within the project's authorized direction. In manual discussion mode, provide decision support instead.\n\nRead current project state, confirmed decisions, active/recent work, backlog and relevant source. Prioritize the controller-selected requirement; treat historical HANDOFF as context, not current authority. Avoid duplicate work.\n\nChoose one ready backlog item or, when authorized, discover an opportunity in the existing direction. Start from user value; distinguish evidence from assumptions and research only what could change the decision. Define a small, complete Packet with requirements, observable completion criteria, scope and supporting evidence. Use the required intent linkage.\n\nMake routine tradeoffs independently. Return no_work with a concrete reason when nothing valuable is ready or a material decision is unresolved; do not create busywork. Submit the proposal to the controller for validation and dispatch. Do not implement, dispatch directly or approve implementation. No extra Product/Acceptance stage is implied.\n\nFollow the caller's exact output schema; report conclusions and uncertainty concisely.\n", 'product': '将已授权需求整理成范围、可观察验收条件与实施计划。未决行为明确标记 BLOCKED；不批准自己的新需求，不修改实现。', 'builder': "Implement the approved Packet completely within its allowed paths.\n\nRead relevant code and project rules first. Use existing patterns and the smallest complete change. Handle meaningful edge cases and failure states; consider accessibility for UI work. Avoid unrelated refactors, speculative abstractions and unnecessary dependencies. Preserve existing behavior and assertions unless explicitly authorized to change them.\n\nInspect the diff and run relevant available checks using the configured environment. Fix failures caused by your change; report unrun checks honestly. Do not weaken checks to pass. Make routine engineering decisions independently; report material requirement conflicts or blockers.\n\nDo not expand scope, install dependencies, commit, push, merge or deploy without explicit controller authorization. Follow the caller's exact output schema; summarize changes, verification and unresolved issues.\n", 'reviewer': "Independently review the assigned diff at the exact target SHA against requirements and project rules. Read surrounding code and trace plausible failure paths; do not rely on Builder's claims or test counts alone.\n\nPrioritize correctness, regressions, security, state/concurrency, meaningful edge cases and missing verification. Report only demonstrated, relevant problems introduced or exposed by the change. Avoid speculative findings and stylistic preferences.\n\nGive actionable findings with severity, location, failure scenario and evidence. Minor suggestions alone do not block approval. Do not invent findings or modify code. A changed SHA requires fresh review.\n\nFollow the caller's exact schema. For delivery review use approved, changes_requested or blocked, not PASS; explain blockers and unverified behavior honestly.\n", 'acceptance': '依据验收条件独立核验可观察结果与证据。不把单元测试通过等同真实用户结果；证据不足则 blocked，不修改实现。', 'qa': '设计和执行获授权的可复现验证，覆盖边界和回归；不访问真实数据或外部服务，不把未运行的检查宣称通过。', 'ux-designer': "Provide bounded, implementation-ready guidance on user goals, flows, information architecture and interaction behavior.\n\nInspect the current experience and distinguish evidence from assumptions. Prefer familiar patterns and the simplest complete flow. Reduce unnecessary steps, decisions and ambiguity. Cover relevant empty/loading/error/success states, recovery paths, edge cases and accessibility. Explain meaningful tradeoffs and unresolved behavior decisions.\n\nFocus on usability rather than visual styling. Do not expand product scope or modify implementation. This is an optional advisory role; do not assume every project needs UI. Claim user research or browser verification only when performed. Follow the caller's output schema.\n", 'ui-designer': "Translate established product and UX requirements into concrete visual guidance for Builder.\n\nInspect and reuse existing components, tokens and design language. Specify clear hierarchy, layout, spacing, typography, relevant component states and responsive behavior. Include accessibility and visual feedback. Prefer consistent existing patterns over new primitives or decorative complexity.\n\nDo not redefine product goals, change user flows or implement production logic. Flag unresolved UX decisions. This is an optional advisory role; use available visual evidence and state limitations rather than inventing screenshots or verification. Follow the caller's output schema.\n"}
class RoleError(ValueError):pass

def safe_path(root,relative):
 p=pathlib.PurePosixPath(relative)
 if not relative or p.is_absolute() or '..' in p.parts:raise RoleError('Invalid role path')
 path=root
 for part in p.parts:
  path=path/part
  if path.is_symlink():raise RoleError('Symlink role path: '+relative)
 if not path.is_file():raise RoleError('Role file missing: '+relative)
 return path

def canonical(name):
 value=re.sub(r'\s+','-',name.strip().lower().replace('_','-'))
 return ALIASES.get(value,value)

def resolve(root,adapter=None):
 from project_adapter import load,safe_file
 root=pathlib.Path(root);adapter=load(root,adapter);roles={};conflicts=[]
 def add(name,text,source):
  name=canonical(name)
  if not re.fullmatch('[a-z][a-z0-9-]{0,63}',name):raise RoleError('Invalid role id: '+name)
  if name in roles:conflicts.append(name)
  else:roles[name]={'id':name,'source':source,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
 # Explicit mapping supports any project role names and filenames.
 manifest=root/'.paperclip/roles.json';mapping={};workflow=adapter.get('workflow') if adapter else None
 if adapter:
  for name,paths in adapter.get('roles',{}).items():
   text='\n\n'.join('PROJECT ROLE FILE '+n+'\n'+safe_file(root,n).read_text() for n in paths)
   add(name,text,'project:'+paths[0])
 if manifest.exists() or manifest.is_symlink():
  data=json.loads(safe_path(root,'.paperclip/roles.json').read_text())
  if data.get('version')!=1 or not isinstance(data.get('roles'),dict):raise RoleError('Invalid roles manifest')
  mapping=data['roles']
  if adapter:
   if any(canonical(n) not in roles or len(adapter.get('roles',{}).get(n,[]))!=1 or adapter['roles'][n][0]!=v for n,v in mapping.items()):raise RoleError('Conflicting legacy and neutral role mappings')
   if data.get('workflow') is not None and data['workflow']!=workflow:raise RoleError('Conflicting legacy and neutral workflows')
  else:workflow=data.get('workflow')
  for name,value in mapping.items():
   if not isinstance(value,str):raise RoleError('Role mapping must name a repository file')
   if canonical(name) not in roles:add(name,safe_path(root,value).read_text(),'project:'+value)
 # Known directories are conventions, not a fixed list of role names.
 for directory in (() if adapter and adapter.get('role_discovery')=='explicit' else ROLE_DIRS):
  folder=root/directory
  if folder.is_symlink():raise RoleError('Symlink role directory')
  if folder.is_dir():
   for p in sorted(folder.iterdir()):
    if p.suffix not in ('.md','.toml'):continue
    name=canonical(p.stem)
    if name in {canonical(k) for k in mapping}|{canonical(k) for k in (adapter or {}).get('roles',{})}:continue
    add(name,safe_path(root,str(p.relative_to(root))).read_text(),'project:'+str(p.relative_to(root)))
 # Inline role contracts stay project-owned; copy the containing rules, not an invented summary.
 for filename in (() if adapter and adapter.get('role_discovery')=='explicit' else ('AGENTS.md','AGENT.md','Agent.md','agents.md')):
  path=root/filename
  if not path.exists() and not path.is_symlink():continue
  text=safe_path(root,filename).read_text()
  for heading in re.findall(r'^#{1,6}\s+(?:[0-9.]+\s+)?(.+?)\s*$',text,re.M):
   h=re.sub(r'\s+(?:Agent|Role(?: Contract)?)$','',heading,flags=re.I).strip()
   h={'Product / Product Owner':'product','Product Manager':'product-manager','UX Designer':'ux-designer'}.get(h,h)
   name=canonical(h)
   if name in roles:continue
   if name in DEFAULTS or re.search(r'\b(?:Agent|Role(?: Contract)?)$',heading,re.I):
    if re.fullmatch('[a-z][a-z0-9-]{0,63}',name):add(name,text,'project:'+filename+'#'+heading)
 if conflicts:raise RoleError('Ambiguous project roles; provide explicit mapping: '+','.join(sorted(set(conflicts))))
 project_roles=sorted(roles)
 for name,text in DEFAULTS.items():
  if name not in roles:
   default=CODE_ROOT/'default-roles'/(name+'.md')
   if default.exists():text=safe_path(CODE_ROOT,'default-roles/'+name+'.md').read_text()
   add(name,text,'default:v1/'+name)
 return {'version':1,'roles':roles,'project_roles':project_roles,'workflow':workflow}

def contract(registry,name):
 name=canonical(name)
 if name not in registry['roles']:raise RoleError('Undefined role: '+name+'; add a project definition or explicit mapping')
 r=registry['roles'][name]
 return 'ROLE '+name+' ('+r['source']+')\n'+r['text']

def fingerprints(registry):
 return {k:{'source':v['source'],'sha256':v['sha256']} for k,v in registry['roles'].items()}

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('repo');a=p.parse_args()
 result=resolve(a.repo)
 print(json.dumps({'project_roles':result['project_roles'],'available_roles':fingerprints(result),'workflow':result['workflow']},ensure_ascii=False,indent=2))
