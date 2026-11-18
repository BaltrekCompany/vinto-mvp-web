import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
const path=new URL("./off-03d7c6b-qa-identity-role-preflight.sh",import.meta.url).pathname;
const s=readFileSync(path,"utf8");
const run=(...args)=>spawnSync("bash",[path,...args],{
  encoding:"utf8",timeout:5000,env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("only READ ONLY inspect mode, all authorization-changing modes fail",()=>{
 assert.equal(run().status,2);
 assert.equal(run("--help").status,0);
 for(const op of ["audit","apply","install","create","create-role","grant","revoke","drop","migrate","restore","backup","deploy","reset"]){
   const p=run(op);
   assert.equal(p.status,1,op);
   assert.match(p.stderr,/read_only_inspect_only/);
 }
});
test("requires post-import D7C6A verified and pinned lifecycle files",()=>{
 for(const key of [
  "2433b96bf9bc9b0f4a46569e6f993b8299ec9e07",
  "OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN",
  "OFF03D7C6A_IDENTITY_ROLE=ABSENT_NOT_PROVISIONED",
  "OFF03D7C6A_POSTIMPORT_CATALOG=PASS_READ_ONLY",
  "OFF03D7C6A_APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE",
  "OFF03D7C6A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY",
  "00c_create_identity_role.sql:04bc90dfeaf225d2c139587899fa46ce54913fe5",
  "03c_d3b2_identity_role_grants.sql:6df9ac8c96d6cf85a00aecccc6631f8eddc7450b",
  "ROLLBACK_D3B2.sql:0039f4c530b611873f4b60710bf42aec54edd2c7",
  "03d_d3b4_cut_identity_dml.sql:bc76423ed56506d55bff1fc0e4d9b82ea96f872b",
 ]) assert.ok(s.includes(key),key);
 assert.match(s,/bash "\$D7C6A" audit/);
 assert.doesNotMatch(s,/bash .*d7c5.*inspect|bash .*d7c4.*inspect|bash .*d6b2.*verify/);
});
test("checks dedicated QA PG cluster role baseline by read-only aggregate only",()=>{
 for(const key of [
  "vinto-qa-postgres","vinto_qa_offline","vinto_qa_bootstrap",
  "default_transaction_read_only=on",
  "NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_identity')",
  "NOT pg_has_role('vinto_app','vinto_migrator','MEMBER')",
  "NOT pg_has_role('vinto_reference','vinto_migrator','MEMBER')",
  "vinto_auth.credential","vinto_master.user_machine_form_grant",
  "PASS_PRE_ROLE_CREATION","ROLE_REMOVAL_OUT_OF_SCOPE",
  "OFF03D7C6B_ROLE_CREATE_GRANTS=NOT_AUTHORIZED",
  "OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY",
  "NO_DATABASE_WRITES=PASS",
 ])assert.ok(s.includes(key),key);
 assert.doesNotMatch(s,/ALTER ROLE|CREATE ROLE|DROP ROLE|GRANT .* ON|REVOKE .* ON|INSERT INTO|UPDATE .* SET|DELETE FROM|docker (?:run|rm|stop|restart)|systemctl (?:start|stop|restart)|pg_restore|pg_dump|curl |chmod |chown /);
});
