"""File-based harness handoff. Dialogue is never execution state."""
import json,uuid
from output_protocol import OutputError

def validate(value,schema):
 kind=schema.get('type')
 if kind=='object':
  if not isinstance(value,dict):raise OutputError('Handoff result must be a JSON object')
  if any(k not in value for k in schema.get('required',[])):raise OutputError('Handoff result missing required fields')
  properties=schema.get('properties',{})
  if schema.get('additionalProperties') is False and set(value)-properties.keys():raise OutputError('Unexpected handoff result fields')
  for k,v in value.items():
   if k in properties:validate(v,properties[k])
 elif kind=='array':
  if not isinstance(value,list):raise OutputError('Handoff field must be an array')
  for item in value:validate(item,schema.get('items',{}))
 elif kind=='string' and not isinstance(value,str):raise OutputError('Handoff field must be a string')
 if 'enum' in schema and value not in schema['enum']:raise OutputError('Invalid handoff field value')

def prepare(scratch,schema):
 path=scratch/'handoff.json'
 if path.exists() or path.is_symlink():raise OutputError('Handoff path already exists; use a fresh run directory')
 identity={'version':1,'run_id':scratch.name,'nonce':uuid.uuid4().hex}
 path.write_text(json.dumps({**identity,'result':None},ensure_ascii=False,indent=2));path.chmod(0o600)
 (scratch/'handoff.schema.json').write_text(json.dumps({'type':'object','properties':{**{k:{'enum':[v]} for k,v in identity.items()},'result':schema},'required':[*identity,'result'],'additionalProperties':False},ensure_ascii=False,indent=2))
 return identity

def read(scratch,schema,identity):
 path=scratch/'handoff.json'
 if path.is_symlink() or not path.is_file() or path.stat().st_size>128000:raise OutputError('Missing or invalid handoff.json file')
 try:
  def pairs(items):
   result={}
   for k,v in items:
    if k in result:raise OutputError('Duplicate key in handoff.json')
    result[k]=v
   return result
  doc=json.loads(path.read_text(),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(OutputError('Non-finite JSON value')))
 except (ValueError,UnicodeError) as exc:raise OutputError('Invalid JSON in handoff.json: '+str(exc)) from exc
 if not isinstance(doc,dict) or set(doc)!=set(identity)|{'result'} or any(doc.get(k)!=v or type(doc.get(k)) is not type(v) for k,v in identity.items()):raise OutputError('Handoff identity changed or belongs to another run')
 validate(doc['result'],schema)
 return doc['result']

def instruction(scratch):
 return ('\nFILE HANDOFF — authoritative output contract: Before finishing, use file tools to update ONLY the result field of '+str(scratch/'handoff.json')+'. Keep version, run_id and nonce unchanged. Read '+str(scratch/'handoff.schema.json')+' for the strict JSON file schema. Earlier "Return JSON" instructions describe this file result, NOT your chat response. Write valid JSON to the file, preferably atomically. This run directory is the sole permitted output-artifact exception for read-only roles; do not modify project source or scheduler/shared state. The result file records your actual conclusion and findings; never claim approval to satisfy formatting. Your final chat response may be natural language and is not parsed.\n')
