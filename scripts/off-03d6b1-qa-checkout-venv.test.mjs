import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';

const filename = new URL('./off-03d6b1-qa-checkout-venv.sh',import.meta.url).pathname;
const src=readFileSync(filename,'utf8');
const run=(args=[],env={})=>spawnSync('bash',[filename,...args],{
  encoding:'utf8',timeout:8000,
  env:{PATH:process.env.PATH,HOME:process.env.HOME,...env}
});

test('only inspect/prepare/verify are documented; unsupported modes fail',()=>{
  const help=run(['--help']);
  assert.equal(help.status,0,help.stderr);
  assert.match(help.stdout,/inspect/);
  assert.match(help.stdout,/CONFIRM_QA_STAGE=YES/);
  for(const mode of ['migrate','apply','drop','restore','backup','install','deploy']){
    const result=run([mode]);
    assert.equal(result.status,1,mode);
    assert.match(result.stderr,/operacion no soportada/);
  }
  assert.equal(run([]).status,2);
});
test('prepare without explicit confirmation cannot write',()=>{
  const result=run(['prepare']);
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/(?:CONFIRM_QA_STAGE=YES|requiere sudo)/);
});
test('exact earlier gates and source pin retained',()=>{
  assert.match(src,/D5_BLOB=f296b71930a8820abea8666fb1aac01a16ede9e6/);
  assert.match(src,/D6A_BLOB=b52d2b2f5b9615b279163a9bfc1519b6331a94c4/);
  assert.match(src,/PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b/);
  assert.match(src,/check_script "\$D5" "\$D5_BLOB"/);
  assert.match(src,/check_script "\$D6A" "\$D6A_BLOB"/);
  assert.match(src,/bash "\$D6A" inspect \|\| die/);
  assert.match(src,/git -C "\$SOURCE" checkout --detach "\$PIN"/);
});
test('fixed QA paths, fail closed if any existing path',()=>{
  assert.match(src,/ROOT=\/srv\/vinto-qa-offline/);
  assert.match(src,/SOURCE=\/srv\/vinto-qa-offline\/source/);
  assert.match(src,/VENV=\/srv\/vinto-qa-offline\/venv/);
  assert.match(src,/BACKUPS=\/srv\/vinto-qa-offline\/backups/);
  assert.match(src,/\[ ! -e "\$p" \] && \[ ! -L "\$p" \]/);
  assert.match(src,/stat -c '%U:%a'/);
});
test('pinned minimal Python dependencies, no database-changing CLI',()=>{
  assert.match(src,/python3 -m venv "\$VENV"/);
  assert.match(src,/psycopg\[binary\]==3\.3\.6/);
  assert.match(src,/pydantic-settings==2\.15\.0/);
  assert.match(src,/MIGRATIONS_MANIFEST=31/);
  assert.doesNotMatch(src,/migrate\.py|pg_restore|pg_dump|docker (?:run|rm|stop|restart)|CREATE SCHEMA|DROP DATABASE/);
  assert.match(src,/OFF03D6B1_PREPARE=PASS_FILES_ONLY/);
  assert.match(src,/OFF03D6B1_BACKUP=NOT_CREATED/);
  assert.match(src,/OFF03D6B1_MIGRATIONS=NOT_STARTED/);
});
