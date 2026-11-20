import assert from "node:assert/strict";
import { test } from "node:test";
import { createDraftAutosave } from "../lib/vinto/offline-draft-autosave.ts";
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function env() {
  const timers = new Map();
  let sequence = 0, unlocked = true, revision = null, val = "first";
  const attempts = [], errors = [];
  let failure = false;
  const save = createDraftAutosave({
    unlocked: () => unlocked,
    current: () => ({ draftId: "draft-1", ownerId: "user-1", revision, values: { test: val } }),
    async persist(snapshot) {
      attempts.push(snapshot);
      if (failure) throw Error("conflict");
      if (snapshot.revision !== revision) throw Error("conflict");
      return { revision: (revision ?? 0) + 1 };
    },
    setTimer(fn, ms) { const id = ++sequence; timers.set(id, fn); return id; },
    clearTimer(id) { timers.delete(id); },
    onSaved(r) { revision = r; },
    onFailure(e) { errors.push(e); },
  });
  return {
    save, attempts, errors, timers, change(v) { val = v; save.changed(); },
    lock() { unlocked = false; }, unlock() { unlocked = true; save.retry(); },
    fail(v) { failure = v; },
    async tick() { const callbacks = [...timers.values()]; timers.clear(); for (const fn of callbacks) fn(); await settle(); },
    get revision() { return revision; },
  };
}
test("rapid edits coalesce into one encrypted-store persist and never queue/send", async () => {
  const f = env();
  f.change("a"); f.change("ab"); f.change("abc");
  assert.equal(f.timers.size, 1);
  await f.tick();
  assert.equal(f.attempts.length, 1);
  assert.equal(f.attempts[0].values.test, "abc");
  assert.equal(f.revision, 1);
  assert.equal(f.save.hasUnsavedChanges, false);
  f.save.stop();
});
test("locked vault cannot persist plaintext; unlocking resumes pending changes", async () => {
  const f = env();
  f.lock(); f.change("private");
  await f.tick();
  assert.equal(f.attempts.length, 0);
  assert.equal(f.save.hasUnsavedChanges, true);
  assert.deepEqual(f.errors, ["locked"]);
  f.unlock(); await f.tick();
  assert.equal(f.attempts.length, 1);
  f.save.stop();
});
test("conflict is blocked until explicitly resolved, never stale-overwritten", async () => {
  const f = env();
  f.fail(true); f.change("edited"); await f.tick();
  assert.equal(f.attempts.length, 1);
  assert.deepEqual(f.errors, ["conflict"]);
  assert.equal(f.timers.size, 0);
  f.fail(false); f.save.retry(); await f.tick();
  assert.equal(f.attempts.length, 2);
  assert.equal(f.revision, 1);
  f.save.stop();
});
test("stopping before a scheduled save cancels work", async () => {
  const f = env(); f.change("draft");
  f.save.stop(); await f.tick();
  assert.equal(f.attempts.length, 0);
  assert.equal(f.save.hasUnsavedChanges, true);
});
