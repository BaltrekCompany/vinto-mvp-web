import assert from "node:assert/strict";
import { test } from "node:test";
import { createOperationalSyncRuntime, openVerifiedOperationalPayload } from "../lib/vinto/offline-operational-sync-runtime.ts";
const OWNER="11111111-1111-4111-8111-111111111111";
const DEVICE="33333333-3333-4333-8333-333333333333";
const CAPTURE="55555555-5555-4555-8555-555555555555";
const FORM="VINTO-P1-22";
const SCOPE="66666666-6666-4666-8666-666666666666";
const SHA="a".repeat(64), SEAL={format:"aes-gcm-v1",iv:"cipher-iv",ciphertext:"ciphertext"};
const identity={ownerId:OWNER,deviceKey:DEVICE};
const record={capture_id:CAPTURE,ownerId:OWNER,deviceKey:DEVICE,seq:1,
 dependsOn:null,formCode:FORM,formVersion:1,contextVersion:SCOPE,
 machineCode:"MP1",scopeSnapshotId:SCOPE,payloadSha256:SHA,
 state:"queued",attempts:0,nextAttemptAt:null,uncertain:false,lease:null,
 version:1,lastError:null,serverRef:null,warnings:[],createdAt:"2026-11-20T00:00:00Z",updatedAt:"2026-11-20T00:00:00Z",
 sealed:SEAL};
const pending={capture_id:CAPTURE,sourceDraftId:"44444444-4444-4444-8444-444444444444",
 sourceRevision:1,ownerId:OWNER,deviceKey:DEVICE,payloadSha256:SHA,synthetic:false,
 sealed:SEAL,createdAt:"2026-11-20T00:00:00Z"};
test("orphan queue cannot decrypt or send",async()=>{
 const store={listPending:async()=>[]};
 await assert.rejects(openVerifiedOperationalPayload(store,identity,{},record),/MISSING_PENDING/);
});
test("a synthetic or altered pending cannot enter the operational sender",async()=>{
 for(const bad of [{...pending,synthetic:true},{...pending,payloadSha256:"b".repeat(64)},{...pending,sealed:{...SEAL,ciphertext:"altered"}},{...pending,ownerId:DEVICE}]) {
  await assert.rejects(openVerifiedOperationalPayload({listPending:async()=>[bad]},identity,{},record),/MISMATCH/);
 }
});
test("another owner or missing capture scope cannot upload",async()=>{
 await assert.rejects(openVerifiedOperationalPayload({listPending:async()=>[pending]},
  {ownerId:DEVICE,deviceKey:DEVICE},{},record),/OWNER/);
 await assert.rejects(openVerifiedOperationalPayload({listPending:async()=>[pending]},
  identity,{}, {...record,scopeSnapshotId:undefined}),/SCOPE/);
});
test("runtime is opt-in and never sends while offline or locked",async()=>{
 let online=false, unlocked=false, sends=0, timerSeq=0;
 const subscriptions=new Map(),timers=new Map();
 const store={listPending:async()=>[pending],sync:{
  list:async()=>[record],get:async()=>record,claim:async()=>null,finalize:async()=>false}};
 const runtime=createOperationalSyncRuntime({
  store, identity, tabId:"tab-one", online:()=>online,
  unlockedKey:()=>unlocked?{}:null,onlineSession:async()=>({userId:OWNER}),
  transport:{send:async()=>{sends++;return {status:201,body:{}};},lookup:async()=>({found:false})},
  subscribe:(event,listener)=>{subscriptions.set(event,listener);return()=>subscriptions.delete(event);},
  setTimer:(fn,ms)=>{const id=++timerSeq;timers.set(id,fn);return id;},
  clearTimer:id=>timers.delete(id),
 });
 runtime.start();
 assert.equal(timers.size,0);
 online=true;subscriptions.get("online")();
 assert.equal(timers.size,0);
 unlocked=true;runtime.notifyReady();
 assert.equal(timers.size,1);
 runtime.stop();
 assert.equal(timers.size,0);
 assert.equal(sends,0);
});
test("runtime cannot call sync when offline",async()=>{
 const runtime=createOperationalSyncRuntime({
  store:{sync:{}}, identity,tabId:"tab-two",
  online:()=>false,unlockedKey:()=>null,onlineSession:async()=>null,
  transport:{},subscribe:()=>()=>{},setTimer:()=>1,clearTimer:()=>{},
 });
 await assert.rejects(runtime.syncOnce(),/offline/);
});
