import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";
import ts from "typescript";
const read=(path)=>readFileSync(new URL("../"+path,import.meta.url),"utf8");
const source=read("lib/vinto/quality-offline-navigation.ts");
const transpiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const exports={};
runInNewContext(transpiled,{exports,Map,Set});
const {groupOfflinePreparedForms,offlineFormTitle}=exports;
const bobbin=(id,code,machine,ot)=>({
 bobbin:{id,code,machine:{code:machine,name:machine}},
 production:{work_order:{number:ot},line:{line_code:"L1"}},
 quality:{status:"pending"}
});
const rows=[
 {id:"a",formCode:"VINTO-P1-20",machineCode:"MP3",bobbin:bobbin("b5","5","MP3","OT-2026-0019"),data:{draftId:"a"}},
 {id:"b",formCode:"VINTO-P1-24",machineCode:"MP3",bobbin:bobbin("b5","5","MP3","OT-2026-0019"),data:{draftId:"b"}},
 {id:"c",formCode:"VINTO-P1-20",machineCode:"MP1",bobbin:bobbin("b2","2","MP1","OT-2026-0035"),data:{draftId:"c"}},
 {id:"d",formCode:"VINTO-P1-26",machineCode:"MP1",bobbin:null,data:{draftId:"d"}},
];
test("prepared forms group by original bobbin identity, never by identical code alone",()=>{
 const groups=groupOfflinePreparedForms(rows);
 assert.equal(groups.length,3);
 const five=groups.find(g=>g.key==="bobbin|MP3|b5");
 assert.equal(five.title,"Bobina 5 · MP3");
 assert.match(five.subtitle,/OT-2026-0019/);
 assert.deepEqual(Array.from(five.items,x=>x.id),["a","b"]);
 assert.equal(groups.find(g=>g.key==="bobbin|MP1|b2").items[0].id,"c");
});
test("machine forms clearly say no bobbin and preserve draft identity",()=>{
 const groups=groupOfflinePreparedForms(rows);
 const machine=groups.find(g=>g.key==="machine|MP1");
 assert.equal(machine.items[0].id,"d");
 assert.match(machine.subtitle,/sin bobina ni OT/);
});
test("offline fallback is a human name and catalog takes precedence",()=>{
 assert.equal(offlineFormTitle("VINTO-P1-20","MP3",[]),"Propiedades físicas de bobina");
 assert.equal(offlineFormTitle("VINTO-P1-26","MP1",[]),"Medición de secos");
 assert.equal(offlineFormTitle("VINTO-P1-20","MP3",[{machineCode:"MP3",formCode:"VINTO-P1-20",name:"Título publicado"}]),"Título publicado");
});
test("new view opens the existing encrypted draft without changing storage or sync",()=>{
 const ui=read("components/vinto/quality-offline-workspace.tsx");
 assert.match(ui,/groupOfflinePreparedForms/);
 assert.match(ui,/onClick=\{\(\)=>setActiveId\(p.id\)\}/);
 assert.match(ui,/createOperationalSyncRuntime/);
 assert.match(ui,/createOperationalCaptureBindings/);
 assert.match(ui,/QualityHumidityCapture/);
 assert.match(ui,/QualityPhysicalCapture/);
});

test("two COPASA mothers with identical label remain distinguishable and correctly ordered",()=>{
 const a={id:"m1",formCode:"VINTO-P1-24",machineCode:"COPASA",
  bobbin:bobbin("4980cfeb-4484-462d-b036-10a200b21dff","25","COPASA","OT-2026-0049"),data:{}};
 const b={id:"m2",formCode:"VINTO-P1-24",machineCode:"COPASA",
  bobbin:bobbin("a4a1639c-60d5-4f3a-aca2-6dba0358673d","25","COPASA","OT-2026-0049"),data:{}};
 const groups=groupOfflinePreparedForms([a,b]);
 assert.equal(groups.length,2);
 assert.match(groups[0].title,/ID [a-f0-9]{8}$/);
 assert.notEqual(groups[0].title,groups[1].title);
 assert.equal(new Set(groups.map(g=>g.key)).size,2);
});
test("ordinary numbered bobbins sort numerically instead of lexically",()=>{
 const items=["1","10","2"].map(n=>({
  id:n,formCode:"VINTO-P1-24",machineCode:"MP1",
  bobbin:bobbin("bobbin-"+n,n,"MP1","OT"),data:{}
 }));
 const groups=groupOfflinePreparedForms(items);
 assert.equal(groups.map(x=>x.title).join(" | "),"Bobina 1 · MP1 | Bobina 2 · MP1 | Bobina 10 · MP1");
});
