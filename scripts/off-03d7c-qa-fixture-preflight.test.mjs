import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
const file=new URL("./off-03d7c-qa-fixture-preflight.sh",import.meta.url).pathname;
const src=readFileSync(file,"utf8");
const run=arg=>spawnSync("bash",[file,...arg],{
  encoding:"utf8",timeout:5000,env:{PATH:process.env.PATH,HOME:process.env.HOME}
});
test("read-only gate rejects all writes before touching docker",()=>{
  assert.equal(run([]).status,2);
  assert.equal(run(["--help"]).status,0);
  for(const mode of ["apply","seed","import","install","deploy","migrate","restore","backup","reset"]){
    const got=run([mode]);
    assert.equal(got.status,1,mode);
    assert.match(got.stderr,/only_read_only_inspect_supported/);
  }
});
test("QA server and DB identities are hardcoded and require post DDL history",()=>{
  for(const marker of [
    "vinto-qa-postgres","vinto_qa_offline","vinto-qa-internal",
    "127.0.0.1:6554","postgres:17","vinto_qa_bootstrap",
    "default_transaction_read_only=on","count(*) FROM vinto_meta.schema_migration",
    "counts.migrations = 31","OFF03D7C_QA_AND_PILOT_ISOLATION=PASS"
  ]) assert.ok(src.includes(marker),marker);
});
test("only aggregate counts, no real identities or credentials exposed",()=>{
  assert.match(src,/count\(\*\) FROM vinto_master\."user"/);
  assert.match(src,/count\(\*\) FROM vinto_master\.user_machine_form_grant/);
  assert.match(src,/count\(\*\) FROM vinto_config\.form_version/);
  assert.match(src,/OFF03D7C_REFERENCE_BASELINE=REVIEW_REQUIRED/);
  assert.match(src,/OFF03D7C_QA_USER=NOT_CREATED/);
  assert.match(src,/OFF03D7C_SEED_AND_SIGNER=NOT_APPLIED/);
  assert.match(src,/NO_DATABASE_WRITES=PASS/);
  assert.doesNotMatch(src,/pg_restore|pg_dump|CREATE TABLE|INSERT INTO|UPDATE .*SET|DELETE FROM|docker (?:run|restart|stop|rm)|systemctl (?:restart|start|stop)/);
});
