import assert from "node:assert/strict";
import {test} from "node:test";
import {createOfflineCaptureEditorWorkflow} from "../lib/vinto/offline-capture-editor-workflow.ts";
const settle=async()=>{for(let n=0;n<12;n++)await Promise.resolve();};
function fixture() {
 let revision=null, value="first", locked=false, release;
 const gate=new Promise(done=>{release=done;});
 const events=[], timers=new Map();
 let seq=0, slow=false, persistCount=0;
 let flow;
 const deps={
   unlocked:()=>true,
   current:()=>({draftId:"draft-1",ownerId:"owner-1",revision,values:{test:value}}),
   async persistDraft(snapshot) {
     persistCount++;
     events.push("persist:"+snapshot.values.test);
     if(slow) await gate;
     if(snapshot.revision!==revision)throw Error("conflict");
     return {revision:(revision??0)+1};
   },
   async freezeDraft(r) {events.push("freeze:"+r);return {captureId:"cap-1",created:true};},
   async enqueueFrozen(id) {events.push("queue:"+id);},
   notifySync(){events.push("wake");},
   setEditorLocked(on){locked=on;events.push("lock:"+on);},
   setTimer(fn,ms){const id=++seq;timers.set(id,{fn,ms});return id;},
   clearTimer(id){timers.delete(id);},
   onDraftSaved(r){revision=r;},
 };
 flow=createOfflineCaptureEditorWorkflow(deps);
 return {flow,events,timers,get locked(){return locked;},get writes(){return persistCount;},
   type(v){if(locked)throw Error("editor locked");value=v;flow.onFieldEdited();},
   async tick(){const first=timers.entries().next().value;if(first){timers.delete(first[0]);first[1].fn();await settle();}},
   setSlow(){slow=true;},release(){slow=false;release();},
 };
}
test("typing saves after 1.5s idle, but never queues or submits",async()=>{
 const f=fixture();f.type("a");f.type("abc");
 assert.equal(f.timers.size,1);
 assert.equal([...f.timers.values()][0].ms,1500);
 await f.tick();
 assert.equal(f.writes,1);
 assert.deepEqual(f.events,["persist:abc"]);
});
test("Guardar captura locks editor, saves final revision, freezes and queues once",async()=>{
 const f=fixture();f.type("latest");
 const result=await f.flow.onGuardarCaptura();
 assert.deepEqual(result,{status:"queued",captureId:"cap-1",created:true});
 assert.deepEqual(f.events,["lock:true","persist:latest","freeze:1","queue:cap-1","wake"]);
 assert.equal(f.locked,true);
 assert.equal(f.flow.hasUnsavedChanges,false);
});
test("existing durable draft needs no new typing to confirm",async()=>{
 let locked=false;
 const events=[];
 const flow=createOfflineCaptureEditorWorkflow({
  unlocked:()=>true,current:()=>({draftId:"saved",ownerId:"owner",revision:5,values:{test:"persisted"}}),
  async persistDraft(){throw Error("should not persist unchanged draft");},
  async freezeDraft(r){events.push("freeze:"+r);return {captureId:"cap-saved",created:false};},
  async enqueueFrozen(id){events.push("queue:"+id);},
  notifySync(){events.push("wake");},setEditorLocked:b=>{locked=b;},
  setTimer:()=>1,clearTimer:()=>{},
 });
 assert.equal((await flow.onGuardarCaptura()).status,"queued");
 assert.equal(locked,true);
 assert.deepEqual(events,["freeze:5","queue:cap-saved","wake"]);
});
test("storage conflict keeps editor editable and does not enqueue",async()=>{
 const f=fixture();
 f.type("changed");f.setSlow();
 const pending=f.flow.onGuardarCaptura();
 assert.equal(f.locked,true);
 assert.throws(()=>f.type("late"),/editor locked/);
 f.release();
 await pending;
 assert.equal(f.events.filter(x=>x.startsWith("freeze:")).length,1);
});
