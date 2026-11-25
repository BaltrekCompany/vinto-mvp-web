import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";
import ts from "typescript";
const read=p=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const s=read("lib/vinto/quality-offline-single-control.ts");
const exports={};
runInNewContext(ts.transpileModule(s,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,Map,Set});
const {projectOfflineControls,isBobbinControlLocked}=exports;
const bob=(id,form="VINTO-P1-24")=>({id,formCode:form,machineCode:"MP1",bobbinId:"bobbin-2"});
const machine=id=>({id,formCode:"VINTO-P1-26",machineCode:"MP1",bobbinId:null});
const queue=(id,state)=>({capture_id:id,state});
const pending=(id,draft)=>({capture_id:id,sourceDraftId:draft});
test("one visible row for older duplicate bobbin drafts, showing completed when any upload succeeded",()=>{
 const out=projectOfflineControls([bob("draft1"),bob("draft2"),bob("draft3")],
  [pending("c1","draft1"),pending("c2","draft2")],
  [queue("c1","synced"),queue("c2","queued")]);
 assert.equal(out.length,1);
 assert.equal(out[0].status,"completed");
 assert.equal(out[0].duplicates,2);
 assert.equal(out[0].item.id,"draft1");
 assert.equal(isBobbinControlLocked(out,bob("fresh")),true);
});
test("pending and review are not falsely labelled as completed",()=>{
 const pendingControl=projectOfflineControls([bob("d1")],[pending("c1","d1")],[queue("c1","retry_wait")]);
 assert.equal(pendingControl[0].status,"pending");
 const review=projectOfflineControls([bob("d1")],[pending("c1","d1")],[queue("c1","requires_review")]);
 assert.equal(review[0].status,"review");
 assert.equal(projectOfflineControls([bob("d1")],[],[])[0].status,"editable");
});
test("different bobbins and forms remain distinct and machine drafts remain repeatable",()=>{
 const out=projectOfflineControls([bob("a"),bob("b","VINTO-P1-20"),
  {...bob("c"),bobbinId:"bobbin-5"},machine("m1"),machine("m2")],[],[]);
 assert.equal(out.length,5);
 assert.equal(isBobbinControlLocked(out,machine("m3")),false);
});
test("workspace reads atomic pending and queue, removes duplicated new-bobbin action",()=>{
 const ui=read("components/vinto/quality-offline-workspace.tsx");
 assert.match(ui,/store\.listPending/);
 assert.match(ui,/projectOfflineControls/);
 assert.match(ui,/Formulario realizado/);
 assert.match(ui,/Pendiente de sincronización/);
 assert.match(ui,/!current\.bobbin&&/);
 assert.match(ui,/if\(reuse\.bobbin\)/);
 assert.match(ui,/setActiveId\(matched\.item\.id\)/);
 assert.match(ui,/createOperationalSyncRuntime/);
});
