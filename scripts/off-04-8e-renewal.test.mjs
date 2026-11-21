import assert from "node:assert/strict";
import { test } from "node:test";
import { createCaptureScopeRenewal } from "../lib/vinto/offline-capture-renewal.ts";
const H = 3600000;
const flush = async () => { for (let i=0;i<12;i++) await Promise.resolve(); };
function fixture() {
  let online = false, unlocked = true, owner = true, expiry = Date.now() + 24*H;
  let count = 0;
  const timers = new Map(), subscriptions = new Map();
  let counter = 0;
  const controller = createCaptureScopeRenewal({
    online: () => online, unlocked: () => unlocked,
    authenticatedOriginalOwner: async () => owner,
    verifiedExpiryMs: () => expiry,
    async renew() { count++; expiry = Date.now()+24*H; },
    setTimer(fn, delay) { const id=++counter; timers.set(id,{fn,delay}); return id; },
    clearTimer(id) { timers.delete(id); },
    subscribe(e,fn) { const a=subscriptions.get(e)||new Set(); a.add(fn);subscriptions.set(e,a);return ()=>a.delete(fn); },
  });
  return {controller,timers, get count() {return count;},
    connect(){ online=true; for(const fn of subscriptions.get("online")||[])fn(); },
    disconnect(){online=false;}, lock(){unlocked=false;}, unlock(){unlocked=true;controller.notifyAuthenticated();},
    otherUser(){owner=false;}, restoreUser(){owner=true;controller.notifyAuthenticated();},
    nearExpiry(){expiry=Date.now()+9*H;}, expiring(){expiry=Date.now()-H;},
    async fire(){ const next=timers.entries().next().value;if(next){timers.delete(next[0]);next[1].fn();await flush();}}
  };
}
test("no mandatory button; valid scope renews automatically when reconnection occurs",async()=>{
  const f=fixture(); f.nearExpiry();f.controller.start();assert.equal(f.count,0);
  f.connect();await f.fire();assert.equal(f.count,1);f.controller.stop();
});
test("no renewal while vault locked, offline or another user is authenticated",async()=>{
  const f=fixture();f.nearExpiry();f.lock();f.controller.start();f.connect();assert.equal(f.timers.size,0);
  f.unlock();f.otherUser();await f.fire();assert.equal(f.count,0);
  f.restoreUser();await f.fire();assert.equal(f.count,1);f.controller.stop();
});
test("healthy 24h authorization avoids unnecessary renewal",async()=>{
  const f=fixture();f.controller.start();f.connect();await f.fire();assert.equal(f.count,0);f.controller.stop();
});
test("stop disables renewal without deleting existing snapshots",async()=>{
  const f=fixture();f.nearExpiry();f.controller.start();f.connect();f.controller.stop();await f.fire();assert.equal(f.count,0);
});
