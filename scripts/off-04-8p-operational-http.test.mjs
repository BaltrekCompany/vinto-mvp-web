import assert from "node:assert/strict";
import {test} from "node:test";
import {createOperationalHttpTransport, OperationalHttpUnavailable} from "../lib/vinto/offline-operational-http.ts";

const ORIGIN="https://qa.example.test/";
const ID="11111111-1111-4111-8111-111111111111";
const HASH="a".repeat(64);
const request={
 capture_id:ID,author_user_id:"22222222-2222-4222-8222-222222222222",
 device_key:"33333333-3333-4333-8333-333333333333",
 form_code:"VINTO-P1-19",form_version:1,machine_code:"MP1",
 context_version:"b".repeat(64),scope_snapshot_id:"44444444-4444-4444-8444-444444444444",
 payload_sha256:HASH,payload:{synthetic:false,payload:{test:"value"}},
};
const json=(data,status=201)=>({status,headers:new Headers({"content-type":"application/json"}),json:async()=>data});
test("operational HTTP sends same-origin authenticated payload and verifies operational ACK",async()=>{
 let calls=[];
 const transport=createOperationalHttpTransport({origin:ORIGIN,fetcher:async(url,opts)=>{
   calls.push({url,opts});
   return json({capture_id:ID,payload_sha256:HASH,server_id:"srv-1",outcome:"created",
      technical_acceptance:true,industrial_approval:false,operational_registered:true,operational_capture_id:ID});
 }});
 const result=await transport.send(request,{signal:new AbortController().signal});
 assert.equal(result.status,201);
 assert.equal(result.body.operational_registered,true);
 assert.equal(calls.length,1);
 assert.equal(calls[0].url,ORIGIN+"api/offline/captures");
 assert.equal(calls[0].opts.credentials,"include");
 assert.equal(calls[0].opts.mode,"same-origin");
 assert.equal(calls[0].opts.redirect,"error");
 assert.equal(calls[0].opts.cache,"no-store");
 assert.deepEqual(JSON.parse(calls[0].opts.body),request);
});
test("technical receipt never asserts operational registration",async()=>{
 const transport=createOperationalHttpTransport({origin:ORIGIN,fetcher:async()=>json({
  capture_id:ID,payload_sha256:HASH,server_id:"srv-2",outcome:"created",technical_acceptance:true,
  industrial_approval:false,
 })});
 const result=await transport.send(request,{signal:new AbortController().signal});
 assert.equal(result.body.operational_registered,undefined);
});
test("reconciliation cannot trust non-json or unverified response",async()=>{
 const transport=createOperationalHttpTransport({origin:ORIGIN,fetcher:async()=>json({
  found:true,capture_id:ID,server_id:"srv-3",outcome:"accepted",
  industrial_approval:false,operational_registered:true,operational_capture_id:ID,
 },200)});
 const lookup=await transport.lookup(ID,{signal:new AbortController().signal});
 assert.equal(lookup.found,true);
 assert.equal(lookup.operational_registered,true);
 const wrong=createOperationalHttpTransport({origin:ORIGIN,fetcher:async()=>json({
  found:true,capture_id:ID,server_id:"srv-3",outcome:"accepted",
  industrial_approval:false,operational_registered:true,
  operational_capture_id:"55555555-5555-4555-8555-555555555555",
 },200)});
 await assert.rejects(wrong.lookup(ID,{signal:new AbortController().signal}),/SYNC_TRANSPORT_NETWORK/);
});
test("no cross origin URLs, redirects, HTML login pages or unrelated endpoint",async()=>{
 for(const origin of ["https://qa.example.test/evil","https://qa.example.test/?x=y","file:///tmp/"]) {
  assert.throws(()=>createOperationalHttpTransport({origin,fetcher:async()=>null}),OperationalHttpUnavailable);
 }
 const html=createOperationalHttpTransport({origin:ORIGIN,fetcher:async()=>({
  status:200,headers:new Headers({"content-type":"text/html"}),json:async()=>({}),
 })});
 await assert.rejects(html.send(request,{signal:new AbortController().signal}),/SYNC_TRANSPORT_NETWORK/);
});
