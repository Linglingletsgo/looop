"""Skill-led discovery, with independently retrieved citations before new product proposals."""
import datetime,hashlib,html,json,pathlib,re,urllib.request,urllib.parse
from project_adapter import safe_file
from planning_runtime import invoke
from runtime import CODE_ROOT

DEFAULT_ROOT=CODE_ROOT/'pm-skills'

def default_catalog():
 manifest=json.loads((DEFAULT_ROOT/'manifest.json').read_text())
 result=[]
 for item in manifest['skills']:
  content=safe_file(DEFAULT_ROOT,item['path']).read_bytes()
  if hashlib.sha256(content).hexdigest()!=item['sha256']:raise ValueError('Default PM skill differs from reviewed manifest: '+item['id'])
  result.append({'path':item['id'],'description':item['description'],'origin':'default','file':item['path'],'sha256':item['sha256'],'upstream':item['upstream'],'license':item['license']})
 return result


def catalog(repo,adapter=None):
 paths=(adapter or {}).get('research',{}).get('skill_paths')
 if paths is None:
  paths=[str(p.relative_to(repo)) for base in ('.agents/skills','.claude/skills','.codex/skills') for p in (pathlib.Path(repo)/base).glob('*/SKILL.md') if p.is_file()]
 result=[]
 for name in sorted(set(paths)):
  content=safe_file(repo,name).read_text();result.append({'path':name,'description':content[:1100],'origin':'project'})
 return result+default_catalog()


def load_skills(repo,plan,available):
 selected=plan.get('skills');known={v['path']:v for v in available}
 if not isinstance(selected,list) or len(selected)>6 or any(not isinstance(p,str) for p in selected) or len(set(selected))!=len(selected) or any(p not in known for p in selected):raise ValueError('Research must select existing catalog skills')
 if not selected and (not isinstance(plan.get('skill_reason'),str) or not plan['skill_reason'].strip()):raise ValueError('Explain missing or inapplicable research skills')
 defaults=any(known[p].get('origin')=='default' for p in selected)
 if defaults and any(v.get('origin')=='project' for v in available) and (not isinstance(plan.get('fallback_reason'),str) or not plan['fallback_reason'].strip()):raise ValueError('Default methods need an explicit gap in project skills')
 selected=list(selected)
 if defaults and 'looop:investigation' not in selected:selected.insert(0,'looop:investigation')
 if not selected and not any(v.get('origin')=='project' for v in available) and 'looop:investigation' in known:selected=['looop:investigation']
 result=[]
 for name in selected:
  item=known[name];default=item.get('origin')=='default'
  content=safe_file(DEFAULT_ROOT if default else repo,item['file'] if default else name).read_bytes();digest=hashlib.sha256(content).hexdigest()
  if default and digest!=item['sha256']:raise ValueError('Default PM skill changed after selection')
  result.append({'path':name,'origin':item.get('origin','project'),'sha256':digest,'content':content.decode(),**({k:item[k] for k in ('upstream','license')} if default else {})})
 return result


def fetch(url):
 parsed=urllib.parse.urlsplit(url)
 if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Public research requires an HTTP(S) source URL')
 request=urllib.request.Request(url,headers={'User-Agent':'looop-research/1.0'})
 with urllib.request.urlopen(request,timeout=30) as response:
  raw=response.read(2*1024*1024+1)
  if len(raw)>2*1024*1024:raise ValueError('Research source too large; cite a targeted source')
  return response.geturl(),raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')


def normalize(value):return ' '.join(html.unescape(re.sub('<[^>]+>',' ',value)).split())


