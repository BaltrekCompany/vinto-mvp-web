import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {createOperationalCaptureBindings} from "../lib/vinto/offline-operational-capture-bindings.ts";
import {createOperationalCaptureEditor} from "../lib/vinto/offline-operational-editor-integration.ts";
import {operationalCaptureId} from "../lib/vinto/offline-operational-id.ts";
import {decideOperationalFreeze,nextOperationalDraft} from "../lib/vinto/offline-operational-model.ts";
import {openLocalDraft} from "../lib/vinto/offline-vault.ts";
const cryptoApi=globalThis.crypto??webcrypto;
Object.defineProperty(globalThis,"crypto",{value:cryptoApi,configurable:true});
const ownerId="11111111-1111-4111-8111-111111111111",
 deviceKey="33333333-3333-4333-8333-333333333333",
 draftId="44444444-4444-4444-8444-444444444444",
 scopeSnapshotId="66666666-6666-4666-8666-666666666666";
const identity={ownerId,deviceKey};
const context={draftId,scopeSnapshotId,contextVersion:scopeSnapshotId,
 machineCode:"MP1",formCode:"VINTO-P1-22",formVersion:2};
async function fixture(){
 const key=await cryptoApi.subtle.generateKey({name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
 let draft, pending, queue, active=true;
 const store={
  sync:{async get(id){return queue?.capture_id===id?queue:null;}},
  async getDraft(id){return id===draftId?(draft??null):null;},
  async saveDraft(row,expected){draft=nextOperationalDraft(draft,row,expected);},
  async confirm(revision,cipher,p,q){
   const result=decideOperationalFreeze(draft,pending,queue,revision,cipher,p,q);
   draft=result.draft;pending=result.pending;queue=result.queue;
   return {created:result.created,captureId:result.pending.capture_id};
  }
 };
 const bindings=createOperationalCaptureBindings({
  key,identity,context,store,now:()=>Date.UTC(2026,10,20,10),
  async assertCaptureScope(){if(!active)throw Error("capture_scope_missing");},
  validateComplete(v){if(!v.medida)throw Error("incomplete");},
 });
 return {bindings,store,key,context,identity, revoke(){active=false;}, get draft(){return draft;},
  get pending(){return pending;},get queue(){return queue;}};
}
test("two autosaves persist exact last revision without sending",async()=>{
 const f=await fixture();
 await f.bindings.persist({draftId,ownerId,revision:null,values:{medida:"12.1"}});
 const r=await f.bindings.persist({draftId,ownerId,revision:1,values:{medida:"12.2"}});
 assert.equal(r.revision,2);
 assert.deepEqual(await f.bindings.resume(),{revision:2,frozen:false,values:{medida:"12.2"}});
 assert.equal(f.pending,undefined);
});
test("one Save Capture atomically freezes exactly the latest edited values, no duplicates",async()=>{
 const f=await fixture();
 await f.bindings.persist({draftId,ownerId,revision:null,values:{medida:"12.1"}});
 await f.bindings.persist({draftId,ownerId,revision:1,values:{medida:"12.2"}});
 const result=await f.bindings.freeze(2);
 assert.equal(result.created,true);
 assert.equal(result.captureId,await operationalCaptureId(ownerId,deviceKey,draftId));
 assert.equal(f.pending.capture_id,f.queue.capture_id);
 assert.equal(f.draft.frozenBy,result.captureId);
 const opened=await openLocalDraft(f.key,{...identity,id:result.captureId,
  contextId:scopeSnapshotId,formCode:context.formCode,formVersion:context.formVersion},f.queue.sealed);
 assert.deepEqual(opened,{synthetic:false,payload:{medida:"12.2"}});
 const again=await f.bindings.freeze(2);
 assert.equal(again.created,false);
 assert.equal(f.queue.capture_id,result.captureId);
 await assert.rejects(f.bindings.persist({draftId,ownerId,revision:2,values:{medida:"changed"}}),/FROZEN/);
});
test("incomplete or stale draft cannot become a pending",async()=>{
 const f=await fixture();
 await f.bindings.persist({draftId,ownerId,revision:null,values:{}});
 await assert.rejects(f.bindings.freeze(1),/incomplete/);
 assert.equal(f.pending,undefined);
 await assert.rejects(f.bindings.freeze(2),/CONFLICT/);
 assert.equal(f.pending,undefined);
});
test("expired capture scope preserves autosave but blocks operational freeze",async()=>{
 const f=await fixture();
 await f.bindings.persist({draftId,ownerId,revision:null,values:{medida:"12.3"}});
 f.revoke();
 await f.bindings.persist({draftId,ownerId,revision:1,values:{medida:"12.4"}});
 await assert.rejects(f.bindings.freeze(2),/capture_scope_missing/);
 assert.equal(f.pending,undefined);
 assert.deepEqual((await f.bindings.resume()).values,{medida:"12.4"});
});
test("wrong owner and stale CAS are not silently accepted",async()=>{
 const f=await fixture();
 await assert.rejects(f.bindings.persist({draftId,ownerId:deviceKey,revision:null,values:{medida:"10"}}),/CONFLICT/);
 await f.bindings.persist({draftId,ownerId,revision:null,values:{medida:"10"}});
 await assert.rejects(f.bindings.persist({draftId,ownerId,revision:null,values:{medida:"11"}}),/CONFLICT/);
});
test("operational ID uses a different domain than synthetic QA and is stable",async()=>{
 const id=await operationalCaptureId(ownerId,deviceKey,draftId);
 assert.equal(id,await operationalCaptureId(ownerId,deviceKey,draftId));
 assert.match(id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

test("one-click editor adapter atomically queues real encrypted values without bridge button",async()=>{
 const f=await fixture();
 let revision=null,locked=false;
 let values={medida:"21.4"};
 const history=[];
 const editor=createOperationalCaptureEditor({
   key:f.key,store:f.store,context:f.context,identity:f.identity,
   now:()=>Date.UTC(2026,10,20,10),
   assertCaptureScope:async()=>{},
   validateComplete:v=>{if(!v.medida)throw Error("incomplete");},
 },{
   current:()=>({draftId,ownerId,revision,values}),
   unlocked:()=>true,
   setEditorLocked:v=>{locked=v;},
   setTimer:()=>1,clearTimer:()=>{},
   onDraftSaved:r=>{revision=r;},
   notifySync:()=>history.push("wake"),
 });
 editor.onFieldEdited();
 const first=await editor.onGuardarCaptura();
 assert.equal(first.status,"queued");
 assert.equal(locked,true);
 assert.equal(f.pending.capture_id,f.queue.capture_id);
 assert.deepEqual(history,["wake"]);
 const opened=await openLocalDraft(f.key,{...identity,id:first.captureId,
  contextId:scopeSnapshotId,formCode:context.formCode,formVersion:context.formVersion},f.queue.sealed);
 assert.deepEqual(opened,{synthetic:false,payload:{medida:"21.4"}});
});
