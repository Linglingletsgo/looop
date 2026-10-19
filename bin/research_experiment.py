"""Research experiment dispatch to a native Harness Agent, not a script runner."""
import hashlib,json,pathlib
from lifecycle import save
from repository import source_fingerprint


def validate(probe):
 if not isinstance(probe,dict) or probe.get('runtime') not in ('python','node','node_ts'):raise ValueError('Experiment runtime must be python, node or node_ts')
 for key,limit in (('script',32000),('purpose',2000)):
  if not isinstance(probe.get(key),str) or not probe[key].strip() or len(probe[key])>limit:raise ValueError('Experiment requires bounded '+key)


def execute(repo,folder,probe,dependencies,fresh):
 validate(probe);fresh();folder=pathlib.Path(folder)
 from sandbox import run
 from planning_runtime import invoke
 from execution_settings import read,route
 from runtime import ROOT
 from roles import resolve,contract
 registry=resolve(repo);role='qa' if 'qa' in registry['project_roles'] or 'reviewer' not in registry['project_roles'] else 'reviewer'
 prompt=contract(registry,role)+'\nInvestigate this synthetic reproduction using the native Harness and linked project dependencies. You own execution and interpretation. Use fixed model stubs and in-memory receivers; no production database, network, external models, mail or credentials. Do not modify project source or install dependencies. Write temporary scripts and bounded execution artifacts ONLY in the supplied handoff directory. Adapt the proposed script if necessary, preserving the question and controls; report what you actually ran and why. Requested experiment: '+json.dumps(probe,ensure_ascii=False)+'\nWrite handoff.json result {"exit_code": integer, "output": "bounded actual observation", "observations": {...}, "evidence_path": "actual artifact path"}. Never claim execution from source inspection. A nonzero exit or missing prerequisite must remain visible.'
 def validate_result(v):
  if not isinstance(v,dict) or type(v.get('exit_code')) is not int:raise ValueError('Experiment requires integer exit_code')
  for key in ('output','evidence_path'):
   if not isinstance(v.get(key),str) or not v[key].strip() or len(v[key])>12000:raise ValueError('Experiment requires bounded '+key)
  if len(json.dumps(v.get('observations'),ensure_ascii=False).encode())>12000:raise ValueError('Experiment observations exceed 12000 bytes')
 value=invoke(run,repo,folder/'agent',prompt,fresh,validate=validate_result,role='readonly',timeout=None,dependencies=dependencies,execution_route=route(read(ROOT),'review','codex'))
 fresh()
 receipt={'executor':'native-agent','role':role,'purpose':probe['purpose'],'argv':['native-harness',role],'exit_code':value['exit_code'],'output':value['output'],'observations':value.get('observations'),'evidence_path':str(folder.resolve()),'agent_evidence_path':value['evidence_path'],'script_sha256':hashlib.sha256(probe['script'].encode()).hexdigest(),'source_fingerprint':hashlib.sha256(json.dumps(source_fingerprint(repo),sort_keys=True).encode()).hexdigest(),'scope':'Agent research conclusion; not merge approval'}
 save(folder/'result.json',receipt);return receipt


def restored(repo,checkpoint):
 """Return prior same-source Agent receipts as context; Agents assess their relevance."""
 checkpoint=pathlib.Path(checkpoint);paths=list(sorted(checkpoint.glob('experiment-*/result.json')))
 report=checkpoint/'research.json'
 if report.is_file():
  for item in json.loads(report.read_text()).get('experiments',[])[:4]:
   p=pathlib.Path(item.get('evidence_path',''))/'result.json'
   if p.resolve().is_relative_to(checkpoint.parent.resolve()) and p.is_file() and p not in paths:paths.append(p)
 result=[];current=hashlib.sha256(json.dumps(source_fingerprint(repo),sort_keys=True).encode()).hexdigest()
 for p in paths[-4:]:
  value=json.loads(p.read_text())
  if value.get('executor')=='native-agent' and value.get('source_fingerprint')==current:result.append(value)
 return result
