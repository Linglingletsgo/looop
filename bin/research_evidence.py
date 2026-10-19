"""One controller-owned evidence rule shared by research and proposal dispatch."""
KINDS=('new_requirement','existing_defect','backlog_validation')

class EvidenceGap(ValueError):pass


def basis(report,kind,public_required,experiments,defect=None):
 if kind not in KINDS:raise ValueError('Unknown research kind')
 public=sum(s.get('kind')=='public' and bool(s.get('verified_source')) for s in report.get('sources',[]))
 runtime=[e['evidence_path'] for e in experiments if e.get('exit_code')==0 and e.get('script_sha256') and e.get('source_fingerprint')]
 local=any(s.get('kind')=='repository' and s.get('verified_source') for s in report.get('sources',[]))
 if public_required and not public and kind!='existing_defect':raise EvidenceGap('New requirement discovery needs public research, not model speculation alone')
 if kind=='existing_defect':
  if not local or not runtime:raise EvidenceGap('Existing defect research requires verified repository sources and a successful controller experiment on current source')
  if not isinstance(defect,dict) or any(not isinstance(defect.get(k),str) or not defect[k].strip() or len(defect[k])>2000 for k in ('expected','observed','contract_source')):raise EvidenceGap('Existing defect needs defect_evidence with expected, observed, contract_source and experiment index')
  index=defect.get('experiment')
  if type(index) is not int or not 0<=index<len(experiments) or experiments[index].get('evidence_path') not in runtime:raise EvidenceGap('Defect must reference a successful controller experiment index')
  if not any(s.get('kind')=='repository' and s.get('path')==defect['contract_source'] for s in report.get('sources',[])):raise EvidenceGap('Defect contract_source must cite an independently verified repository source')
 return {'kind':kind,'public_sources':public,'runtime_receipts':runtime,'repository_verified':bool(local)}


def proposal_supported(report):
 """Model-provided kind alone never relaxes the public research gate."""
 b=(report or {}).get('evidence_basis',{})
 return bool(b.get('public_sources') or b.get('kind')=='existing_defect' and b.get('repository_verified') and b.get('runtime_receipts'))
