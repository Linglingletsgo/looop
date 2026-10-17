"""Recover only explicit HTTP 429 cooldowns; authentication and billing stay paused."""
import datetime,email.utils,json,pathlib,time,uuid
from lifecycle import save

def pause(root,provider,status,retry_after,now=None):
 now=time.time() if now is None else now
 value={'status':'paused','http_status':status,'retry_after':retry_after,'remaining':'unknown','paused_at':now}
 if status==429 and retry_after:
  try:
   seconds=float(retry_after)
  except (TypeError,ValueError):
   try:seconds=email.utils.parsedate_to_datetime(retry_after).timestamp()-now
   except (TypeError,ValueError,OverflowError):seconds=0
  if 0<seconds<=86400:value['resume_at']=now+max(60,seconds)
 save(pathlib.Path(root)/'data'/('quota-'+provider+'.json'),value)
 return value

def paused(root,provider,now=None):
 now=time.time() if now is None else now;path=pathlib.Path(root)/'data'/('quota-'+provider+'.json')
 if not path.exists():return None
 value=json.loads(path.read_text())
 if value.get('http_status')==429 and value.get('resume_at',float('inf'))<=now:
  # Atomic rename lets concurrent callers safely observe the same recovered pause.
  archive=pathlib.Path(root)/'data/provider-recovery';archive.mkdir(parents=True,exist_ok=True,mode=0o700)
  try:path.rename(archive/(provider+'-'+uuid.uuid4().hex+'.json'))
  except FileNotFoundError:pass
  return None
 return value
