import {execFile,spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {promisify} from 'node:util';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const run=promisify(execFile), root=fileURLToPath(new URL('../',import.meta.url));
const express=createRequire(root+'.runtime/package.json')('express');
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
  app.post('/api/looop/action',owner,(req,res,next)=>{
    const origin=req.get('origin');
    // Same-origin JSON is required even for authenticated owner requests.
    if(!origin||origin!==req.protocol+'://'+req.get('host'))return res.status(403).json({error:'Same-origin request required'});
    if(!req.is('application/json'))return res.status(415).json({error:'JSON required'});
    next();
  },express.json({limit:'32kb'}),async(req,res)=>{
    try{
      const child=spawn('/usr/bin/python3',[root+'bin/console_actions.py'],{cwd:root,stdio:['pipe','pipe','pipe']});
      const output=await new Promise((resolve,reject)=>{
        let stdout='',size=0;
        child.stdout.on('data',chunk=>{size+=chunk.length;if(size>1024*1024){child.kill();reject(new Error('Output limit'));}else stdout+=chunk;});
        child.stderr.on('data',()=>{});child.on('error',reject);
        child.on('close',code=>code===0?resolve(stdout):reject(new Error('Command failed')));
        child.stdin.on('error',reject);child.stdin.end(JSON.stringify(req.body));
      });
      const value=JSON.parse(output);res.status(value.ok?200:value.conflict?409:422).json(value);
    }catch{res.status(503).json({error:'操作结果暂时未知，请刷新状态后判断，不要重复提交。'});}
  });

}
