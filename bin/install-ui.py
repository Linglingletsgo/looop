#!/usr/bin/env python3
"""Reproducible, version-checked hook into Paperclip; no minified bundle edits."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
def install(root=ROOT):
 root=pathlib.Path(root);server=root/'.runtime/node_modules/@paperclipai/server';meta=json.loads((server/'package.json').read_text())
 if meta['version']!='2026.1012.0':raise ValueError('Review UI mount for new Paperclip version')
 app=server/'dist/app.js';s=app.read_text();hook='    // looop: owner-authenticated project console\n    installLooop(app);\n';anchor='    app.use("/api", api);'
 if hook not in s:
  if s.count(anchor)!=1:raise ValueError('Paperclip API anchor changed')
  s='import { installLooop } from '+json.dumps((root/'ui/server.mjs').as_uri())+';\n'+s.replace(anchor,hook+anchor);app.write_text(s)
 print('looop console mounted at /looop (Paperclip owner session required)')
if __name__=='__main__':install()
