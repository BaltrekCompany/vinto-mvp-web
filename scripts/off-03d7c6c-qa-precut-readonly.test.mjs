import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";

const path=new URL("./off-03d7c6c-qa-precut-readonly.sh",import.meta.url).pathname;
const s=readFileSync(path,"utf8");
const run=(...args)=>spawnSync("bash",[path,...args],{
  encoding:"utf8",timeout:4500,env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("only read-only audit permitted and no other operations",()=>{
 assert.equal(run().status,2);
 assert.equal(run("--help").status,0);
 for(const op of ["inspect","apply","cut","rollback","migrate","restore","deploy","create-user","grant","revoke","backup"]){
  const x=run(op);
  assert.equal(x.status,1,op);
  assert.match(x.stderr,/only_read_only_audit_permitted/);
 }
});
test("inherits post-role verifier, never invokes PRE-ROL code",()=>{
 for(const term of [
  "93a222224a99b7c0e1eaa3bcd2575681efb26af0",
  "OFF03D7C6B_POSTVERIFY=PASS_ROLE_AND_GRANTS_QA_ONLY",
  "OFF03D7C6B_ROLE_AUTH=PASS_READ_ONLY_QA_LOOPBACK",
  "OFF03D7C6B_QA_USERS_AND_GRANTS=ZERO",
  "OFF03D7C6B_DML_CUT=NOT_APPLIED",
  "OFF03D7C6C_POSTROLE=PASS_READ_ONLY"
 ])assert.ok(s.includes(term),term);
 assert.match(s,/bash "\$POSTROLE" verify/);
 assert.doesNotMatch(s,/bash .*d7c6a.*audit|bash .*d7c6b.*inspect|bash .*d7c5.*inspect/);
});
test("official cut and rollback fixed by Git blob but NEVER executed",()=>{
 for(const term of [
  "03d_d3b4_cut_identity_dml.sql:bc76423ed56506d55bff1fc0e4d9b82ea96f872b",
  "ROLLBACK_D3B4.sql:97041aa0c90b738d4f9be7fa71185b11f2240a9e",
  "OFF03D7C6C_CUT_AND_ROLLBACK=PASS_PINNED",
  "OFF03D7C6C_D3B4_SQL_CUT=NOT_AUTHORIZED"
 ])assert.ok(s.includes(term),term);
 assert.doesNotMatch(s,/(?:psql|bash|cat) .*\$SOURCE.*03d_d3b4|PGOPTIONS=.*vinto\.d3b4_approval|CUT-IDENTITY-DML-APPROVED/);
});
test("metadata only with PGOPTIONS read only on exact QA DB",()=>{
 const q=s.slice(s.indexOf('SQL="$(cat <<'),s.indexOf('status="$(docker exec'));
 for(const term of [
  "vinto-qa-postgres","vinto_qa_offline","vinto_qa_bootstrap",
  "default_transaction_read_only=on","statement_timeout=15000",
  "pg_auth_members","rolname='vinto_identity'","rolname='vinto_app'",
  "has_column_privilege('vinto_app','vinto_auth.credential','password_hash','SELECT')",
  "OFF03D7C6C_TWO_ROLES_DB_ACL=PASS_PRECUT_READ_ONLY"
 ])assert.ok(s.includes(term),term);
 assert.match(q,/current_database\(\) = 'vinto_qa_offline'/);
 assert.match(q,/PASS_PRECUT_DB_ROLES_READY/);
 assert.doesNotMatch(s,/docker (?:run|rm|stop|restart)|systemctl (?:start|stop|restart)|pg_dump|pg_restore|ALTER ROLE|CREATE ROLE|DROP ROLE|INSERT INTO|DELETE FROM|UPDATE .* SET/);
});
test("must NOT claim real API dual-role or write-guard verified",()=>{
 for(const term of [
  "OFF03D7C6C_ACTIVE_API_IDENTITY_DATABASE_URL=NOT_VERIFIED",
  "OFF03D7C6C_ACTIVE_API_PG_PRIVILEGE_MODE=NOT_VERIFIED",
  "OFF03D7C6C_ACTIVE_API_QA_WRITE_GUARD=NOT_VERIFIED",
  "OFF03D7C6C_D3B3_TWO_ROLE_FUNCTIONAL_GATE=NOT_EXECUTED_ON_QA",
  "OFF03D7C6C_AUDIT=PASS_READ_ONLY_WITH_FUNCTIONAL_GATES_OPEN",
  "NO_DATABASE_WRITES=PASS"
 ])assert.ok(s.includes(term),term);
});
