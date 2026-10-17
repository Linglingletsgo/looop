"""Operator-only Paperclip client; never imported inside a model sandbox."""
import http.cookiejar,json,pathlib,urllib.request,urllib.error,os
from runtime import ROOT
_settings=ROOT/'data/local-settings.json'
BASE=os.environ.get('PAPERCLIP_URL') or (json.loads(_settings.read_text()).get('board_url') if _settings.exists() else None) or 'http://127.0.0.1:3101'
class Board:
 def __init__(self):
  self.jar=http.cookiejar.MozillaCookieJar(str(ROOT/'data/board-cookies.txt'))
  if pathlib.Path(self.jar.filename).exists():self.jar.load(ignore_discard=True,ignore_expires=True)
  self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
 def api(self,method,path,data=None,retry=True):
  req=urllib.request.Request(BASE+'/api'+path,None if data is None else json.dumps(data).encode(),{'Content-Type':'application/json','Origin':BASE},method=method)
  try:
   with self.opener.open(req,timeout=60) as r:
    body=r.read();return json.loads(body) if body else None
  except urllib.error.HTTPError as e:
   if e.code==401 and retry:
    creds=json.loads((ROOT/'data/owner-login.json').read_text()); self.api('POST','/auth/sign-in/email',creds,False)
    self.jar.save(ignore_discard=True,ignore_expires=True);pathlib.Path(self.jar.filename).chmod(0o600)
    return self.api(method,path,data,False)
   raise RuntimeError(f'Paperclip {method} {path}: {e.code} {e.read().decode()[:250]}') from None
