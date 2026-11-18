import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";

const path=new URL("./off-03d7c6a-qa-identity-readiness.sh",import.meta.url).pathname;
const source=readFileSync(path,"utf8");
const run=(...args)=>spawnSync("bash",[path,...args],{
  encoding:"utf8",timeout:4500,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("rejects unsafe operation modes before PostgreSQL or secrets",()=>{
 assert.equal(run().status,2);
 assert.equal(run("--help").status,0);
 for(const mode of ["inspect","apply","create-role","seed","create-user","grant","revoke","backup","restore","deploy","migrate","reset"]){
  const z=run(mode);
  assert.equal(z.status,1,mode);
  assert.match(z.stderr,/only_read_only_audit_permitted/);
 }
});
test("requires trusted postimport audit before inspecting identity",()=>{
 for(const marker of [
  "34c560bc0e1b77381820d0e9d5b57caf1de4c67a",
  "OFF03D7C5A_AUDIT=PASS_READ_ONLY",
  "OFF03D7C5A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY",
  "OFF03D7C5A_FULL_REFERENCE_CATALOG=PASS_COUNTS",
  "OFF03D7C5A_MP1_MP3=PASS_EIGHT_EXACT_PAIRS",
  "OFF03D7C5A_PILOT_TVC_STATUS=PASS_AT_AUDIT",
  "OFF03D7C6A_POSTIMPORT_CATALOG=PASS_READ_ONLY",
 ])assert.ok(source.includes(marker),marker);
 assert.match(source,/bash "\$PREVIOUS" audit/);
 assert.doesNotMatch(source,/bash .*d7c5.*inspect|bash .*d7c4.*inspect|bash .*off03d6b2.*verify|bash .*off03d6c1.*inspect/);
});
test("fixed QA postgres and aggregate read-only SQL, no credentials/rows printed",()=>{
 for(const marker of [
  "vinto-qa-postgres","vinto_qa_offline","vinto_qa_bootstrap",
  "default_transaction_read_only=on","count(*) FROM vinto_meta.schema_migration",
  "pg_roles WHERE rolname = 'vinto_identity'",
  "vinto_master.user_machine_form_grant",
  "vinto_auth.credential","vinto_auth.session",
  "has_table_privilege('vinto_app', 'vinto_master.\"user\"', 'INSERT')",
  "has_table_privilege('vinto_app', 'vinto_auth.credential', 'INSERT')",
  "has_column_privilege('vinto_app', 'vinto_auth.credential', 'password_hash', 'SELECT')",
  "ROLE_ABSENT_APP_IDENTITY_DML_PRESENT"
 ])assert.ok(source.includes(marker),marker);
 assert.doesNotMatch(source,/postgresql:\/\/|PGPASSWORD|role-reference\.password|echo.*secret|SELECT .*password_hash|SELECT .*username/);
});
test("PASS audit is not permission to create identity and does not assert QA API deployed",()=>{
 for(const marker of [
  "OFF03D7C6A_IDENTITY_ROLE=ABSENT_NOT_PROVISIONED",
  "OFF03D7C6A_APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE",
  "OFF03D7C6A_TEST_ACCOUNT_CREATE=BLOCKED_PENDING_ROLE_AND_APPROVAL",
  "OFF03D7C6A_GRANTS_AND_SIGNING=NOT_AUTHORIZED",
  "OFF03D7C6A_QA_WEB_WRITE_GUARD=NOT_VERIFIED_ON_DEPLOYED_API",
  "OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN",
  "NO_DATABASE_WRITES=PASS",
 ])assert.ok(source.includes(marker),marker);
 assert.doesNotMatch(source,/docker (?:run|rm|stop|restart)|systemctl (?:start|stop|restart)|pg_restore|pg_dump|ALTER ROLE|CREATE ROLE|INSERT INTO|UPDATE .* SET|DELETE FROM|chmod |chown |git (?:pull|checkout|reset)/);
});
