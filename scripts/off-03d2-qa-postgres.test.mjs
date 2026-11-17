import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const path = new URL('./off-03d2-qa-postgres.sh', import.meta.url).pathname;
const source = readFileSync(path, 'utf8');
function invoke(args) {
  return spawnSync('bash', [path, ...args], {
    encoding: 'utf8',
    env: { PATH: process.env.PATH, HOME: process.env.HOME },
    timeout: 8000,
  });
}
test('help never invokes Docker', () => {
  const r = invoke(['--help']);
  assert.equal(r.status, 0);
  assert.match(r.stdout, /preflight/);
  assert.match(r.stdout, /verify/);
});
test('install without explicit gate is blocked before preflight or writes', () => {
  const r = invoke(['install']);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /CONFIRM_QA_DB_CREATE=YES/);
  assert.doesNotMatch(r.stdout, /QA_NAMES_COLLISION/);
});
test('unknown operation is blocked', () => {
  const r = invoke(['unsupported-operation']);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /accion desconocida/);
});
test('script has QA-only network, volume, loopback binding and no deletion of data', () => {
  assert.match(source, /vinto-qa-postgres/);
  assert.match(source, /vinto-qa-internal/);
  assert.match(source, /vinto-qa-offline-pgdata/);
  assert.match(source, /127\.0\.0\.1:\$PORT:5432/);
  assert.match(source, /POSTGRES_PASSWORD_FILE/);
  assert.match(source, /default_transaction_read_only=on/);
  assert.doesNotMatch(source, /docker (?:rm|rmi|stop|restart|volume rm|system prune)/);
});
