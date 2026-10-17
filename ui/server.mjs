import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const run=promisify(execFile), root=fileURLToPath(new URL('../',import.meta.url));
export function installLooop(app){
  function owner(req,res,next){
    if(req.actor?.type!=='board'||!req.actor.userId){if(req.path==='/looop')return res.redirect('/auth?next=%2Flooop');return res.status(401).json({error:'Sign in required'});}
    if(!req.actor.isInstanceAdmin)return res.status(403).json({error:'Instance owner access required'});
    res.set('Cache-Control','no-store');next();
  }
  app.get('/',(req,res,next)=>{if(req.actor?.type==='board'&&req.actor.isInstanceAdmin&&!req.query.paperclip)return res.redirect('/looop');next();});
  app.get('/looop',owner,async(req,res,next)=>{try{res.type('html').send(await readFile(root+'ui/index.html','utf8'));}catch(e){next(e);}});
  for(const name of ['app.js','style.css'])app.get('/looop-assets/'+name,owner,async(req,res,next)=>{try{res.type(name.endsWith('.js')?'js':'css').send(await readFile(root+'ui/'+name,'utf8'));}catch(e){next(e);}});
  app.get('/api/looop/status',owner,async(req,res)=>{
    try{const {stdout}=await run('/usr/bin/python3',[root+'bin/console.py'],{cwd:root,maxBuffer:1024*1024});res.json(JSON.parse(stdout));}
    catch{res.status(503).json({error:'项目状态暂时无法读取；请保留当前页面并重试。'});}
  });
}
