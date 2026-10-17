import urllib.request,urllib.error,http.cookiejar,json,pathlib,secrets,re
root=pathlib.Path(__file__).resolve().parent.parent
from board import BASE as base
cred=root/'data/owner-login.json'
if not cred.exists():
 cred.write_text(json.dumps({'email':'dominic@paperclip.local','password':secrets.token_urlsafe(30)},indent=2));cred.chmod(0o600)
c=json.loads(cred.read_text())
jar=http.cookiejar.MozillaCookieJar(str(root/'data/board-cookies.txt'))
opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def api(path,data):
 req=urllib.request.Request(base+path,json.dumps(data).encode(),{'Content-Type':'application/json','Origin':base})
 try:
  with opener.open(req,timeout=30) as r: return json.load(r)
 except urllib.error.HTTPError as e:
  print('Request failed',path,e.code,e.read().decode()[:300]);raise SystemExit(1)
api('/api/auth/sign-in/email',c)
jar.save(ignore_discard=True,ignore_expires=True)
(root/'data/board-cookies.txt').chmod(0o600)
req=urllib.request.Request(base+'/api/companies')
with opener.open(req) as r: print('Owner authenticated, companies access',r.status)
print('Credentials and session stored owner-only. No secret printed.')
