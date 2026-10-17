import pathlib,subprocess,json
from board import ROOT,Board
repo=ROOT/'data/fixture-repo';repo.mkdir(parents=True,exist_ok=True)
if not (repo/'.git').exists():
 subprocess.run(['git','init','-b','main',str(repo)],check=True,stdout=subprocess.DEVNULL)
 (repo/'AGENTS.md').write_text('Synthetic fixture repository. Roles: Product plans; Builder edits only app.py; Reviewer independently reviews readonly source; Acceptance tests the JSON process as black box. Never merge or deploy.\n')
 (repo/'app.py').write_text('''import json,re,sys,unicodedata

def slug(value):
    return str(value).lower().replace(" ", "-")

if __name__ == "__main__":
    try:
        data=json.load(sys.stdin)
        print(json.dumps({"slug":slug(data["text"])}))
    except (KeyError,ValueError,TypeError):
        print(json.dumps({"error":"invalid input"}))
        sys.exit(2)
''')
 (repo/'test_app.py').write_text('''import unittest
from app import slug
class TestSlug(unittest.TestCase):
 def test_ascii(self): self.assertEqual(slug("Hello World"),"hello-world")
 def test_accents(self): self.assertEqual(slug("Café Déjà Vu"),"cafe-deja-vu")
 def test_separators(self): self.assertEqual(slug(" -- A___B!!! "),"a-b")
 def test_empty(self): self.assertEqual(slug("!!!"),"")
 def test_invalid(self):
  for value in [None,123,[],{}]:
   with self.assertRaises(TypeError):slug(value)
if __name__=="__main__":unittest.main()
''')
 subprocess.run(['git','-C',str(repo),'add','.'],check=True)
 subprocess.run(['git','-C',str(repo),'-c','user.name=Agent Fixture','-c','user.email=agent-fixture@localhost','commit','-m','fixture: baseline with failing slug requirements'],check=True,stdout=subprocess.DEVNULL)
sha=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
packet={'bundle':'normalize-slug','repo':str(repo),'baseline_sha':sha,'agent_system_sha':sha,'requirements':['R1: string input only; non-string raises TypeError','R2: Unicode NFKD normalization, remove combining accents, lowercase, replace each run of non ASCII a-z/0-9 with one hyphen, trim hyphens. Empty allowed.','R3: preserve JSON CLI; invalid input returns error JSON and exit2.'],'acceptance':['POST input {"text":"Café Déjà Vu"} must output {"slug":"cafe-deja-vu"}','Repeated separators and edge separators normalize; punctuation-only yields empty slug.','Missing text or non-string returns error JSON with exit2.'],'allowed_paths':['app.py'],'checks':[['python3','-m','unittest','-v']],'max_rounds':3,'risk':'high','entry':'app.py'}
(ROOT/'data/fixture-packet.json').write_text(json.dumps(packet,indent=2))
b=Board();companies=b.api('GET','/companies');company=next((x for x in companies if x['name']=='Agent Control Sandbox'),None)
if not company:company=b.api('POST','/companies',{'name':'Agent Control Sandbox','description':'Synthetic PoC only. No WOS source or secrets.'})
projects=b.api('GET',f'/companies/{company["id"]}/projects');p=next((x for x in projects if x['name']=='Delivery fixture'),None)
if not p:p=b.api('POST',f'/companies/{company["id"]}/projects',{'name':'Delivery fixture','status':'in_progress','workspace':{'name':'fixture','cwd':str(repo),'isPrimary':True}})
agents=b.api('GET',f'/companies/{company["id"]}/agents');agent=next((x for x in agents if x['name']=='Fixture delivery'),None)
if not agent:agent=b.api('POST',f'/companies/{company["id"]}/agents',{'name':'Fixture delivery','role':'general','adapterType':'process','adapterConfig':{'command':'/usr/bin/python3','args':[str(ROOT/'bin/fixture_worker.py')],'cwd':str(ROOT),'timeoutSec':3600},'runtimeConfig':{'heartbeat':{'enabled':False,'intervalSec':0,'wakeOnDemand':True}},'permissions':{'canCreateAgents':False,'canCreateSkills':False}})
state={'company':company['id'],'project':p['id'],'agent':agent['id']};(ROOT/'data/fixture-control.json').write_text(json.dumps(state,indent=2));print('Fixture initialized; no business repository changed.')
