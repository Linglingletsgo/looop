"""Current, attributable backlog selection; independent of the scheduling backend."""
import hashlib,pathlib,re
from project_adapter import safe_file

MODES=('backlog_only','backlog_and_research')

def backlog_sources(mandate,adapter=None):
 adapter=adapter or {}
 declared=adapter.get('backlog_paths',mandate.get('backlog_paths'))
 if declared is not None:
  if not isinstance(declared,list) or not all(isinstance(n,str) for n in declared):raise ValueError('backlog_paths must be a list of files')
  return list(dict.fromkeys(declared))
 return [n for n in dict.fromkeys(mandate.get('evidence_paths',[])+adapter.get('rules',{}).get('common',[])+adapter.get('rules',{}).get('reference',[])) if 'backlog' in pathlib.PurePosixPath(n).name.lower()]

def backlog_items(repo,sources,completed=()):
 items=[]
 for name in sources:
  path=safe_file(repo,name)
  for line in path.read_text().splitlines():
   # Only explicitly pending entries are executable; prose and completed checkboxes are context.
   if not re.match(r'^\s*[-*+]\s+\[ \]\s+\S',line):continue
   quote=line.strip();key=hashlib.sha256((name+'\n'+quote).encode()).hexdigest()
   if key not in completed:items.append({'path':name,'quote':quote,'key':key})
 return items

def check_source(value,mode,selected,items):
 if value.get('action')!='task':return None
 if selected:return None
 source=value.get('backlog_item')
 if source:
  found=next((i for i in items if isinstance(source,dict) and source.get('path')==i['path'] and source.get('quote')==i['quote']),None)
  if not found:raise ValueError('Backlog source is not a current pending item')
  return found['key']
 if mode=='backlog_only':raise ValueError('Backlog-only task must cite a current pending backlog item')
 return None

def instructions(mode,items):
 return ('Selection mode: '+mode+'. '+('Select only a ready item from the pending backlog below or the controller-selected confirmed requirement. No new requirement discovery. If nothing is ready, return no_work.' if mode=='backlog_only' else 'Prioritize ready backlog and confirmed requirements. You may also discover a valuable new requirement within existing product direction; avoid duplicate or already implemented work.')+'\nFor backlog work, return backlog_item {path,quote} copied exactly from one pending entry below; for research use null. Verify actual code and dependencies: a checkbox alone does not prove the work is still needed.\nPending backlog: '+__import__('json').dumps(items,ensure_ascii=False))
