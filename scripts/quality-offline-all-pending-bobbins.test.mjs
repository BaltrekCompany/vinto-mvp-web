import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {runInNewContext} from "node:vm";
import {test} from "node:test";
import ts from "typescript";
const source=(p)=>readFileSync(new URL("../"+p,import.meta.url),"utf8");
const compiled=(p,bindings={})=>{
 const exports={};
 const js=ts.transpileModule(source(p),{compilerOptions:{
  module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,
 }}).outputText;
 runInNewContext(js,{exports,require:(name)=>bindings[name]??{},Set,Map,Promise});
 return exports;
};
const auto=compiled("lib/vinto/quality-offline-auto-prepare.ts");
const form=(machineCode,formCode,kind="bobbin")=>({
 machineCode,formCode,kind,formVersion:1,machineName:machineCode,name:formCode,
});
const bobbin=(id,code,machineCode)=>({
 bobbin:{id,code,machine:{code:machineCode,name:machineCode}},
 quality:{status:"pending"},
});
test("MP3 prepares distinct bobbin 4 and 5, plus any new pending bobbin",()=>{
 const p=auto.enumerateQualityPreparationPairs(
  [form("MP3","VINTO-P1-24"),form("MP1","VINTO-P1-20")],
  [bobbin("b4","4","MP3"),bobbin("b5","5","MP3"),bobbin("b6","6","MP3"),
   bobbin("b2","2","MP1")],
 );
 assert.equal(p.length,4);
 assert.equal(JSON.stringify([...p.filter(x=>x.offer.machineCode==="MP3").map(x=>x.bobbin.bobbin.id)].sort()),JSON.stringify(["b4","b5","b6"]));
});
test("all machine forms remain machine-level and no pair is duplicated",()=>{
 const p=auto.enumerateQualityPreparationPairs(
 [form("MP1","VINTO-P1-22","machine"),form("MP1","VINTO-P1-22","machine")],
 [bobbin("b2","2","MP1"),bobbin("b3","3","MP1")]);
 assert.equal(p.length,1);assert.equal(p[0].bobbin,null);
});
test("two mothers with same visible label are different UUIDs",()=>{
 const p=auto.enumerateQualityPreparationPairs(
  [form("COPASA","VINTO-P1-24")],
  [bobbin("m25a","25","COPASA"),bobbin("m25b","25","COPASA")]);
 assert.equal(p.length,2);
});
test("no silent truncation of all pending targets under configured ceiling",()=>{
 const bobbins=Array.from({length:80},(_,i)=>bobbin("b"+i,String(i+1),"MP3"));
 const p=auto.enumerateQualityPreparationPairs(
 [form("MP3","VINTO-P1-24"),form("MP3","VINTO-P1-21")],bobbins);
 assert.equal(p.length,160);
 assert.ok(auto.MAX_AUTO_PREPARE_PAIRS>=160);
});
test("workspace displays coverage, not obsolete N/22 offer ratio",()=>{
 const ui=source("components/vinto/quality-offline-workspace.tsx");
 assert.match(ui,/result\.total/);
 assert.match(ui,/result\.completed/);
 assert.match(ui,/result\.omitted/);
 assert.doesNotMatch(ui,/available\.length\+\s*\(result\.failed/);
});
