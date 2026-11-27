import test from "node:test";
import assert from "node:assert/strict";
import {CONVERSION_PROFILE_DB,getConversionOfflineProfile,saveConversionOfflineProfile}
  from "../lib/vinto/foff-conversion-profile.ts";
import {prepareConversionForm}
  from "../lib/vinto/foff-conversion-prepare.ts";

const id="11111111-1111-4111-8111-111111111111";
const device="22222222-2222-4222-8222-222222222222";

test("FOFF-03: profile database is not Quality and has no in-memory fallback",async()=>{
  assert.notEqual(CONVERSION_PROFILE_DB,"vinto-quality-offline-preparations-v1");
  await assert.rejects(getConversionOfflineProfile({ownerId:id,deviceKey:device}),
    /foff_conversion_profile_unavailable/);
});
test("FOFF-03: profile never accepts a missing or identical signer pin",async()=>{
  await assert.rejects(saveConversionOfflineProfile({
    id:id+":"+device,ownerId:id,deviceKey:device,displayName:"Operador",
    vaultRecord:{} as never,preparationPin:"a".repeat(43),capturePin:"a".repeat(43),
  }),/foff_conversion_profile_invalid/);
});
test("FOFF-03: preparing a form requires explicit assignment, version and local passphrase",async()=>{
  await assert.rejects(prepareConversionForm({
    assignmentId:"",machineCode:"GAMBINI",formCode:"VINTO-P1-11",
    formVersion:4,localPassphrase:"x".repeat(20),
  }),/foff_conversion_invalid_assignment/);
  await assert.rejects(prepareConversionForm({
    assignmentId:id,machineCode:"GAMBINI",formCode:"VINTO-P1-99",
    formVersion:4,localPassphrase:"x".repeat(20),
  }),/foff_conversion_invalid_target/);
});
