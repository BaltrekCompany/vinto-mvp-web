import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {runInNewContext} from "node:vm";
import ts from "typescript";

const source=readFileSync(new URL("../lib/vinto/quality-offline-clock.ts",import.meta.url),"utf8");
const compiled=ts.transpileModule(source,{compilerOptions:{
  module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
}}).outputText;

function moduleWithHandsetTime(initial){
 const handset={current:initial};
 const FakeDate={parse:Date.parse,now:()=>handset.current};
 const exports={};
 runInNewContext(compiled,{exports,Date:FakeDate});
 return {...exports,handset};
}
function envelope(issued,expires){
 return {payload:{issued_at:new Date(issued).toISOString(),
                  expires_at:new Date(expires).toISOString()}};
}

test("six-hour handset skew does not invalidate a freshly issued signed scope",()=>{
 const server=Date.UTC(2026,10,25,20,0,0);
 const {validateQualityServerClock,qualityScopeNow,handset}
  =moduleWithHandsetTime(server-6*3600000);
 const authority=envelope(server,server+12*3600000);
 const clock={serverDateMs:server,clientReceivedAtMs:handset.current};
 assert.equal(validateQualityServerClock(authority,clock),clock);
 assert.ok(qualityScopeNow(clock)>=server);
 assert.ok(qualityScopeNow(clock)<server+3000);
});
test("a stale authenticated Date response cannot resurrect an old grant",()=>{
 const server=Date.UTC(2026,10,25,20,0,0);
 const {validateQualityServerClock}=moduleWithHandsetTime(server);
 const authority=envelope(server,server+12*3600000);
 assert.throws(()=>validateQualityServerClock(authority,{
   serverDateMs:server+12*3600000,clientReceivedAtMs:server,
 }),/offline_quality_server_clock_invalid/);
 assert.throws(()=>validateQualityServerClock(authority,{
   serverDateMs:server-6000,clientReceivedAtMs:server,
 }),/offline_quality_server_clock_invalid/);
});
test("an expired scope remains expired after the offline duration elapses",()=>{
 const server=Date.UTC(2026,10,25,20,0,0);
 const {qualityScopeNow,handset}=moduleWithHandsetTime(server-6*3600000);
 const clock={serverDateMs:server,clientReceivedAtMs:handset.current};
 handset.current+=13*3600000;
 assert.ok(qualityScopeNow(clock)>server+12*3600000);
});
