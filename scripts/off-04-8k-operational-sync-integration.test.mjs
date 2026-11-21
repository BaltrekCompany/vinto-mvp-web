import assert from "node:assert/strict";
import { test } from "node:test";
import { webcrypto } from "node:crypto";
import { sealLocalDraft } from "../lib/vinto/offline-vault.ts";
import { payloadHash } from "../lib/vinto/offline-sync-engine.ts";
import { applyClaim, applyFinalize } from "../lib/vinto/offline-sync-rules.ts";
import { createOperationalSyncRuntime } from "../lib/vinto/offline-operational-sync-runtime.ts";

const cryptoApi=globalThis.crypto ?? webcrypto;
Object.defineProperty(globalThis,"crypto",{value:cryptoApi,configurable:true});
const OWNER="11111111-1111-4111-8111-111111111111",DEVICE="33333333-3333-4333-8333-333333333333";
const CAPTURE="55555555-5555-4555-8555-555555555555",SCOPE="66666666-6666-4666-8666-666666666666";
const identity={ownerId:OWNER,deviceKey:DEVICE};
async function build(transport,serverUser=OWNER){
 const key=await cryptoApi.subtle.generateKey({name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
 const content={synthetic:false,payload:{temperatura:"42.5",numero_de_cuba:"CUBA-01"}};
 const sealed=await sealLocalDraft(key,{...identity,id:CAPTURE,contextId:SCOPE,formCode:"VINTO-P1-22",formVersion:1},content);
 const sha=await payloadHash(content);
 let current={capture_id:CAPTURE,...identity,seq:1,dependsOn:null,formCode:"VINTO-P1-22",
  formVersion:1,machineCode:"MP1",scopeSnapshotId:SCOPE,contextVersion:SCOPE,
  payloadSha256:sha,state:"queued",attempts:0,nextAttemptAt:null,uncertain:false,lease:null,
  version:1,lastError:null,serverRef:null,warnings:[],sealed,
  createdAt:"2026-11-20T10:00:00Z",updatedAt:"2026-11-20T10:00:00Z"};
 let requests=0;
 const fullTransport={
  async send(request){requests++;return transport(request);},
  async lookup(){return {found:false};},
 };
 const store={
  listPending:async()=>[{capture_id:CAPTURE,sourceDraftId:"44444444-4444-4444-8444-444444444444",
   sourceRevision:1,ownerId:OWNER,deviceKey:DEVICE,payloadSha256:sha,synthetic:false,sealed,createdAt:"2026-11-20T10:00:00Z"}],
  sync:{
   async list(owner,device){return owner===OWNER&&device===DEVICE?[current]:[];},
   async get(id){return id===CAPTURE?current:null;},
   async claim(id,tab,now,leaseMs){
    if(id!==CAPTURE)return null;
    const next=applyClaim(current,tab,now,leaseMs);
    if(next)current=next.record;
    return next;
   },
   async finalize(id,tab,patch,now){
    const next=id===CAPTURE?applyFinalize(current,tab,patch,now):null;
    if(!next)return false;
    current=next;return true;
   },
  },
 };
 const runtime=createOperationalSyncRuntime({
  store,identity,online:()=>true,unlockedKey:()=>key,
  onlineSession:async()=>({userId:serverUser}),transport:fullTransport,tabId:"tab-1",
  subscribe:()=>()=>{},setTimer:()=>1,clearTimer:()=>{},
 });
 return {runtime, get state(){return current.state;},get requests(){return requests;}};
}
test("full offline operational pass sends exact original values and requires matching server ACK",async()=>{
 const f=await build(async(request)=>{
  assert.equal(request.capture_id,CAPTURE);
  assert.equal(request.author_user_id,OWNER);
  assert.equal(request.payload.synthetic,false);
  assert.deepEqual(request.payload.payload,{temperatura:"42.5",numero_de_cuba:"CUBA-01"});
  return {status:201,body:{outcome:"created",server_id:"srv-1",
   operational_registered:true,operational_capture_id:CAPTURE}};
 });
 const r=await f.runtime.syncOnce();
 assert.equal(r.paused,null);
 assert.equal(f.state,"synced");
 assert.equal(f.requests,1);
});
test("technical-only server receipt never counts as operational registration",async()=>{
 const f=await build(async()=>({status:201,body:{outcome:"created",server_id:"srv-2"}}));
 await f.runtime.syncOnce();
 assert.equal(f.state,"requires_review");
 assert.equal(f.requests,1);
});
test("server ACK for a DIFFERENT capture cannot complete operational registration",async()=>{
 const f=await build(async()=>({status:201,body:{outcome:"created",server_id:"srv-3",
  operational_registered:true,operational_capture_id:"99999999-9999-4999-8999-999999999999"}}));
 await f.runtime.syncOnce();
 assert.equal(f.state,"requires_review");
});
test("an authenticated DIFFERENT user cannot send the saved capture",async()=>{
 const f=await build(async()=>{throw Error("must not send");},DEVICE);
 const result=await f.runtime.syncOnce();
 assert.equal(result.paused,"different_user");
 assert.equal(f.requests,0);
 assert.equal(f.state,"queued");
});
