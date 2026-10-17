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
 response=await post({action:'settings',lane:'fixture',revision:2,request_id:'selection-settings',selection_mode:'backlog_and_research',daily_limit:null});assert.equal(response.status,200);assert.equal((await response.json()).result.revision,3);
 assert.equal((await post({action:'settings',lane:'fixture',revision:3,request_id:'bad-selection',selection_mode:'anything',daily_limit:null})).status,422);
 const executor={action:'execution_settings',revision:0,request_id:'http-executor',harness:'codex',routes:Object.fromEntries(['planning','build','review','acceptance','advisory'].map(s=>[s,'codex'])),codex_model:null};
 response=await post(executor);assert.equal(response.status,200);assert.equal((await response.json()).result.revision,1);
 response=await post(executor);assert.equal((await response.json()).result.replayed,true);
 assert.equal((await post({...executor,request_id:'stale-executor'})).status,409);
 assert.equal((await post({...executor,revision:1,request_id:'unsupported-harness',harness:'pi'})).status,422);
 console.log('Disposable HTTP integration passed: owner auth, CSRF, real intent persistence/idempotency, revision conflict, no authority expansion, pause.');
}finally{if(server)await new Promise(resolve=>server.close(resolve));await rm(fixture,{recursive:true,force:true});}
