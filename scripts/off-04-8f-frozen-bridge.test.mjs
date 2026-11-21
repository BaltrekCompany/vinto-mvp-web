import assert from "node:assert/strict";
import { test } from "node:test";
import { bridgeOperationalPendings } from "../lib/vinto/offline-frozen-queue-bridge.ts";
const ID={ownerId:"a1",deviceKey:"d1"};
const row=(captureId, patch={})=>({captureId,ownerId:ID.ownerId,deviceKey:ID.deviceKey,synthetic:false,...patch});
function fixture(list) {
 let identity=ID;const sent=[],quarantined=[];
 const deps={
  unlockedIdentity:()=>identity,
  list:async()=>list,
  enqueue:async r=>{ if(r.captureId==="bad-storage")throw Error("quota");sent.push(r.captureId); },
  onQuarantine:(captureId,reason)=>quarantined.push([captureId,reason])
 };
 return {deps,sent,quarantined,lock:()=>identity=null,swap:()=>identity={ownerId:"other",deviceKey:"d1"}};
}
test("reconnect automatically bridges valid frozen captures without changing their ID",async()=>{
 const f=fixture([row("CAP-1"),row("CAP-2")]);
 assert.deepEqual(await bridgeOperationalPendings(f.deps),{queuedOrExisting:2,quarantined:0,deferred:false});
 assert.deepEqual(f.sent,["CAP-1","CAP-2"]);
});
test("one invalid record does not block valid records; synthetic lab receipt is rejected",async()=>{
 const f=fixture([row("CAP-1"),row("LAB",{synthetic:true}),row("OTHER",{ownerId:"other"}),row("bad-storage"),row("CAP-2")]);
 const r=await bridgeOperationalPendings(f.deps);
 assert.deepEqual(r,{queuedOrExisting:2,quarantined:3,deferred:false});
 assert.deepEqual(f.sent,["CAP-1","CAP-2"]);
 assert.deepEqual(f.quarantined.map(x=>x[1]),["invalid_kind","identity_mismatch","storage"]);
});
test("duplicate pending references cannot enqueue the same capture twice in one pass",async()=>{
 const f=fixture([row("CAP-1"),row("CAP-1"),row("CAP-2")]);
 assert.equal((await bridgeOperationalPendings(f.deps)).queuedOrExisting,2);
 assert.deepEqual(f.sent,["CAP-1","CAP-2"]);
});
test("locked identity never enumerates pendings or enqueues",async()=>{
 const f=fixture([row("CAP-1")]);f.lock();
 const r=await bridgeOperationalPendings({...f.deps,list:async()=>{throw Error("must not list");}});
 assert.deepEqual(r,{queuedOrExisting:0,quarantined:0,deferred:true});
});
test("account switch during bridge halts remaining work",async()=>{
 const f=fixture([row("CAP-1"),row("CAP-2")]);
 let called=0;
 const deps={...f.deps,enqueue:async row=>{f.sent.push(row.captureId);called++;if(called===1)f.swap();}};
 assert.deepEqual(await bridgeOperationalPendings(deps),{queuedOrExisting:1,quarantined:0,deferred:true});
 assert.deepEqual(f.sent,["CAP-1"]);
});
