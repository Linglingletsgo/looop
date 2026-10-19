#!/usr/bin/env python3
"""Publish looop default roles into Magpie's native subagent library."""
import datetime,http.cookiejar,json,pathlib,re,shutil,subprocess,urllib.parse,urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
DESCRIPTIONS={
 'product-manager':'Research and define the next evidenced product outcome; project roles take precedence.',
 'product':'Clarify authorized requirements and unresolved decisions; optional product support.',
 'builder':'Implement the approved task within scope and verify the change.',
 'reviewer':'Independently review current changes and execution evidence.',
 'qa':'Run reproducible authorized checks and report actual results.',
 'acceptance':'Verify observable acceptance criteria when the project explicitly requests this role.',
 'ui-designer':'Provide visual and component guidance when UI advice is requested.',
 'ux-designer':'Provide bounded user flow and interaction guidance when requested.'}
PREFIX="""This is a looop fallback role. Read the current project's rules and structured current state first. If the project defines this responsibility, follow its role contract instead of this fallback. Use only for the assigned task; availability does not add a workflow stage or authorize delegation, implementation, publication or merge. Controller means the caller or scheduler; without a scheduler, return the result to the caller. Follow the caller's result format; when none is specified, use concise prose. Do not invent a Packet or handoff requirement for ordinary standalone discussion.

"""

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
 expected={}
 for path in files:
  name='looop-'+path.stem;old=existing.get(name,{})
  item={'name':name,'description':DESCRIPTIONS[path.stem],'prompt':PREFIX+path.read_text().strip()+'\n','skills':old.get('skills',[]),'mcp':old.get('mcp',[]),'agents':list(dict.fromkeys([*old.get('agents',[]),*agents]))}
  api('library/subagents/save',{'old':name if name in existing else '', 'subagent':item});expected[name]=item
 result={v['name']:v for v in api('library').get('subagents',[])}
 for name,item in expected.items():
  saved=result[name]
  if saved['prompt'].strip()!=item['prompt'].strip() or not set(agents)<=set(saved['agents']):raise ValueError('Magpie subagent did not retain the requested definition: '+name)
  if saved.get('problems'):raise ValueError('Inspect Magpie native configuration conflict for '+name)
 print(json.dumps({'synced':list(expected),'agents':agents,'backup':str(backup)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
