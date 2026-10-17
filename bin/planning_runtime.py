"""Read-only model call recovery; never wraps binding, publication or business verdicts."""
import json,time
from lifecycle import failure,save

def invoke(run,workspace,scratch,prompt,fresh,**kwargs):
 for attempt in range(3):
  fresh()
  target=scratch if attempt==0 else scratch.with_name(scratch.name+'-retry-'+str(attempt))
  try:
   text=run(workspace,target,prompt,**kwargs)
   value=json.loads(text)
   if attempt:save(scratch.parent/(scratch.name+'-recovery.json'),{'attempts':attempt+1,'state':'recovered','automatic_retry':False})
   return value
  except Exception as exc:
   retry=isinstance(exc,json.JSONDecodeError) or failure(exc)['category']=='connection'
   save(scratch.parent/(scratch.name+'-recovery.json'),{'attempts':attempt+1,'state':'retry_wait' if retry and attempt<2 else 'needs_attention','category':'invalid_json' if isinstance(exc,json.JSONDecodeError) else failure(exc)['category'],'automatic_retry':retry and attempt<2})
   if not retry or attempt==2:raise
   time.sleep(5 if attempt==0 else 15)
