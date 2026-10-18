"""Pure deterministic SHA/role/review gates, independent of model statements."""
import re,json
class GateError(ValueError):pass

def validate_packet(packet):
 for k in ['bundle','baseline_sha','agent_system_sha','requirements','acceptance','allowed_paths','checks','max_rounds','risk']:
  if not packet.get(k):raise GateError('missing '+k)
 for k in ['baseline_sha','agent_system_sha']:
  if not re.fullmatch('[0-9a-f]{40}',packet[k]):raise GateError('full SHA required: '+k)
 if packet['risk'] not in ['low','high']:raise GateError('risk required')
 if packet['max_rounds']>6 or packet['max_rounds']<1:raise GateError('round cap')
 for p in packet['allowed_paths']:
  if p.startswith('/') or '..' in p.split('/') or p in ['AGENTS.md','AGENT.md'] or p.startswith(('.git','docs/project/agent-roles/')):raise GateError('invalid write scope')

def review_valid(evidence,target,mode,builder_id):
 return bool(evidence and evidence.get('target_sha')==target and evidence.get('mode')==mode and evidence.get('verdict')=='approved' and evidence.get('run_id') and evidence.get('run_id')!=builder_id)

def require_reviews(state):
 required=['standard','adversarial'] if state['risk']=='high' else ['standard']
 for mode in required:
  if not review_valid(state.get('reviews',{}).get(mode),state['target_sha'],mode,state['builder_run']):raise GateError('missing fresh review '+mode)
 if len({state['reviews'][m]['run_id'] for m in required})!=len(required):raise GateError('review contexts reused')

def update_target(state,target):
 if state.get('target_sha')!=target:state.update(target_sha=target,reviews={},acceptance=None)

def require_pr(state,policy=None):
 require_reviews(state)
 if policy is not None and not any(s["stage"]=="acceptance" for s in policy.get("workflow",[{"stage":"acceptance"}])):return
 a=state.get('acceptance')
 if not a or a.get('target_sha')!=state['target_sha'] or a.get('verdict')!='approved':raise GateError('acceptance missing/stale')
 if a.get('run_id') in [state['builder_run'],*[v['run_id'] for v in state['reviews'].values()]]:raise GateError('acceptance context reused')

def verdict(text):
 from output_protocol import object_value
 d=object_value(text)
 if not isinstance(d,dict) or d.get('verdict') not in ['approved','changes_requested','blocked'] or ('findings' in d and not isinstance(d['findings'],list)):raise GateError('invalid review output: require verdict and findings array')
 return d

