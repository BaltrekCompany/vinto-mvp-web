import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import {test} from "node:test";
import ts from "typescript";

const src=p=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const js=ts.transpileModule(src("lib/vinto/quality-offline-api.ts"),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText;
const qualityBobbinsJs=ts.transpileModule(src("lib/vinto/quality-bobbins.ts"),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText;
const qb={};
runInNewContext(qualityBobbinsJs,{exports:qb,Set,Map});
const child=(id,motherId,position,code="25")=>({
 bobbin:{id,code:"CRIA-"+id,machine:{code:"COPASA",name:"COPASA"},
  rewinding:{mother_bobbin_id:motherId,mother_label:code,child_position:position}},
 production:{capture_id:"origin-"+motherId,work_order:{id:"ot",number:"OT"},
 line:{id:"line",line_code:"L1",pv_reference:"PV"}},
 quality:{status:"pending"},
});
test("pending online child rows yield distinct technical mothers, without child targets",async()=>{
 const requests=[];
 const records=[child("c1","m25a",1),child("c2","m25a",2),
   child("c3","m25b",1),{bobbin:{id:"b4",code:"4",
   machine:{code:"MP3",name:"MP3"}},production:{capture_id:"c4"},quality:{status:"pending"}}];
 const exports={};
 const fetch=async url=>{
  requests.push(url);
  return {ok:true,json:async()=>records};
 };
 runInNewContext(js,{exports,require:(p)=>p==="./quality-bobbins"?qb:
  p==="./api"?{apiBaseUrl:()=>"/api-base"}:{},fetch,Map,Set,Promise});
 const out=await exports.listQualityOfflineBobbins();
 assert.equal(out.length,3);
 assert.deepEqual(out.map(x=>x.bobbin.id).sort(),["b4","m25a","m25b"]);
 assert.deepEqual(out.filter(x=>x.bobbin.mother_quality).map(x=>x.bobbin.code),["25","25"]);
 assert.equal(requests.length,1);
 assert.match(requests[0],/status=pending/);
});
test("an inbox 403 never becomes an empty successful list",async()=>{
 const exports={};
 runInNewContext(js,{exports,require:(p)=>p==="./quality-bobbins"?qb:
  p==="./api"?{apiBaseUrl:()=>"/api-base"}:{},
  fetch:async()=>({ok:false,status:403}),Map,Set,Promise});
 await assert.rejects(exports.listQualityOfflineBobbins(),/offline_bobbin_inbox_http_403/);
});
