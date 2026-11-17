import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {mkdtempSync,writeFileSync,mkdirSync,rmSync,readFileSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {test} from "node:test";
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const source=readFileSync(path.join(root,"scripts/off-03d1-https-preflight.sh"),"utf8");

test("preflight is strictly unauthenticated, HTTPS-only and read-only",()=>{
  assert.match(source,/\^https:\/\//);
  assert.match(source,/--proto '=https'/);
  assert.match(source,/--max-redirs 0/);
  assert.doesNotMatch(source,/--insecure|--location|--cookie|--user\s|--authorization|--oauth|--netrc/);
  assert.doesNotMatch(source,/sudo |psql |pg_dump |docker |kubectl |systemctl |nginx -s|git push|git merge/);
  assert.match(source,/DATABASE_ISOLATION=NOT_VERIFIED/);
  assert.match(source,/MOBILE_HARD_RESTART=NOT_RUN/);
});

const stub=`#!/usr/bin/env bash
set -euo pipefail
body='' headers='' url=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) body="$2"; shift 2 ;;
    --dump-header) headers="$2"; shift 2 ;;
    --connect-timeout|--max-time|--proto|--max-redirs|--request|--header|--data|--write-out)
      shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
: > "$body"
: > "$headers"
case "$url" in
  */api/*)
    if [[ "$FAKE_AUTH_OPEN" = 1 ]]; then printf 200; else printf 401; fi
    ;;
  */offline.html) printf '/offline-device-qa.js' > "$body"; printf 200 ;;
  */sw.js) printf 'vinto-off03c3-static-v1' > "$body"; printf 200 ;;
  */offline-device-qa.js)
    if [[ "$FAKE_STALE" != 1 ]]; then printf 'vinto-off03c3-static-v1' > "$body"; fi
    printf 200 ;;
  *) printf 200 ;;
esac
`;
function exercise(extra={},origin="https://qa.vinto.example"){
  const base=mkdtempSync(path.join(tmpdir(),"vinto-preflight-test-"));
  try{
    const bin=path.join(base,"bin");mkdirSync(bin);
    const curl=path.join(bin,"curl");
    writeFileSync(curl,stub,{mode:0o755});
    return spawnSync("bash",[path.join(root,"scripts/off-03d1-https-preflight.sh"),origin],{
      cwd:root,encoding:"utf8",timeout:10000,
      env:{...process.env,FAKE_AUTH_OPEN:"0",FAKE_STALE:"0",PATH:bin+":"+process.env.PATH,...extra}});
  }finally{rmSync(base,{recursive:true,force:true});}
}
test("synthetic protected QA serves public shell and returns only NETWORK PASS",()=>{
  const r=exercise();
  assert.equal(r.status,0, r.stdout+"\n"+r.stderr);
  assert.match(r.stdout,/CHECKS_PASS=12 CHECKS_BLOCKED=0/);
  assert.match(r.stdout,/OFF03D1_REMOTE_GATE=PASS_NETWORK_ONLY/);
  assert.match(r.stdout,/DATABASE_ISOLATION=NOT_VERIFIED/);
});
test("unprotected auth or stale PWA asset blocks QA",()=>{
  const open=exercise({FAKE_AUTH_OPEN:"1"});
  assert.equal(open.status,1);
  assert.match(open.stdout,/esperado 401/);
  assert.match(open.stdout,/OFF03D1_REMOTE_GATE=BLOCKED/);
  const stale=exercise({FAKE_STALE:"1"});
  assert.equal(stale.status,1);
  assert.match(stale.stdout,/versión\/artefacto no coincide/);
});
test("HTTP, credentials, path and redirects-in-origin are rejected",()=>{
  for(const origin of ["http://qa.vinto.example","https://alice:pass@qa.vinto.example",
    "https://qa.vinto.example/path","https://qa.vinto.example?redirect=1"]){
    const r=exercise({},origin);assert.equal(r.status,2,r.stdout+r.stderr);
    assert.match(r.stderr,/solo origen HTTPS/);
  }
});
