import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";
const file=p=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const source=file("public/offline-device-qa.js");
const shell=file("public/offline.html");
const worker=file("public/sw.js");

test("device readiness script cannot initiate writes, downloads or disclose actor data",()=>{
  assert.doesNotMatch(source,/\bfetch\s*\(|\bXMLHttpRequest\b|\bsendBeacon\s*\(|document\.cookie|localStorage|sessionStorage/);
  assert.doesNotMatch(source,/\.(put|add|delete|clear|getAll|setItem|removeItem)\s*\(/);
  assert.match(source,/\.transaction\(NAMES, "readonly"\)/);
  assert.match(source,/indexedDB\.databases\(\)/);
  assert.match(source,/navigator\.storage\.persisted\(\)/);
  assert.doesNotMatch(source,/\bconsole\.|\beval\s*\(/);
});
test("shell loads local QA only as public precached asset and retains no-capture boundary",()=>{
  assert.match(shell,/id="offline-qa-run"/);
  assert.match(shell,/id="offline-qa-checks"/);
  assert.match(shell,/src="\/offline-device-qa\.js" defer/);
  assert.match(shell,/captura de datos reales.*aún no están habilitados/);
  assert.match(worker,/vinto-off03c3-static-v1/);
  assert.match(worker,/"\/offline-device-qa\.js"/);
  assert.doesNotMatch(worker,/fetch.*\/api\/offline\/quality-package/);
});

function testRuntime({ready=true, persistent=true, noEnumeration=false}={}){
  const state={checks:[],listeners:{},openCount:0,dbWriteCount:0};
  function el(){
    return {textContent:"",hidden:false,disabled:false,dataset:{},children:[],
       addEventListener(name,fn){this.event=name;this.listener=fn;},
       replaceChildren(...args){this.children=args;},
       appendChild(child){this.children.push(child);}};
  }
  const button=el(), result=el(),list=el();
  const nodes={"offline-qa-run":button,"offline-qa-result":result,"offline-qa-checks":list};
  const context={
    document:{getElementById(id){return nodes[id]},createElement(){return el()}},
    window:{isSecureContext:true},
    navigator:{serviceWorker:{controller:{}},storage:{persisted:async()=>persistent}},
    caches:{keys:async()=>["vinto-off03c3-static-v1"],
       match:async()=>({status:200})},
    indexedDB:{databases: noEnumeration?undefined:async()=>ready?
        [{name:"vinto-off03a-profiles-v1",version:3}]:[],
        open(){state.openCount++; const req={};
          Promise.resolve().then(()=>{
            const db={version:3,objectStoreNames:{contains:x=>["profiles","scopes","quality_packages"].includes(x)},
               close(){},transaction(names,mode){
                 assert.equal(mode,"readonly"); const tx={};
                 tx.objectStore=n=>({count(){
                   const r={};
                   Promise.resolve().then(()=>{r.result=n==="quality_packages"?2:1;r.onsuccess?.();
                     state.checks.push(n);
                     if(state.checks.length===3)Promise.resolve().then(()=>tx.oncomplete?.());
                   });return r;}}
                 );return tx;
               }};
            req.result=db;req.onsuccess?.();
          });return req;
        }}
  };
  context.window.caches=context.caches;
  context.window.indexedDB=context.indexedDB;
  vm.runInNewContext(source,context,{timeout:3000});
  return {button,result,list,state};
}
test("real executable diagnostics report prepared local browser without exposing identity",async()=>{
  const env=testRuntime();
  await env.button.listener();
  // handler returns void and starts an async task; await all microtasks.

  assert.ok(env.list.children.some(x=>x.textContent.startsWith("OK · Perfil único")));
  assert.ok(env.list.children.some(x=>x.textContent.startsWith("OK · Paquete")));
  assert.equal(env.state.openCount,1);
  assert.equal(env.result.dataset.status,"warn"); // rights cannot be verified offline
  assert.ok(!env.list.children.some(x=>x.textContent.includes("11111111-")));
});
test("unprepared browser blocks and DOES NOT create a database",async()=>{
  const env=testRuntime({ready:false});
  await env.button.listener();

  assert.equal(env.state.openCount,0);
  assert.equal(env.result.dataset.status,"block");
  assert.match(env.list.children.map(x=>x.textContent).join("\n"),/No existe preparación local/);
});
test("missing enumeration API is explicitly inconclusive and never creates data",async()=>{
  const env=testRuntime({noEnumeration:true});
  await env.button.listener();

  assert.equal(env.state.openCount,0);
  assert.equal(env.result.dataset.status,"warn");
  assert.match(env.list.children.map(x=>x.textContent).join("\n"),/no permite inventariar bases/);
});
