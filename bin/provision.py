import json,pathlib
from board import Board,ROOT
b=Board(); dest=ROOT/'data/control.json'
state=json.loads(dest.read_text()) if dest.exists() else {'projects':{},'agents':{}}
def save():dest.write_text(json.dumps(state,indent=2));dest.chmod(0o600)
companies=b.api('GET','/companies')
company=next((c for c in companies if c['name']=='Work On Show'),None)
if not company:company=b.api('POST','/companies',{'name':'Work On Show','description':'WOS mainline automation. DS1 is a human-operated UI worktree excluded from scheduling. Manual merge only.'})
state['company']=company['id'];save()
projects=b.api('GET',f'/companies/{company["id"]}/projects')
for lane,name,repo,profile in [('mainline','WOS Product mainline','/home/agentdev/projects/emerging-fashion-creatives','wos-mainline-draft.json')]:
 p=next((p for p in projects if p['name']==name),None)
 if not p:p=b.api('POST',f'/companies/{company["id"]}/projects',{'name':name,'description':f'Independent {lane} context. Original handoff and approvals preserved.','status':'planned','workspace':{'name':lane,'cwd':repo,'isPrimary':True}})
 state['projects'][lane]={'id':p['id'],'repo':repo,'profile':profile};save()
 roles=['product','product-manager','builder','reviewer','acceptance']
 for role in roles:
  key=lane+':'+role
  if key in state['agents']:continue
  a=b.api('POST',f'/companies/{company["id"]}/agents',{'name':f'{lane} / {role}','role':'pm' if role in ['product','product-manager'] else 'engineer' if role=='builder' else 'qa','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/bridge.py'),'heartbeat',lane,role],'cwd':str(ROOT),'timeoutSec':1200},'runtimeConfig':{'heartbeat':{'enabled':False,'intervalSec':0,'wakeOnDemand':True}},'permissions':{'canCreateAgents':False,'canCreateSkills':False},'capabilities':'Bounded project role; bridge enforces workspace and authority. No merge/deploy.'})
  state['agents'][key]=a['id'];save()
  if role not in ['product']:b.api('POST',f'/agents/{a["id"]}/pause',{})
print('Provisioned Work On Show; lanes',list(state['projects']),'agents',len(state['agents']))
