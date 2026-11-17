import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const script = new URL('./off-03d6a-qa-staging-preflight.sh', import.meta.url).pathname;
const src = readFileSync(script, 'utf8');
const run = args => spawnSync('bash', [script, ...args], {
  encoding:'utf8', timeout:8000,
  env:{PATH:process.env.PATH, HOME:process.env.HOME},
});
test('only help and inspect are accepted',()=>{
  const help=run(['--help']);
  assert.equal(help.status,0);
  assert.match(help.stdout,/inspect/);
  for (const mode of ['install','prepare','backup','migrate','apply','drop','restore']) {
    const r=run([mode]);
    assert.equal(r.status,1);
    assert.match(r.stderr,/solo inspect/);
  }
  assert.equal(run([]).status,2);
});
test('preflight relies on exact OFF03D5 audit and cannot silently bypass it',()=>{
  assert.match(src,/D5_BLOB=f296b71930a8820abea8666fb1aac01a16ede9e6/);
  assert.match(src,/git hash-object "\$D5"/);
  assert.match(src,/bash "\$D5" inspect \|\| die/);
  assert.match(src,/OFF03D6A_D5_GATE=PASS/);
});
test('isolated QA path is fixed and protected against prior checkout',()=>{
  assert.match(src,/QA_ROOT=\/srv\/vinto-qa-offline/);
  assert.match(src,/QA_CHECKOUT=\/srv\/vinto-qa-offline\/source/);
  assert.match(src,/QA_VENV=\/srv\/vinto-qa-offline\/venv/);
  assert.match(src,/QA_BACKUPS=\/srv\/vinto-qa-offline\/backups/);
  assert.match(src,/\[ ! -e "\$path" \] && \[ ! -L "\$path" \]/);
});
test('read only SQL, no Docker mutations, no DDL, no staging creation',()=>{
  assert.match(src,/default_transaction_read_only=on/);
  assert.match(src,/pg_database_size\(current_database\(\)\)/);
  assert.match(src,/OFF03D6A_PREFLIGHT=PASS_READ_ONLY/);
  assert.doesNotMatch(src,/docker (?:run|stop|restart|rm|volume|network|cp)\b/);
  assert.doesNotMatch(src,/^[ \t]*(?:mkdir|rm|mv|cp|chmod|chown|pg_restore -d|git clone|pip install)\b/m);
  assert.doesNotMatch(src,/(?:migrate\.py|--target dev|CREATE SCHEMA|DROP DATABASE|TRUNCATE)/);
});
