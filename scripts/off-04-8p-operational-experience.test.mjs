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

test("offline capture survives locked interval and syncs only with original author and operational ACK",async()=>{
 const {applyClaim,applyFinalize}=await import("../lib/vinto/offline-sync-rules.ts");
 const key=await cryptoApi.subtle.generateKey({name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
 const identity={ownerId:OWNER,deviceKey:DEVICE};
 let draftRow=null,pending=null,queue=null,revision=null,online=false,sessionUser=DEVICE,fetchCount=0;
 const store={
  getDraft:async()=>draftRow,
  saveDraft:async row=>{draftRow=row;},
  async confirm(expected,cipher,p,q){
   assert.equal(pending,null);
   pending=p;queue=q;
   return {captureId:p.capture_id,created:true};
  },
  listPending:async(owner,device)=>owner===OWNER&&device===DEVICE&&pending?[pending]:[],
  sync:{
   get:async id=>queue?.capture_id===id?queue:null,
   list:async(owner,device)=>owner===OWNER&&device===DEVICE&&queue?[queue]:[],
   claim:async(id,tab,now,leaseMs)=>{
    if(!queue||queue.capture_id!==id)return null;
    const next=applyClaim(queue,tab,now,leaseMs);
    if(next)queue=next.record;
    return next;
   },
   finalize:async(id,tab,patch,now)=>{
    if(queue?.capture_id!==id)return false;
    const next=applyFinalize(queue,tab,patch,now);
    if(!next)return false;
    queue=next;return true;
   },
  },
 };
 const experience=await createOperationalQualityExperience({
  editor:{
   key,identity,store,
   definition:{envelope:{payload:{form_code:"VINTO-P1-22",form_version:1,machine_code:"MP1",
     definition:{form_code:"VINTO-P1-22",form_version:1,
      fields:[{key:"medida",source:"manual",value_type:"decimal",required:true,options:[],display_order:1}]}}}},
   form:{draftId:DRAFT,machineCode:"MP1",formCode:"VINTO-P1-22",
      formVersion:1,captureScopeSnapshotId:SCOPE},
   assertCaptureScope:async()=>{},
   ui:{
    current:()=>({draftId:DRAFT,ownerId:OWNER,revision,values:{medida:"2.50"}}),
    unlocked:()=>true,setEditorLocked:()=>{},setTimer:()=>1,clearTimer:()=>{},
    onDraftSaved:v=>{revision=v;},
   },
  },
  http:{
   origin:"https://qa.example.test/",
   fetcher:async(url,options)=>{
    fetchCount++;
    assert.equal(options.credentials,"include");
    assert.equal(options.mode,"same-origin");
    assert.equal(options.redirect,"error");
    assert.equal(options.method,"POST");
    assert.equal(url,"https://qa.example.test/api/offline/captures");
    const body=JSON.parse(options.body);
    assert.equal(body.author_user_id,OWNER);
    assert.equal(body.capture_id,pending.capture_id);
    assert.equal(body.payload_sha256,pending.payloadSha256);
    assert.deepEqual(body.payload,{synthetic:false,payload:{medida:"2.50"}});
    return {status:201,headers:new Headers({"content-type":"application/json"}),
      json:async()=>({capture_id:body.capture_id,payload_sha256:body.payload_sha256,
       server_id:"srv-77",outcome:"created",technical_acceptance:true,
       industrial_approval:false,operational_registered:true,operational_capture_id:body.capture_id})};
   },
  },
  sync:{
   tabId:"integration-test",unlockedKey:()=>key,online:()=>online,
   onlineSession:async()=>({userId:sessionUser}),
   subscribe:()=>()=>{},setTimer:()=>1,clearTimer:()=>{},
  },
 });
 experience.editor.onFieldEdited();
 assert.equal((await experience.editor.onGuardarCaptura()).status,"queued");
 assert.equal(queue.state,"queued");
 assert.equal(pending.synthetic,false);
 assert.equal(fetchCount,0);
 await assert.rejects(experience.syncNow(),/offline/);
 assert.equal(queue.state,"queued");
 online=true;
 let outcome=await experience.syncNow();
 assert.equal(outcome.paused,"different_user");
 assert.equal(fetchCount,0);
 assert.equal(queue.state,"queued");
 sessionUser=OWNER;
 outcome=await experience.syncNow();
 assert.equal(outcome.paused,null);
 assert.equal(fetchCount,1);
 assert.equal(queue.state,"synced");
 assert.equal(queue.serverRef,"srv-77");
 await experience.syncNow();
 assert.equal(fetchCount,1,"retries cannot duplicate an acknowledged capture");
 experience.stop();
});
