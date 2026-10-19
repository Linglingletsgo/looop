"""Atomic bounded-document persistence, independent of execution modules."""
import json,pathlib,re,uuid

def save(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 tmp=path.with_name("."+path.name+"-"+uuid.uuid4().hex+".tmp");tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.chmod(0o600);tmp.replace(path)

def validate_receipt(value):
 """Validate a bounded stage claim; validation never grants approval or completion."""
 fields={'version','task_id','role','stage','baseline_sha','target_sha','verdict','summary','findings','checks','artifacts','unverified','cleanup'}
 if not isinstance(value,dict) or set(value)!=fields or type(value['version']) is not int or value['version']!=1:raise ValueError('Invalid stage receipt fields/version')
 for key in ('task_id','role'):
  if not isinstance(value[key],str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',value[key]):raise ValueError('Invalid receipt '+key)
 if value['stage'] not in ('plan','advisory','build','review','acceptance','integration','cleanup'):raise ValueError('Invalid receipt stage')
 if value['verdict'] not in ('approved','changes_requested','blocked'):raise ValueError('Invalid receipt verdict')
 if value['stage'] in ('plan','advisory','build') and value['verdict']=='changes_requested':raise ValueError('Invalid stage verdict')
 for key in ('baseline_sha','target_sha'):
  if not isinstance(value[key],str) or not re.fullmatch('[0-9a-f]{40}',value[key]):raise ValueError('Full receipt SHA required: '+key)
 if not isinstance(value['summary'],str) or not 1<=len(value['summary'])<=2000:raise ValueError('Concise receipt summary required')
 for key in ('findings','checks','artifacts','unverified','cleanup'):
  items=value[key]
  if not isinstance(items,list) or len(items)>30 or any(not isinstance(v,str) or not v.strip() or len(v)>(24000 if key=='findings' else 4000) for v in items):raise ValueError('Bounded string list required: '+key)
 if len(json.dumps(value,ensure_ascii=False).encode())>128000:raise ValueError('Stage receipt too large')
 return value
