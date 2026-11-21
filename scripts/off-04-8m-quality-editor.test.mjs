import assert from "node:assert/strict";
import {test} from "node:test";
import {webcrypto} from "node:crypto";
import {createOperationalQualityEditor} from "../lib/vinto/offline-operational-quality-editor.ts";
const cryptoApi=globalThis.crypto??webcrypto;
Object.defineProperty(globalThis,"crypto",{value:cryptoApi,configurable:true});
const user="11111111-1111-4111-8111-111111111111";
const dev="33333333-3333-4333-8333-333333333333";
const scope="66666666-6666-4666-8666-666666666666";
const draft="44444444-4444-4444-8444-444444444444";
function definition(code){
 return {envelope:{payload:{form_code:code,form_version:1,machine_code:"MP1",
 definition:{form_code:code,form_version:1,fields:[
  {key:"medida",source:"manual",value_type:"decimal",required:true,options:[],display_order:0},
  {key:"derivado",source:"calculated",value_type:"decimal",required:false,options:[],display_order:1}
 ]}}}};
}
async function build(code,bobbin){
 const key=await cryptoApi.subtle.generateKey({name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
 let rev=null, locked=false,scopeOk=true, edited={medida:"10.5"}, storeRow=null,queue;
 const store={
  async getDraft(){return storeRow;},
  async saveDraft(row){storeRow=row;},
  sync:{async get(){return queue;}},
  async confirm(expected,cipher,p,q){queue=q;return {captureId:p.capture_id,created:true}},
 };
 const editor=await createOperationalQualityEditor({
  key,identity:{ownerId:user,deviceKey:dev},store,definition:definition(code),
  form:{draftId:draft,machineCode:"MP1",formCode:code,formVersion:1,captureScopeSnapshotId:scope,
   ...(bobbin?{bobbin}: {})},
  async assertCaptureScope(){if(!scopeOk)throw Error("no_authority");},
  ui:{
   current:()=>({draftId:draft,ownerId:user,revision:rev,values:edited}),
   unlocked:()=>true,
   setEditorLocked:v=>{locked=v;},
   setTimer:()=>1,clearTimer:()=>{},
   onDraftSaved:v=>{rev=v;},
   notifySync:()=>{},
  }
 });
 return {editor,store, get contextVersion(){return queue?.contextVersion},
  rejectAuthority(){scopeOk=false;},get locked(){return locked;}};
}
test("machine form uses independent capture scope snapshot as context",async()=>{
 const f=await build("VINTO-P1-22");
 f.editor.onFieldEdited();
 const r=await f.editor.onGuardarCaptura();
 assert.equal(r.status,"queued");
 assert.equal(f.contextVersion,scope);
 assert.equal(f.locked,true);
});
test("by-bobbin form derives SHA256 context from capture snapshot+original bobbin digest",async()=>{
 const b={bobbin_id:"77777777-7777-4777-8777-777777777777",context_digest:"a".repeat(64)};
 const f=await build("VINTO-P1-21",b);
 f.editor.onFieldEdited();
 assert.equal((await f.editor.onGuardarCaptura()).status,"queued");
 assert.match(f.contextVersion,/^[0-9a-f]{64}$/);
 assert.notEqual(f.contextVersion,scope);
});
test("valid readiness metadata never overrides a revoked capture authority",async()=>{
 const f=await build("VINTO-P1-22");
 f.rejectAuthority();f.editor.onFieldEdited();
 assert.equal((await f.editor.onGuardarCaptura()).status,"blocked");
 assert.equal(f.locked,false);
 assert.equal(f.contextVersion,undefined);
});
test("bobbin form cannot be started without a bobbin context",async()=>{
 await assert.rejects(build("VINTO-P1-21"),/BOBBIN/);
});
