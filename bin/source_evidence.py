"""Validate source quotations by exact content, independent of language or length."""
from project_adapter import safe_file

class SourceEvidenceError(ValueError):pass


def quote(repo,name,value):
 if not isinstance(name,str):raise SourceEvidenceError('Source path must be a repository file')
 try:path=safe_file(repo,name)
 except ValueError as exc:raise SourceEvidenceError('Source file unavailable: '+name[:240]) from exc
 if not isinstance(value,str) or not value.strip():raise SourceEvidenceError('Source quotation must be nonempty: '+name)
 if len(value)>2000:raise SourceEvidenceError('Source quotation exceeds 2000 characters: '+name)
 if value not in path.read_text():raise SourceEvidenceError('Source quote not found: '+name)
 return value


def verify_completion(repo,artifacts,goal,evidence,target):
 """Verify proof identity and exact artifact quotations, never judge usability."""
 from product_goals import completion_coverage
 completion_coverage(evidence,goal['success_criteria'],goal.get('experience'))
 for e in evidence:
  if e.get('kind') in ('agent_walkthrough','user_test'):
   if e.get('target_sha')!=target:raise ValueError('Experience proof targets another revision')
   quote(artifacts,e.get('path'),e.get('quote'))
  else:safe_file(repo,e.get('path'))
 return evidence
