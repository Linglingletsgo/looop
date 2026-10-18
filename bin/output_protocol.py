"""Conservative transport decoding; never infer a verdict from prose or default success."""
import json,re

class OutputError(ValueError):pass

def object_value(text):
 text=text.strip().lstrip('\ufeff')
 try:value=json.loads(text)
 except json.JSONDecodeError as original:
  blocks=list(re.finditer(r'^```(?:json)?[ \t]*\n([\s\S]*?)\n```[ \t]*$',text,re.M))
  if len(blocks)!=1:raise OutputError('Expected one JSON object or one unambiguous JSON fence') from original
  block=blocks[0];outside=(text[:block.start()]+text[block.end():]).strip()
  # Outside text is not a second authority source. Refuse possible competing conclusions.
  if outside and (any(c in outside for c in '{}[]') or re.search(r'\b(approved|blocked|changes_requested|rejected|no_work|not ready|not approved|unresolved|cannot proceed)\b|阻塞|受阻|未解决|未通过|不批准|需修改|需要修改',outside,re.I)):
   raise OutputError('Ambiguous conclusions outside JSON; preserve output for correction') from original
  try:value=json.loads(block[1])
  except json.JSONDecodeError as exc:raise OutputError('Invalid JSON fence') from exc
 if not isinstance(value,dict):raise OutputError('Expected a JSON object')
 return value

def delivery_schema(stage):
 # String findings preserve full severity/location/evidence in one item across providers.
 properties={'verdict':{'type':'string','enum':['approved','blocked'] if stage in ('build','plan','advisory') else ['approved','changes_requested','blocked']},'findings':{'type':'array','items':{'type':'string'}}}
 if stage=='build':properties['summary']={'type':'string'}
 if stage in ('plan','advisory'):properties['plan']={'type':'string'}
 if stage=='acceptance':properties['evidence']={'type':'array','items':{'type':'string'}}
 return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
