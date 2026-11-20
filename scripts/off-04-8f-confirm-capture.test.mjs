import assert from "node:assert/strict";
import { test } from "node:test";
import { createCaptureConfirmer } from "../lib/vinto/offline-confirm-capture.ts";
const settle = async () => { for (let i=0;i<8;i++) await Promise.resolve(); };
const good = (extra = {}) => {
  const log = [], make = createCaptureConfirmer({
    async flushDraft() { log.push("flush"); return {ok:true,revision:3}; },
    async freeze(revision) { log.push("freeze:"+revision); return {captureId:"c1",created:true}; },
    async enqueueFrozen(id) { log.push("enqueue:"+id); },
    notifySync() { log.push("notify"); },
    ...extra,
  });
  return { log, make };
};
test("one Save Capture click confirms, freezes, enqueues, and wakes sync without a second button", async () => {
  const f=good();
  const r=await f.make.confirm();
  assert.deepEqual(r,{status:"queued",captureId:"c1",created:true});
  assert.deepEqual(f.log,["flush","freeze:3","enqueue:c1","notify"]);
});
test("double click in same tab has one durable operation", async () => {
  let resolve; const promise = new Promise(r => {resolve=r;});
  const f=good({async freeze(n){f.log.push("freeze:"+n); await promise;return {captureId:"c1",created:true};}});
  const a=f.make.confirm(), b=f.make.confirm();
  assert.equal(a,b);
  await settle();resolve();
  assert.deepEqual(await a,{status:"queued",captureId:"c1",created:true});
  assert.equal(f.log.filter(x=>x.startsWith("freeze")).length,1);
});
test("autosave not durable blocks confirmation without freezing anything",async()=>{
  const f=good({async flushDraft(){return {ok:false,reason:"conflict"};}});
  assert.deepEqual(await f.make.confirm(),{status:"blocked",reason:"conflict"});
  assert.deepEqual(f.log,[]);
});
test("incomplete new draft stays editable without sending",async()=>{
  const f=good({async flushDraft(){return {ok:true,revision:null};}});
  assert.deepEqual(await f.make.confirm(),{status:"blocked",reason:"incomplete"});
  assert.deepEqual(f.log,[]);
});
test("freeze uses exact persisted revision and rejects a stale revision without enqueue",async()=>{
  const f=good({async freeze(){throw Error("conflict");}});
  assert.deepEqual(await f.make.confirm(),{status:"blocked",reason:"conflict"});
  assert.deepEqual(f.log,["flush"]);
});
test("queue storage failure preserves the frozen pending for retry",async()=>{
  const f=good({async enqueueFrozen(){throw Error("offline indexeddb busy");}});
  assert.deepEqual(await f.make.confirm(),{status:"blocked",reason:"storage"});
  assert.deepEqual(f.log,["flush","freeze:3"]);
});
test("sync notification failure leaves queued result successful for next reconnect",async()=>{
  const f=good({notifySync(){throw Error("navigator not ready");}});
  assert.deepEqual(await f.make.confirm(),{status:"queued",captureId:"c1",created:true});
  assert.deepEqual(f.log,["flush","freeze:3","enqueue:c1"]);
});
