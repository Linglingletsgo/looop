"""Import measured tokens as unpriced usage. Remaining subscription quota stays unknown."""
import datetime,json,sqlite3
from board import ROOT

def record(b,folder,company,agent,issue,project):
 c=sqlite3.connect(ROOT/'data/metrics.sqlite');c.execute('CREATE TABLE IF NOT EXISTS imported (path TEXT PRIMARY KEY)')
 for p in folder.glob('*/usage.json'):
  if c.execute('SELECT 1 FROM imported WHERE path=?',(str(p),)).fetchone():continue
  d=json.loads(p.read_text())
  b.api('POST',f'/companies/{company}/cost-events',{'agentId':agent,'issueId':issue,'projectId':project,'provider':d['provider'],'model':d['model'],'billingType':'subscription_included' if d['provider']=='codex' else 'credits','costStatus':'unpriced','inputTokens':d['input_tokens'],'cachedInputTokens':d['cached_input_tokens'],'outputTokens':d['output_tokens'],'costCents':0,'occurredAt':datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z')})
  c.execute('INSERT INTO imported VALUES (?)',(str(p),));c.commit()
