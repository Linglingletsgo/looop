// Exercise the actual dialog/render functions without requiring a browser installation.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.value='';}
 append(...nodes){this.children.push(...nodes);}
 prepend(node){this.children.unshift(node);}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(){}
 addEventListener(name,fn){this.listeners[name]=fn;}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const nodes=new Map();const document={hidden:true,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);},createElement:tag=>new Element(tag),createTextNode:text=>text,addEventListener(){},querySelectorAll:()=>[]};
const response={revision:8,title:'Fixture',phase:'blocked',holds:[],intervention:{title:'连接中断',stage:'开发',cause:'Connection refused',instruction:'恢复网络',preserved:'草稿保留',category:'connection',retry_allowed:true,retry_effect:'重新开发、检查、审核',decisions:[],diagnostic:'fixture diagnosis'}};
const context=vm.createContext({document,URL,console,crypto:{randomUUID:()=> 'test-request'},setInterval(){},fetch:async()=>({ok:true,status:200,json:async()=>({ok:true,result:response})}),navigator:{clipboard:{writeText:async()=>{}}}});
await vm.runInContext(await readFile(new URL('../ui/app.js',import.meta.url),'utf8'),context);
const project={id:'demo',name:'Demo',revision:1,attention:[],tasks:[]};context.project=project;
await vm.runInContext("evidence(project,'task')",context);
const flatten=node=>node instanceof Element?[node,...node.children.flatMap(flatten)]:[];
let elements=flatten(nodes.get('dialog-body'));
assert.ok(elements.some(n=>n.tag==='h4'&&n.textContent==='怎么处理'));
assert.ok(elements.some(n=>n.tag==='button'&&n.textContent==='复制诊断给维护对话'));
assert.ok(elements.find(n=>n.tag==='details').children.some(n=>n.tag==='pre'));
let payload;context.capture=value=>{payload=value;};vm.runInContext('act=async payload=>capture(payload)',context);
const input=elements.find(n=>n.tag==='textarea');input.value='网络恢复';elements.find(n=>n.tag==='form').listeners.submit({preventDefault(){}});
assert.equal(payload.revision,8);assert.equal(payload.action,'retry');assert.equal(payload.reason,'网络恢复');
response.intervention.retry_allowed=false;response.intervention.unavailable_reason='基线变化，需要重新规划';
await vm.runInContext("evidence(project,'task')",context);elements=flatten(nodes.get('dialog-body'));
assert.ok(!elements.some(n=>n.tag==='form'));assert.ok(elements.some(n=>n.textContent===response.intervention.unavailable_reason));
console.log('Intervention UI passed: readable diagnosis, collapsed evidence, explicit recovery, latest revision, unavailable action hidden.');
