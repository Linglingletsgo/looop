// Integration checks use a disposable project state and the real console child-process protocol.
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const express=createRequire(root+'.runtime/package.json')('express');
const fixture=await mkdtemp(join(tmpdir(),'looop-http-'));
process.env.AGENT_RUNTIME_ROOT=fixture;
const {installLooop}=await import('../ui/server.mjs');
let server;
try{
 await mkdir(join(fixture,'data'),{recursive:true});
 await writeFile(join(fixture,'data/control.json'),JSON.stringify({projects:{fixture:{repo:fixture}},agents:{}}));
 execFileSync('/usr/bin/python3',['-c','import sys;sys.path.insert(0,sys.argv[1]);from project_state import Store;Store(sys.argv[2]).ensure("fixture")',root+'bin',fixture],{env:process.env});
 const app=express();app.use((req,res,next)=>{if(req.get('x-test-owner')==='yes')req.actor={type:'board',userId:'fixture-owner',isInstanceAdmin:true};next();});installLooop(app);
 server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});const base='http://127.0.0.1:'+server.address().port;
 const post=(value,extra={})=>fetch(base+'/api/looop/action',{method:'POST',headers:{'Content-Type':'application/json',Origin:base,'x-test-owner':'yes',...extra},body:JSON.stringify(value)});
 assert.equal((await post({},{'x-test-owner':'no'})).status,401);
 assert.equal((await post({},{Origin:'http://outside.example'})).status,403);
 const command={action:'intent',lane:'fixture',revision:0,request_id:'http-requirement',title:'Product request',body:'Observable product improvement',priority:'high'};
 let response=await post(command);assert.equal(response.status,200);let value=await response.json();assert.equal(value.result.revision,1);
 response=await post(command);assert.equal(response.status,200);assert.equal((await response.json()).result.replayed,true);
 assert.equal((await post({...command,request_id:'stale'})).status,409);
 assert.equal((await post({action:'loop',lane:'fixture',mode:'continuous',revision:1,request_id:'forbidden'})).status,422);
 response=await post({action:'loop',lane:'fixture',mode:'paused',revision:1,request_id:'pause'});assert.equal(response.status,200);
 console.log('Disposable HTTP integration passed: owner auth, CSRF, real intent persistence/idempotency, revision conflict, no authority expansion, pause.');
}finally{if(server)await new Promise(resolve=>server.close(resolve));await rm(fixture,{recursive:true,force:true});}
