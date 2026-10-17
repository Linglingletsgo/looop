import json
from board import ROOT,Board
b=Board();companies=b.api('GET','/companies');company=next((c for c in companies if c['name']=='Goal to People'),None)
if not company:company=b.api('POST','/companies',{'name':'Goal to People','description':'Explicit isolated regression-test pilot. No production services or external actions.'})
projects=b.api('GET',f'/companies/{company["id"]}/projects');project=next((p for p in projects if p['name']=='GTP isolated pilot'),None)
if not project:project=b.api('POST',f'/companies/{company["id"]}/projects',{'name':'GTP isolated pilot','status':'planned','workspace':{'name':'isolated-pilot','cwd':str(ROOT/'data/gtp-pilot/repo'),'isPrimary':True}})
agents=b.api('GET',f'/companies/{company["id"]}/agents');agent=next((a for a in agents if a['name']=='GTP bounded delivery'),None)
if not agent:agent=b.api('POST',f'/companies/{company["id"]}/agents',{'name':'GTP bounded delivery','role':'general','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/gtp_worker.py')],'cwd':str(ROOT),'timeoutSec':3600},'runtimeConfig':{'heartbeat':{'enabled':False,'intervalSec':0,'wakeOnDemand':True,'maxConcurrentRuns':1}},'permissions':{'canCreateAgents':False,'canCreateSkills':False}})
c={'company':company['id'],'project':project['id'],'agent':agent['id']};(ROOT/'data/gtp-control.json').write_text(json.dumps(c,indent=2))
print('GTP isolated project configured. No task dispatched.')
