import assert from "node:assert/strict";
import {test} from "node:test";
import {createOperationalQualityValidator,MACHINE_QUALITY_FORMS,BOBBIN_QUALITY_FORMS,ALL_OFFLINE_QUALITY_FORMS}
 from "../lib/vinto/offline-operational-quality-validation.ts";
const form=(code,required=true)=>({
 envelope:{payload:{form_code:code,form_version:2,machine_code:"MP1",
 definition:{form_code:code,form_version:2,
 fields:[{key:"medida",source:"manual",required,value_type:"decimal",options:[],display_order:0},
 {key:"nota",source:"manual",required:false,value_type:"text",options:[],display_order:1},
 {key:"promedio",source:"calculated",required:false,value_type:"decimal",options:[],display_order:2}]}}}
});
const uuid="11111111-1111-4111-8111-111111111111",digest="a".repeat(64);
const make=(code)=>createOperationalQualityValidator(form(code),{
 formCode:code,formVersion:2,machineCode:"MP1",
 ...(BOBBIN_QUALITY_FORMS.has(code)?{bobbin:{bobbin_id:uuid,context_digest:digest}}:{})});
test("exact ten forms have correct machine/bobbin kinds",()=>{
 assert.equal(ALL_OFFLINE_QUALITY_FORMS.size,10);
 assert.equal(MACHINE_QUALITY_FORMS.size,4);
 assert.equal(BOBBIN_QUALITY_FORMS.size,6);
 for(const f of ALL_OFFLINE_QUALITY_FORMS)make(f)({medida:"12.4"});
});
test("required and unknown/calculated values fail closed",()=>{
 const valid=make("VINTO-P1-22");
 assert.throws(()=>valid({}),/INCOMPLETE/);
 assert.throws(()=>valid({medida:"12.4",promedio:"1"}),/INVALID/);
 assert.throws(()=>valid({medida:"12.4",alien:"x"}),/INVALID/);
});
test("non-normalized decimals are not silently modified on confirmation",()=>{
 const v=make("VINTO-P1-22");
 assert.throws(()=>v({medida:"12,5"}),/INVALID/);
 assert.throws(()=>v({medida:" 12.5 "}),/INVALID/);
 v({medida:"12.5"});
});
test("bobbin binding mandatory on bobbin forms and forbidden on machine forms",()=>{
 assert.throws(()=>createOperationalQualityValidator(form("VINTO-P1-21"),{
  formCode:"VINTO-P1-21",formVersion:2,machineCode:"MP1"}),/BOBBIN/);
 assert.throws(()=>createOperationalQualityValidator(form("VINTO-P1-22"),{
  formCode:"VINTO-P1-22",formVersion:2,machineCode:"MP1",
  bobbin:{bobbin_id:uuid,context_digest:digest}}),/BOBBIN/);
});
test("wrong machine/form/version or malformed bobbin context cannot pass",()=>{
 assert.throws(()=>createOperationalQualityValidator(form("VINTO-P1-22"),{
  formCode:"VINTO-P1-22",formVersion:3,machineCode:"MP1"}),/DEFINITION/);
 assert.throws(()=>createOperationalQualityValidator(form("VINTO-P1-22"),{
  formCode:"VINTO-P1-22",formVersion:2,machineCode:"MP3"}),/DEFINITION/);
 assert.throws(()=>createOperationalQualityValidator(form("VINTO-P1-21"),{
  formCode:"VINTO-P1-21",formVersion:2,machineCode:"MP1",
  bobbin:{bobbin_id:uuid,context_digest:"tampered"}}),/CONTEXT/);
});
