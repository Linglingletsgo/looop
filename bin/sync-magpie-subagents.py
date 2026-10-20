#!/usr/bin/env python3
"""Publish looop default roles into Magpie's native subagent library."""
import datetime,http.cookiejar,json,pathlib,re,shutil,subprocess,urllib.parse,urllib.request
from product_goals import EXPERIENCE_INSTRUCTIONS

ROOT=pathlib.Path(__file__).resolve().parents[1]
DESCRIPTIONS={
 'product-manager':'Research and define the next evidenced product outcome.',
 'product':'Clarify authorized requirements and unresolved decisions; optional product support.',
 'builder':'Implement the approved task within scope and verify the change.',
 'reviewer':'Independently review current changes and execution evidence.',
 'qa':'Run reproducible authorized checks and report actual results.',
 'acceptance':'Verify observable acceptance criteria when the project explicitly requests this role.',
 'ui-designer':'Provide visual and component guidance when UI advice is requested.',
 'ux-designer':'Provide bounded user flow and interaction guidance when requested.'}

def connect():
 text=subprocess.check_output(['magpie','daemon','web'],text=True,stderr=subprocess.STDOUT)
 links=re.findall(r'https?://[^\s]+',text)
 link=next((v for v in links if urllib.parse.urlsplit(v).hostname in ('127.0.0.1','localhost')),None)
 if not link:raise ValueError('Magpie daemon web must expose an existing local authenticated library')
 url=urllib.parse.urlsplit(link);base=urllib.parse.urlunsplit((url.scheme,url.netloc,'','',''))
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 with opener.open(link,timeout=15) as response:response.read()
 def api(path,value=None):
  req=urllib.request.Request(base+'/api/'+path,data=None if value is None else json.dumps(value).encode(),headers={'Content-Type':'application/json','Origin':base})
  with opener.open(req,timeout=60) as response:return json.load(response)
 return api

def main():
 api=connect();view=api('library');supported={v['id'] for v in view.get('subagentAgents',[]) if not v.get('no') and not v.get('wsl')}
 agents=[v for v in ('codex','claude') if v in supported]
 if not agents:raise ValueError('No supported native subagent targets')
 files=sorted((ROOT/'default-roles').glob('*.md'));existing={v['name']:v for v in view.get('subagents',[])}
 backup=ROOT/'data/backups'/('magpie-subagents-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True,mode=0o700)
 (backup/'library-subagents.json').write_text(json.dumps(view.get('subagents',[]),ensure_ascii=False,indent=2))
 for agent in agents:
  folder=next(pathlib.Path(v['dir']) for v in view['subagentAgents'] if v['id']==agent)
  if folder.exists():shutil.copytree(folder,backup/agent,symlinks=True)
 # Export reviewed skills without changing their scheduler-validated source hashes.
 manifest=json.loads((ROOT/'pm-skills/manifest.json').read_text())
 export=ROOT/'data/magpie-pm-skills';export.mkdir(parents=True,exist_ok=True)
 skill_names=[]
 for spec in manifest['skills']:
  source=ROOT/'pm-skills'/spec['path'];name='pm-'+source.parent.name
  target=export/name;target.mkdir(exist_ok=True)
  prompt=re.sub(r'^name: .*$', 'name: '+name, source.read_text(), count=1, flags=re.M)
  prompt=re.sub(r'Adapted for looop personal use\. Original and attribution: .*',
                'Adapted for personal use. Original and attribution: '+spec['upstream']['url'],prompt)
  (target/'SKILL.md').write_text(prompt)
  upstream=ROOT/'pm-skills/upstream'/spec['upstream']['repo'].split('/')[0]
  for notice in upstream.rglob('*'):
   if notice.is_file() and notice.name.upper().startswith(('LICENSE','NOTICE')):
    shutil.copy2(notice,target/notice.name)
  skill_names.append(name)
 probe=api('library/skills/probe',{'source':str(export)})
 candidates={v['name']:v['path'] for v in probe['candidates']}
 if not set(skill_names)<=candidates.keys():raise ValueError('PM skill export discovery failed')
 api('library/skills/install',{'source':probe['source'],'paths':[candidates[n] for n in skill_names],'agents':agents})
 expected={}
 for path in files:
  name=path.stem;previous='looop-'+name
  old_name=name if name in existing else previous if previous in existing else ''
  old=existing.get(old_name,{})
  # Same-name unmanaged native files are preserved in the complete backup above.
  if name not in existing:
   for agent in agents:
    folder=next(pathlib.Path(v['dir']) for v in view['subagentAgents'] if v['id']==agent)
    suffix='.toml' if agent=='codex' else '.md'
    conflict=folder/(name+suffix)
    if conflict.exists():conflict.unlink()
  prompt=path.read_text().strip()
  skills=old.get('skills',[])
  if name=='product-manager':
   prompt=prompt.replace('Define a small, complete Packet','Define a coherent, complete Packet')
   prompt+='\n\n'+EXPERIENCE_INSTRUCTIONS
   skills=list(dict.fromkeys([*skills,*skill_names]))
   prompt+='\n\nUse project-required research methods first; otherwise consult pm-investigation and the relevant installed PM skills: '+', '.join(n for n in skill_names if n!='pm-investigation')+'. Choose methods that inform the decision; do not run every method mechanically.'
  item={'name':name,'description':DESCRIPTIONS[name],'prompt':prompt,'skills':skills,'mcp':old.get('mcp',[]),'agents':list(dict.fromkeys([*old.get('agents',[]),*agents]))}
  api('library/subagents/save',{'old':old_name,'subagent':item});expected[name]=item
 result_view=api('library');result={v['name']:v for v in result_view.get('subagents',[])}
 for name,item in expected.items():
  saved=result[name]
  if saved['prompt'].strip()!=item['prompt'].strip() or not set(agents)<=set(saved['agents']):raise ValueError('Magpie subagent did not retain the requested definition: '+name)
  if saved.get('problems'):raise ValueError('Inspect Magpie native configuration conflict for '+name)
  if not set(item['skills'])<=set(saved.get('skills',[])):raise ValueError('Missing role skills: '+name)
  if 'looop-'+name in result:raise ValueError('Legacy prefixed role still present: '+name)
 installed={v['name'] for v in result_view.get('skills',[])}
 if not set(skill_names)<=installed:raise ValueError('Missing installed PM skills')
 print(json.dumps({'synced':list(expected),'skills':skill_names,'agents':agents,'backup':str(backup)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
