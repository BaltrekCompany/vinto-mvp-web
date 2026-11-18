import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const rolePath=new URL("./off-03d7b-qa-app-role-audit.sh",import.meta.url).pathname;
const smokePath=new URL("./off-03d7b-vinext-standalone-smoke.sh",import.meta.url).pathname;
const role=readFileSync(rolePath,"utf8");
const smoke=readFileSync(smokePath,"utf8");
const run=(file,arg)=>spawnSync("bash",[file,...arg],{
  encoding:"utf8",timeout:6000,env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("QA app audit only accepts audit mode; never operates on VPS in CI",()=>{
  assert.equal(run(rolePath,["help"]).status,0);
  assert.equal(run(rolePath,[]).status,2);
  for(const mode of ["inspect","apply","install","prepare","restore","migrate","deploy","rollback"]){
    const got=run(rolePath,[mode]);
    assert.equal(got.status,1,mode);
    assert.match(got.stderr,/only audit mode/);
  }
  assert.match(role,/set \+x/);
  assert.match(role,/OFF03D7B_AUDIT=PASS_READ_ONLY/);
  assert.match(role,/NO_DATABASE_WRITES=PASS/);
});

test("QA SQL target and container are pinned, no pilot or TVC DB queries",()=>{
  for(const marker of [
    "vinto-qa-postgres","vinto_qa_offline","127.0.0.1:6554",
    "vinto-qa-internal","vinto_qa_bootstrap","vinto_app","vinto_meta.schema_migration",
    "default_transaction_read_only=on","statement_timeout=10000",
    "/etc/vinto-qa/role-app.password","root:600","OFF03D7B_QA_APP_LOGIN=PASS_READ_ONLY",
  ]) assert.ok(role.includes(marker),marker);
  assert.match(role,/count\(\*\) FROM vinto_meta\.schema_migration\)=31/);
  assert.match(role,/not has_schema_privilege\('vinto_app','vinto_meta','USAGE'\)/i);
  assert.match(role,/not has_table_privilege\('vinto_app','vinto_master\.profile','INSERT'\)/i);
  assert.match(role,/current_user='vinto_app'/);
  assert.doesNotMatch(role,/migrate\.py|pg_dump|pg_restore|docker (?:run|stop|rm|restart)|systemctl (?:start|stop|restart)|\bDELETE FROM\b|\bINSERT INTO\b|\bCREATE TABLE\b|\bALTER TABLE\b/);
});

test("QA secret is used only through stdin, never password argv or output",()=>{
  assert.match(role,/cat "\$APP_SECRET" \| docker exec -i/);
  assert.match(role,/IFS= read -r PGPASSWORD/);
  assert.match(role,/export PGPASSWORD/);
  assert.doesNotMatch(role,/echo.*\$APP_SECRET|printf.*PGPASSWORD|password=[^\s]+ -c|PGPASSWORD=\$\(cat/);
});

test("standalone smoke cannot execute outside ephemeral Github Actions runner",()=>{
  assert.equal(run(smokePath,[]).status,2);
  for(const mode of ["apply","deploy","start","install"]){
    assert.equal(run(smokePath,[mode]).status,2,mode);
  }
  const out=run(smokePath,["smoke"]);
  assert.equal(out.status,1);
  assert.match(out.stderr,/ephemeral GitHub Actions runner required/);
  assert.match(smoke,/HOSTNAME=127\.0\.0\.1/);
  assert.match(smoke,/node dist\/standalone\/server\.js/);
  assert.match(smoke,/OFF03D7B_SMOKE=PASS_EPHEMERAL_ONLY/);
  assert.doesNotMatch(smoke,/wrangler.*dev|pnpm start|ssh |docker (?:run|exec|restart)|nginx/);
});

test("standalone tests exact QA origin, offline resources and exit cleanup",()=>{
  assert.match(smoke,/NEXT_PUBLIC_API_URL/);
  assert.match(smoke,/https:\/\/qa-vinto-mvp\.baltrekservices\.com/);
  assert.match(smoke,/kill "\$PID"/);
  assert.match(smoke,/trap cleanup EXIT/);
  for(const path of ["/offline-preparacion","/offline.html","/sw.js",
    "/offline-device-qa.js","/offline-boot.js","/offline-probe.js",
    "/manifest.webmanifest","/favicon.svg"]) assert.ok(smoke.includes(path),path);
});