def verify(report,repo,public_required=False):
 if not isinstance(report,dict) or report.get('status') not in ('supported','insufficient_evidence','rejected'):raise ValueError('Research requires an explicit evidence conclusion')
 for field in ('question','finding','counterevidence','recommendation'):
  if not isinstance(report.get(field),str) or not report[field].strip() or len(report[field])>5000:raise ValueError('Research requires '+field)
 if report['status']!='supported':return {k:report[k] for k in ('status','question','finding','counterevidence','recommendation')}
 sources=report.get('sources')
 if not isinstance(sources,list) or not 1<=len(sources)<=8:raise ValueError('Research requires attributable source evidence')
 verified=[];public=0
 for source in sources:
  if not isinstance(source,dict):raise ValueError('Research source must be an object')
  quote=source.get('quote')
  if not isinstance(quote,str) or not 20<=len(quote)<=2000:raise ValueError('Research requires exact source quotations')
  if source.get('kind')=='repository':
   name=source.get('path');content=safe_file(repo,name).read_text();address=name
  elif source.get('kind')=='public':
   try:address,content=fetch(source.get('url',''))
   except (OSError,TimeoutError) as exc:return {'status':'insufficient_evidence','question':report['question'],'finding':'A cited public source could not be independently retrieved.','counterevidence':report['counterevidence'],'recommendation':'公开证据暂时无法核验，保留当前需求并等待来源恢复；不发起开发。','sources':verified,'source_gap':{'url':source.get('url'),'error_type':type(exc).__name__}}
   public+=1
  else:raise ValueError('Unrecognized research source')
  if normalize(quote) not in normalize(content):raise ValueError('Research quotation not found in independently read source')
  verified.append({**source,'verified_source':address,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sha256':hashlib.sha256(content.encode()).hexdigest()})
 if public_required and not public:raise ValueError('New requirement discovery needs public research, not model speculation alone')
 return {**{k:report[k] for k in ('status','question','finding','counterevidence','recommendation')},'sources':[{k:v for k,v in s.items() if k in ('kind','path','url','quote','verified_source','sha256','retrieved_at')} for s in verified]}


def brief(report):
 """Decision evidence only; full provenance remains in the audit artifact."""
 if not report:return None
 result={k:report[k] for k in ('status','question','finding','counterevidence','recommendation') if k in report}
 result['sources']=[{k:s[k] for k in ('kind','path','url','quote') if k in s} for s in report.get('sources',[])]
 return result


def perform(run,repo,folder,role_prompt,context,fresh,execution_route,adapter=None,public_required=False):
 available=catalog(repo,adapter)
 # Descriptions only in selection; full reviewed bytes are loaded for the chosen methods.
 phase='RESEARCH PLAN ONLY. Project role describes the wider workflow; this call selects a discovery question and methods, not a task Packet. '
 selection='\nBefore proposing any feature, choose ONE concrete discovery question and a stopping condition. Prefer relevant project PM skills. Default looop: methods fill only gaps: when project skills exist, give fallback_reason naming the missing method. Never replace a required project skill. Select only methods relevant to this decision, not the whole catalog. Explain unavailable/inapplicable skills explicitly. Project authority and data boundaries override skills. Return JSON {"question":"...","stop_condition":"...","skills":["path/SKILL.md"],"skill_reason":"...","fallback_reason":"only if defaults fill a project gap"}.\nCatalog: '+json.dumps([{k:v for k,v in item.items() if k in ('path','description','origin')} for item in available],ensure_ascii=False)
 def validate_plan(plan):
  if not isinstance(plan,dict):raise ValueError('Research plan must be a JSON object')
  for field in ('question','stop_condition'):
   if not isinstance(plan.get(field),str) or not plan[field].strip() or len(plan[field])>2000:raise ValueError('Research needs a bounded discovery question and stopping condition')
  load_skills(repo,plan,available)
  for key in ('skill_reason','fallback_reason'):
   if key in plan and (not isinstance(plan[key],str) or len(plan[key])>2000):raise ValueError('Research plan explanation must be concise')
 plan=invoke(run,repo,folder/'research-plan',phase+'\n'+role_prompt+'\n'+context+'\n'+selection,fresh,validate=validate_plan,role='readonly',execution_route=execution_route)
 skills=load_skills(repo,plan,available)
 plan={k:v for k,v in plan.items() if k in ('question','stop_condition','skills','skill_reason','fallback_reason')}
 for key in ('skill_reason','fallback_reason'):
  if key in plan and (not isinstance(plan[key],str) or len(plan[key])>2000):raise ValueError('Research plan explanation must be concise')
 plan['skills']=[s['path'] for s in skills]
 prompt=role_prompt+'\n'+context+'\nResearch plan: '+json.dumps({k:plan[k] for k in ('question','stop_condition')},ensure_ascii=False)+'\nActually loaded skills, use their methods without expanding permissions:\n'+'\n'.join(s['path']+'\n'+s['content'] for s in skills)
 prompt+='\nConduct the research using real tools and permitted sources. Distinguish facts, inference and unknowns. Do not invent interviews, analytics, experiments or citations. No outreach, private data, payment or production access. '+('This is new requirement discovery: investigate public sources as well as current repository reality. ' if public_required else 'Validate the backlog/confirmed requirement against repository evidence; public research only when needed and permitted. ')
 prompt+='Return only JSON {"status":"supported|insufficient_evidence|rejected","question":"...","finding":"...","counterevidence":"...","recommendation":"...","skill_usage":[{"path":"...","impact":"method actually applied"}],"sources":[{"kind":"repository|public","path":"repo/file","url":"https://...","quote":"exact source quotation"}]}. When unavailable evidence prevents a conclusion, return insufficient_evidence with recommendation; never substitute a guessed requirement.'
 def validate_report(report):
  if not isinstance(report,dict) or report.get('status') not in ('supported','insufficient_evidence','rejected'):raise ValueError('Research requires an explicit evidence conclusion')
  for field in ('question','finding','counterevidence','recommendation'):
   if not isinstance(report.get(field),str) or not report[field].strip() or len(report[field])>5000:raise ValueError('Research requires '+field)
  if not isinstance(report.get('skill_usage'),list):raise ValueError('Research requires a skill usage list')
  for skill in skills:
   if not any(isinstance(v,dict) and v.get('path')==skill['path'] and isinstance(v.get('impact'),str) and v['impact'].strip() and len(v['impact'])<=2000 for v in report['skill_usage']):raise ValueError('Research must explain the impact of each loaded skill')
  if report['status']=='supported':
   sources=report.get('sources')
   if not isinstance(sources,list) or not 1<=len(sources)<=8:raise ValueError('Research requires attributable source evidence')
   for source in sources:
    if not isinstance(source,dict):raise ValueError('Research source must be an object')
    if source.get('kind')=='repository':
     name=source.get('path')
     if not isinstance(name,str):raise ValueError('Repository source path must be a string without line-number suffixes')
     try:safe_file(repo,name)
     except ValueError as exc:raise ValueError('Repository source path must name an existing file, without line-number suffixes: '+name[:240]) from exc
    elif source.get('kind')!='public':raise ValueError('Unrecognized research source')
 report=invoke(run,repo,folder/'research',prompt,fresh,validate=validate_report,role='readonly',execution_route=execution_route)
 usage=report['skill_usage']
 report=verify(report,repo,public_required)
 return {**report,'skill_usage':[{'path':s['path'],'impact':next(v['impact'] for v in usage if isinstance(v,dict) and v.get('path')==s['path'])} for s in skills],'plan':plan,'loaded_skills':[{k:v for k,v in s.items() if k!='content'} for s in skills]}
