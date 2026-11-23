import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {createOperationalQualityExperience} from "../lib/vinto/offline-operational-quality-experience.ts";

const cryptoApi=globalThis.crypto??webcrypto;
Object.defineProperty(globalThis,"crypto",{value:cryptoApi,configurable:true});
const OWNER="11111111-1111-4111-8111-111111111111";
const DEVICE="33333333-3333-4333-8333-333333333333";
const DRAFT="44444444-4444-4444-8444-444444444444";
const SCOPE="66666666-6666-4666-8666-666666666666";

test("Quality capture composition is opt-in; encrypted save queues without sending while offline",async()=>{
 const key=await cryptoApi.subtle.generateKey({name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
 let draftRow=null,queue=null,rev=null,locked=false,online=false,fetchCount=0;
 let timerSeq=0; const timers=new Map(),listeners=new Map();
 const store={
  getDraft:async()=>draftRow,
  saveDraft:async(row)=>{draftRow=row;},
  confirm:async(expected,cipher,pending,q)=>{queue=q;return {captureId:pending.capture_id,created:true};},
  sync:{get:async()=>queue},
 };
 const definition={envelope:{payload:{form_code:"VINTO-P1-22",form_version:1,machine_code:"MP1",
  definition:{form_code:"VINTO-P1-22",form_version:1,
   fields:[{key:"medida",source:"manual",value_type:"decimal",required:true,options:[],display_order:1}]}}}};
 const experience=await createOperationalQualityExperience({
  editor:{
   key,identity:{ownerId:OWNER,deviceKey:DEVICE},store,definition,
   form:{draftId:DRAFT,machineCode:"MP1",formCode:"VINTO-P1-22",formVersion:1,captureScopeSnapshotId:SCOPE},
   assertCaptureScope:async()=>{},
   ui:{
    current:()=>({draftId:DRAFT,ownerId:OWNER,revision:rev,values:{medida:"2.50"}}),
    unlocked:()=>true,setEditorLocked:v=>{locked=v;},
    setTimer:()=>1,clearTimer:()=>{},onDraftSaved:v=>{rev=v;},
   },
  },
  http:{origin:"https://qa.example.test/",fetcher:async()=>{fetchCount++;throw Error("unexpected call");}},
  sync:{
   tabId:"test",unlockedKey:()=>key,online:()=>online,
   onlineSession:async()=>({userId:OWNER}),
   subscribe:(ev,cb)=>{listeners.set(ev,cb);return()=>listeners.delete(ev);},
   setTimer:(cb,ms)=>{const id=++timerSeq;timers.set(id,cb);return id;},
   clearTimer:id=>timers.delete(id),
  },
 });
 assert.equal(fetchCount,0);
 assert.equal(timers.size,0);
 experience.start();
 assert.equal(timers.size,0);
 experience.editor.onFieldEdited();
 const saved=await experience.editor.onGuardarCaptura();
 assert.equal(saved.status,"queued");
 assert.equal(locked,true);
 assert.equal(queue.state,"queued");
 assert.equal(fetchCount,0);
 online=true;
 experience.notifySessionRestored();
 assert.equal(timers.size,1);
 experience.stop();
 assert.equal(timers.size,0);
 assert.equal(listeners.size,0);
 assert.equal(fetchCount,0);
});
