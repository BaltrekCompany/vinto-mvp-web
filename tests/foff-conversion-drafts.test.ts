import test from "node:test";
import assert from "node:assert/strict";
import {parseConversionDefinition,emptyConversionValues,normalizeConversionValues}
  from "../lib/vinto/foff-conversion-form-schema.ts";
import {CONVERSION_DRAFT_DB,loadConversionDraft,saveConversionDraft}
  from "../lib/vinto/foff-conversion-draft-store.ts";

const identity={ownerId:"11111111-1111-4111-8111-111111111111",
  deviceKey:"22222222-2222-4222-8222-222222222222"};
const groupId="33333333-3333-4333-8333-333333333333";
const f=(key:string,kind:string,required:boolean,group:string|null=null)=>({
  key,value_type:kind,source:"manual",required,group_id:group,unit:null,
  display_order:1,options:[],
});
const definition=()=>{
  return parseConversionDefinition({
    fields:[f("peso_kg","decimal",true),f("cantidad_jabas","integer",false),
      f("numero_bobina","text",true,groupId)],
    groups:[{id:groupId,code:"bobinas",repeatable:true,min_rows:1,max_rows:5,display_order:1}],
  });
};
test("FOFF-03 encrypted drafts stay separate from Quality",()=>{
  assert.notEqual(CONVERSION_DRAFT_DB,"vinto-off048-operational-v1");
  assert.notEqual(CONVERSION_DRAFT_DB,"vinto-quality-offline-preparations-v1");
});
test("FOFF-03 no plaintext fallback when IndexedDB is absent",async()=>{
  await assert.rejects(loadConversionDraft(identity,groupId),/foff_conversion_draft_unavailable/);
});
test("FOFF-03 server-published repeated groups and numeric values normalize",()=>{
  const d=definition();
  assert.deepEqual(emptyConversionValues(d),{_groups:{bobinas:[]}});
  assert.deepEqual(normalizeConversionValues(d,{
    peso_kg:"1.75",cantidad_jabas:"3",_groups:{bobinas:[{numero_bobina:"BOB-2"}]},
  }),{peso_kg:"1.75",cantidad_jabas:3,_groups:{bobinas:[{numero_bobina:"BOB-2"}]}});
});
test("FOFF-03 missing required fields and unknown values fail closed",()=>{
  const d=definition();
  assert.throws(()=>normalizeConversionValues(d,{_groups:{bobinas:[]}}));
  assert.throws(()=>normalizeConversionValues(d,{peso_kg:"1",extra:"untrusted",
    _groups:{bobinas:[{numero_bobina:"B"}]}}));
  assert.throws(()=>normalizeConversionValues(d,{peso_kg:"NaN",_groups:{bobinas:[{numero_bobina:"B"}]}}));
});
test("FOFF-03 unsupported calculated fields cannot become editable",()=>{
  assert.throws(()=>parseConversionDefinition({
    fields:[{...f("total","decimal",true),source:"calculated"}],groups:[],
  }));
});
test("FOFF-03 refuses invalid capture id before opening any storage",async()=>{
  await assert.rejects(saveConversionDraft({
    identity,key:{} as CryptoKey,preparationId:groupId,assignmentId:groupId,
    machineCode:"GAMBINI",formCode:"VINTO-P1-16",formVersion:4,
    captureId:"invalid",expectedRevision:0,values:{},
  }),/foff_conversion_draft_invalid/);
});
