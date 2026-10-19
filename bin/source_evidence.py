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
