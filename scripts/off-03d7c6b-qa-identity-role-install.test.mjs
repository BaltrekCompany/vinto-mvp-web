import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";

const file=new URL("./off-03d7c6b-qa-identity-role-install.sh",import.meta.url).pathname;
const s=readFileSync(file,"utf8");
const run=(...args)=>spawnSync("bash",[file,...args],{
  encoding:"utf8",timeout:4500,
  env:{PATH:process.env.PATH,HOME:process.env.HOME}
});

test("only inspect, verify and confirmed apply advertised; other modes blocked",()=>{
 assert.equal(run().status,2);
 assert.equal(run("--help").status,0);
 for(const mode of ["install","migrate","backup","restore","drop","reset","grant","revoke","apply-again","deploy"]){
  const x=run(mode);
  assert.equal(x.status,1,mode);
  assert.match(x.stderr,/unsupported_operation/);
 }
 const x=run("apply");
 assert.notEqual(x.status,0);
 assert.match(x.stderr,/(sudo_required|missing_specific_CREATE_ROLE_and_GRANT_approval)/);
});

test("three explicit operator gates, pre-role audit pinned, QA source and Docker fixed",()=>{
 for(const key of [
  "CONFIRM_QA_IDENTITY_ROLE_INSTALL=YES",
  "CONFIRM_QA_TARGET=vinto_qa_offline_6554",
  "ACK_NO_NEW_BACKUP=YES",
  "abfb2e15e99cd207693a309c5d8d7314ae71f467",
  "OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY",
  "OFF03D7C6B_ROLE_CREATE_GRANTS=NOT_AUTHORIZED",
  "vinto-qa-postgres","vinto-qa-internal","127.0.0.1:6554",
  "7b9eb8c82a290d06e719ee4990c2020076bbd11b",
  "OFF03D7C6B_NO_NEW_BACKUP=EXPLICITLY_WAIVED",
 ])assert.ok(s.includes(key),key);
 assert.match(s,/bash "\$PRE" inspect/);
 assert.match(s,/flock -n 9/);
 assert.match(s,/git -C "\$SOURCE" status --porcelain --untracked-files=all/);
 assert.doesNotMatch(s,/docker (?:run|rm|stop|restart)|systemctl (?:stop|start|restart)|git (?:pull|checkout|reset)|pg_dump|pg_restore/);
});

test("official role and grants pinned, only QA admin CREATE and owner CONNECT; no D3B4",()=>{
 for(const key of [
  "00c_create_identity_role.sql:04bc90dfeaf225d2c139587899fa46ce54913fe5",
  "03c_d3b2_identity_role_grants.sql:6df9ac8c96d6cf85a00aecccc6631f8eddc7450b",
  "ROLLBACK_D3B2.sql:0039f4c530b611873f4b60710bf42aec54edd2c7",
  "GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_identity",
  "OFF03D7C6B_ROLE_CREATE=PASS_QA_CLUSTER_ONLY",
  "OFF03D7C6B_QA_DB_CONNECT=PASS_BOOTSTRAP_OWNER",
  "OFF03D7C6B_D3B2_GRANTS=EXECUTED_QA_ONLY",
 ])assert.ok(s.includes(key),key);
 assert.match(s,/docker exec -i "\$QA" \/bin\/sh -c/);
 assert.match(s,/-U vinto_qa_bootstrap -d vinto_qa_offline -f -/);
 assert.match(s,/-U vinto_migrator -d vinto_qa_offline -f -/);
 assert.doesNotMatch(s,/03d_d3b4_cut_identity_dml\.sql|DROP ROLE|REVOKE CONNECT|ROLLBACK_D3B2\.sql.*psql|CREATE ROLE vinto_identity LOGIN/);
});

test("password generated exclusively on apply, protected root 0600, never in CLI",()=>{
 for(const k of [
  "O_EXCL","O_NOFOLLOW","secrets.token_hex(32)",
  "role-identity.password","root:600",
  "role-migrator.password",
  "IFS= read -r IDENTITY_PASSWORD; export IDENTITY_PASSWORD",
  "IFS= read -r PGPASSWORD; export PGPASSWORD",
  "OFF03D7C6B_QA_IDENTITY_SECRET=CREATED_ROOT_600_NO_VALUE",
 ])assert.ok(s.includes(k),k);
 const create=s.indexOf('secrets.token_hex(32)');
 const apply=s.indexOf('apply(){');
 const dispatch=s.lastIndexOf('case "$OP" in');
 assert.ok(create>apply && create<dispatch);
 assert.doesNotMatch(s,/docker exec (?:-e|--env) (?:IDENTITY_PASSWORD|PGPASSWORD)|IDENTITY_PASSWORD="\$\(cat|echo "\$IDENTITY_PASSWORD"|print\(secret\)|print\(password\)/);
});

test("postverify is distinct from the absent-role preflight and does not modify DB",()=>{
 const verify=s.slice(s.indexOf("verify_role(){"),s.indexOf("\ninspect(){"));
 assert.doesNotMatch(verify,/check_pre|bash "\$PRE" inspect|psql.*-f -|GRANT CONNECT/);
 assert.match(verify,/PGOPTIONS|default_transaction_read_only=on/);
 for(const key of [
  "PASS_ROLE_IDENTITY_ADDITIVE_ONLY",
  "OFF03D7C6B_ROLE_GRANTS=PASS_D3B2_ADDITIVE_ONLY",
  "OFF03D7C6B_QA_CATALOG_AND_MIGRATIONS=PASS_UNCHANGED",
  "OFF03D7C6B_ROLE_AUTH=PASS_READ_ONLY_QA_LOOPBACK",
  "OFF03D7C6B_POSTVERIFY=PASS_ROLE_AND_GRANTS_QA_ONLY",
  "OFF03D7C6B_DML_CUT=NOT_APPLIED",
  "OFF03D7C6B_NEW_USERS=NOT_CREATED",
 ])assert.ok(s.includes(key),key);
});

test("effective ACL must check each SELECT INSERT UPDATE independently",()=>{
 const q=s.slice(s.indexOf("role_metadata_sql="),s.indexOf("verify_role(){"));
 assert.doesNotMatch(q,/'SELECT,INSERT,UPDATE'|'SELECT,INSERT'/);
 for(const tbl of ["vinto_master.\"user\"","vinto_auth.credential","vinto_master.user_machine_form_grant"]){
   for(const priv of ["SELECT","INSERT","UPDATE"]){
     assert.ok(q.includes("has_table_privilege('vinto_identity','"+tbl+"','"+priv+"')"),
       tbl+" "+priv);
   }
 }
 for(const forbidden of [
  "NOT has_table_privilege('vinto_identity','vinto_master.machine','INSERT')",
  "NOT has_table_privilege('vinto_identity','vinto_master.sector','INSERT')",
  "NOT has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','DELETE')",
  "NOT EXISTS (SELECT 1 FROM pg_auth_members",
 ])assert.ok(q.includes(forbidden),forbidden);
});
