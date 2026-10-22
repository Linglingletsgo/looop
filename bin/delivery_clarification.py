"""Product-owned clarifications preserve the immutable Packet and write scope."""
import copy,hashlib,json,pathlib,uuid
from gates import GateError

def packet_hash(packet):
 return hashlib.sha256(json.dumps(packet,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def apply(packet,value):
 if value.get('verdict')!='approved':raise GateError('Product clarification blocked')
 result=copy.deepcopy(packet);seen=set()
 changes=value.get('changes')
 if not isinstance(changes,list) or not changes or len(changes)>20:raise GateError('Explicit bounded criteria changes required')
 for item in changes:
  section=item.get('section');index=item.get('index')
  if section not in ('requirements','acceptance') or type(index) is not int or not 0<=index<len(packet[section]):raise GateError('Clarification cannot change scope or baseline')
  if (section,index) in seen or item.get('before')!=packet[section][index]:raise GateError('Clarification source clause changed')
  if not all(isinstance(item.get(k),str) and 0<len(item[k])<=10000 for k in ('after','reason')):raise GateError('Clarification text and reason required')
  seen.add((section,index));result[section][index]=item['after']
 return result

def effective_packet(folder,packet):
 source=folder
 if packet.get('clarification_receipt'):
  source=pathlib.Path(packet['clarification_receipt'])
  if source.is_symlink() or source.resolve().parent!=(folder.parent.parent/'delivery-attempts').resolve() or not source.name.startswith(folder.name+'-'):raise GateError('Invalid archived Product clarification')
  original=json.loads((source/'packet.json').read_text())
  strip=lambda p:{k:v for k,v in p.items() if k not in ('execution_notes','clarification_receipt')}
  if strip(original)!=strip(packet):raise GateError('Archived Product clarification contract changed')
 else:original=packet
 path=source/'product-clarification.json'
 if not path.exists():
  if source!=folder:raise GateError('Missing archived Product clarification')
  return packet
 doc=json.loads(path.read_text())
 if doc['packet_hash']!=packet_hash(original):raise GateError('Product clarification belongs to another Packet')
 run=source/doc['run_id']
 if run.parent!=source or not run.name.startswith('product-clarification-'):raise GateError('Invalid Product clarification receipt')
 from handoff import read
 schema=json.loads((run/'handoff.schema.json').read_text())
 identity={'version':1,'run_id':run.name,'nonce':schema['properties']['nonce']['enum'][0]}
 value=read(run,schema['properties']['result'],identity)
 if value!=doc['result']:raise GateError('Product clarification differs from original handoff')
 return apply(packet,value)

def clarify(root,issue):
 from lifecycle import save
 from repository import git,snapshot
 from process_owner import alive
 from roles import resolve,contract
 from execution_settings import read,route
 from planning_runtime import invoke
 from sandbox import run
 import fcntl
 folder=root/'data/deliveries'/issue
 binding=json.loads((root/'data/delivery-bindings'/(issue+'.json')).read_text())
 packet=binding['packet'];policy=binding['policy'];old=json.loads((folder/'state.json').read_text())
 common=git(policy['repo'],'rev-parse','--path-format=absolute','--git-common-dir').decode().strip()
 lock=root/'data/locks'/hashlib.sha256(common.encode()).hexdigest()
 with lock.open('w') as handle:
  fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
  def fresh():
   from project_state import task_guard
   task_guard(root,issue)
   current=json.loads((folder/'state.json').read_text())
   if current!=old or old.get('state')!='blocked' or old.get('pr_url') or alive(old.get('owner')) is not False:raise GateError('Clarification requires a stopped unpublished task')
   if git(folder/'candidate','rev-parse','HEAD').decode().strip()!=old['target_sha'] or git(folder/'candidate','status','--porcelain').strip():raise GateError('Clarification candidate changed')
   if git(policy['repo'],'rev-parse','HEAD').decode().strip()!=packet['baseline_sha']:raise GateError('Clarification baseline moved')
  fresh()
  if (folder/'product-clarification.json').exists():return effective_packet(folder,packet)
  rid='product-clarification-'+uuid.uuid4().hex[:12]
  workspace=snapshot(folder/'candidate',old['target_sha'],folder/'clarification-workspace')
  schema={'type':'object','properties':{'verdict':{'type':'string','enum':['approved','blocked']},'changes':{'type':'array','items':{'type':'object','properties':{'section':{'type':'string','enum':['requirements','acceptance']},'index':{'type':'integer'},'before':{'type':'string'},'after':{'type':'string'},'reason':{'type':'string'}},'required':['section','index','before','after','reason'],'additionalProperties':False}},'summary':{'type':'string'}},'required':['verdict','changes','summary'],'additionalProperties':False}
  prompt=contract(resolve(workspace,policy.get('project_adapter')),'product-manager')+'\nClarify contradictory criteria in this existing task, not a new product proposal. Read the Packet, Builder blocker and independent review findings. Preserve the original outcome, all truthful unknowns, isolation, evidence binding, and all regression checks. No source edits, installation, commands that change production data, commits, publication, or scope expansion. Resolve wording only; do not declare the implementation correct or replace independent review. Preserve existing product input precision and behavior. If fixture amounts or steps contradict that contract, clarify the fixture and all dependent expectations instead of widening product behavior. Read the preserved Builder workspace and actual observations; keep isolation and cleanup requirements. If this requires changing intended product behavior or expanding allowed paths, return blocked with no changes. Changes must quote each original clause exactly using zero-based indices. Write the supplied handoff.json; chat is not parsed.\nPacket: '+json.dumps(packet,ensure_ascii=False)+'\nBuilder blocker: '+str(old.get('error',''))[:16000]+'\nPreserved Builder workspace: '+str(folder/old.get('pending_builder',{}).get('workspace','candidate'))+'\nIndependent findings: '+json.dumps(old.get('reviews'),ensure_ascii=False)+'\nEvidence root: '+str(folder/'artifacts')
  value=invoke(run,workspace,folder/rid,prompt,fresh,validate=lambda v:apply(packet,v) if v.get('verdict')=='approved' else None,role='readonly',dependencies=pathlib.Path(policy['dependencies']) if policy.get('dependencies') else None,git_metadata=folder/'candidate/.git',timeout=None,execution_route=route(read(root),'planning'),handoff_schema=schema)
  fresh()
  recovery=folder/(rid+'-recovery.json')
  if recovery.exists():rid+='-retry-'+str(json.loads(recovery.read_text())['attempts']-1)
  if value['verdict']!='approved':raise GateError('Product clarification blocked: '+value['summary'])
  save(folder/rid/'validated-result.json',value)
  save(folder/'product-clarification.json',{'packet_hash':packet_hash(packet),'run_id':rid,'target_sha':old['target_sha'],'result':value})
  return effective_packet(folder,packet)
