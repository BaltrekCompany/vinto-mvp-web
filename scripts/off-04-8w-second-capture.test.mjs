// OFF-04.8 v6.1 (Issue #249): second capture of a session + visible state after an automatic sync.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {createOperationalSyncRuntime} from "../lib/vinto/offline-operational-sync-runtime.ts";
import {createOfflineCaptureEditorWorkflow} from "../lib/vinto/offline-capture-editor-workflow.ts";
const page=readFileSync(new URL("../lib/vinto/offline-operational-mobile-page.ts",import.meta.url),"utf8");
const OWNER="11111111-1111-4111-8111-111111111111",DEVICE="33333333-3333-4333-8333-333333333333";
const identity={ownerId:OWNER,deviceKey:DEVICE};

function runtime(extra={}){
 const store={listPending:async()=>[],sync:{list:async()=>[],get:async()=>null,claim:async()=>null,finalize:async()=>false}};
 return createOperationalSyncRuntime({store,identity,tabId:"t",online:()=>true,unlockedKey:()=>({}),onlineSession:async()=>({userId:OWNER}),
  transport:{send:async()=>({status:201,body:{}}),lookup:async()=>({found:false})},subscribe:()=>()=>{},setTimer:()=>1,clearTimer:()=>{},...extra});
}
test("onRunComplete runs after every completed pass (manual or automatic) with the result, and is purely presentational",async()=>{
 const seen=[];const rt=runtime({onRunComplete:r=>seen.push(r)});
 const a=await rt.syncOnce(),b=await rt.syncOnce();
 assert.equal(seen.length,2);assert.equal(seen[0],a);assert.equal(seen[1],b);
 assert.ok("counts" in a&&"outcomes" in a);
});
test("an exception inside the hook never changes the outcome of the pass",async()=>{
 const rt=runtime({onRunComplete:()=>{throw Error("ui exploded");}});
 const r=await rt.syncOnce();assert.ok(r&&"counts" in r);
});
test("the hook is NOT called when the pass cannot run (offline or locked): no stale redraw",async()=>{
 let calls=0;
 await assert.rejects(runtime({online:()=>false,onRunComplete:()=>{calls++;}}).syncOnce(),/offline/);
 await assert.rejects(runtime({unlockedKey:()=>null,onRunComplete:()=>{calls++;}}).syncOnce(),/vault_locked/);
 assert.equal(calls,0);
});
function wf(){
 let locked=false,revision=null;const events=[];
 const flow=createOfflineCaptureEditorWorkflow({
  unlocked:()=>true,current:()=>({draftId:"d",ownerId:"o",revision,values:{a:"1"}}),
  async persistDraft(s){return {revision:(revision??0)+1};},async freezeDraft(){return {captureId:"c",created:true};},async enqueueFrozen(){},
  notifySync(){events.push("wake");},setEditorLocked(on){locked=on;events.push("lock:"+on);},setTimer:()=>1,clearTimer:()=>{},onDraftSaved(r){revision=r;},
 });
 return {flow,events,get locked(){return locked;}};
}
test("a CONFIRMED editor stays locked and immutable; a NEW workflow instance is independent (the page, not the workflow, owns the shared button)",async()=>{
 const a=wf();a.flow.onFieldEdited();const r=await a.flow.onGuardarCaptura();
 assert.equal(r.status,"queued");assert.equal(a.locked,true);
 assert.deepEqual((await a.flow.onGuardarCaptura()).status,"blocked");            // no second submission of the same editor
 assert.equal(a.locked,true);
 const b=wf();b.flow.onFieldEdited();assert.equal(b.locked,false);                                    // a fresh editor starts unlocked
 assert.equal((await b.flow.onGuardarCaptura()).status,"queued");                 // and can be saved on its own
});
test("a blocked (not queued) confirmation unlocks again so the operator can retry",async()=>{
 let locked=false;
 const flow=createOfflineCaptureEditorWorkflow({
  unlocked:()=>true,current:()=>({draftId:"d",ownerId:"o",revision:null,values:{}}),async persistDraft(){throw Error("storage");},
  async freezeDraft(){return {captureId:"c",created:true};},async enqueueFrozen(){},notifySync(){},setEditorLocked(on){locked=on;},setTimer:()=>1,clearTimer:()=>{},onDraftSaved(){},
 });
 const r=await flow.onGuardarCaptura();assert.notEqual(r.status,"queued");assert.equal(locked,false);
});
test("page wiring: a new editor enables ITS Save button only after being built; the confirmed editor is never unlocked; the list redraws after each pass",()=>{
 const ce=page.slice(page.indexOf("async function createEditor("),page.indexOf("async function openExisting("));
 assert.match(ce,/activeEditor=await createOperationalQualityEditor\(/);
 const iBuilt=ce.indexOf("activeEditor=await createOperationalQualityEditor("),iEnable=ce.indexOf('el<HTMLButtonElement>("capture-save").disabled=false'),iShow=ce.indexOf('show("editor",true)');
 assert.ok(iBuilt>0&&iEnable>iBuilt&&iShow>iEnable,"enable after the editor exists and before it is shown");
 // the ONLY places that touch the button
 assert.equal((page.match(/capture-save"\)\.disabled=/g)||[]).length,2);
 assert.match(page,/setEditorLocked:locked=>\{\s*el<HTMLButtonElement>\("capture-save"\)\.disabled=locked;/);
 const submit=page.slice(page.indexOf('el<HTMLFormElement>("capture").addEventListener("submit"'),page.indexOf('el("back").addEventListener'));
 assert.doesNotMatch(submit,/disabled=false/);assert.match(submit,/activeEditor=null/);
 assert.match(page,/onRunComplete:result=>\{[\s\S]*?refreshDrafts\(\)\.catch/);
 assert.doesNotMatch(page,/deleteDatabase|\.clear\(\)|localStorage\.clear/);
});
