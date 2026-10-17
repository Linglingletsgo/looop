#!/usr/bin/env python3
"""Version-checked deployment patch: default owner email, never a password."""
import hashlib,pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
p=ROOT/'.runtime/node_modules/@paperclipai/server/ui-dist/assets/index-xCoSuYwt.js'
old='[a,i]=(0,m.useState)("sign_in"),[o,l]=(0,m.useState)(""),[c,d]=(0,m.useState)(""),[u,h]=(0,m.useState)("")'
new=old.replace('[c,d]=(0,m.useState)("")','[c,d]=(0,m.useState)("dominic@paperclip.local")')
s=p.read_text()
if new in s:print('Owner email already configured.')
if new not in s and s.count(old)!=1:raise SystemExit('UI bundle differs; review new version before patching.')
backup=ROOT/'data/deployment-backups'/('login-ui-'+hashlib.sha256(s.encode()).hexdigest()+'.js')
backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
if not backup.exists():backup.write_text(s);backup.chmod(0o600)
p.write_text(s.replace(old,new))
print('Login email default configured. Password field unchanged.')
# Keep module references consistent while invalidating immutable browser caches.
ui=p.parent.parent
old_ref='index-xCoSuYwt.js'
new_ref='index-xCoSuYwt.js?owner-email=1'
for asset in [ui/'index.html',*ui.joinpath('assets').glob('*.js')]:
    content=asset.read_text()
    if old_ref not in content or new_ref in content:continue
    original=ROOT/'data/deployment-backups'/('email-cache-'+asset.name)
    if not original.exists():original.write_text(content);original.chmod(0o600)
    asset.write_text(content.replace(old_ref,new_ref))
print('UI module cache version updated.')
