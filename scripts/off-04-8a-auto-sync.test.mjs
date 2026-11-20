// OFF-04.8A: offline auto-sync scheduler contract. Pure fakes only; no browser or network.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createAutoSyncScheduler } from "../lib/vinto/offline-auto-sync.ts";

const tick = async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
};

function fixture() {
    const listeners = new Map();
    const timers = new Map();
    let serial = 0;
    let connected = false;
    let unlocked = false;
    let prepared = 0;
    let sent = 0;
    let result = { paused: null, stopped: null, counts: { queued: 0, retry_wait: 0 } };
    let failure = null;
    const problems = [];
    const scheduler = createAutoSyncScheduler({
        online: () => connected,
        unlocked: () => unlocked,
        async prepareQueue() { prepared++; if (failure === "prepare") throw Error("prepare"); },
        async sync() { sent++; if (failure === "sync") throw Error("sync"); return result; },
        setTimer(fn, delay) { const id = ++serial; timers.set(id, { fn, delay }); return id; },
        clearTimer(id) { timers.delete(id); },
        subscribe(name, fn) {
            const bucket = listeners.get(name) ?? new Set();
            bucket.add(fn); listeners.set(name, bucket);
            return () => bucket.delete(fn);
        },
        onError(reason) { problems.push(reason); },
    });
    return {
        scheduler, timers, problems,
        get prepared() { return prepared; },
        get sent() { return sent; },
        connect() { connected = true; for (const fn of listeners.get("online") ?? []) fn(); },
        disconnect() { connected = false; },
        unlock() { unlocked = true; scheduler.notifyReady(); },
        lock() { unlocked = false; },
        focus() { for (const fn of listeners.get("focus") ?? []) fn(); },
        async fire() {
            const next = timers.entries().next().value;
            if (next) { timers.delete(next[0]); next[1].fn(); await tick(); }
        },
        output(value) { result = value; },
        failure(value) { failure = value; },
    };
}

test("never sends before start, without Internet, or without an unlocked identity", async () => {
    const f = fixture();
    f.connect(); f.unlock(); assert.equal(f.timers.size, 0);
    f.scheduler.start(); assert.equal(f.timers.size, 1);
    f.disconnect(); await f.fire();
    assert.equal(f.prepared, 0); assert.equal(f.sent, 0);
    f.connect(); await f.fire();
    assert.equal(f.prepared, 1); assert.equal(f.sent, 1);
    f.scheduler.stop();
});

test("reconnection schedules automatically and no manual button is required", async () => {
    const f = fixture();
    f.scheduler.start(); f.unlock();
    assert.equal(f.sent, 0);
    f.connect(); assert.equal(f.timers.size, 1);
    await f.fire();
    assert.equal(f.prepared, 1); assert.equal(f.sent, 1);
    assert.equal(f.timers.size, 0);
    f.scheduler.stop();
});

test("retryable records are revisited; session pauses until reauthentication notification", async () => {
    const f = fixture();
    f.output({ paused: "session_invalid", stopped: null, counts: { queued: 2, retry_wait: 0 } });
    f.scheduler.start(); f.unlock(); f.connect(); await f.fire();
    assert.equal(f.sent, 1);
    assert.equal(f.timers.size, 0);
    f.output({ paused: null, stopped: null, counts: { queued: 1, retry_wait: 1 } });
    f.scheduler.notifyReady(); await f.fire();
    assert.equal(f.sent, 2); assert.equal(f.timers.size, 1);
    await f.fire(); assert.equal(f.sent, 3);
    f.scheduler.stop();
});

test("stop, lock and failed preparation never discard pending work or send without consent", async () => {
    const f = fixture();
    f.scheduler.start(); f.unlock(); f.connect();
    f.failure("prepare"); await f.fire();
    assert.equal(f.sent, 0); assert.deepEqual(f.problems, ["preparation_failed"]);
    f.lock(); await f.fire(); assert.equal(f.sent, 0);
    f.scheduler.stop(); assert.equal(f.timers.size, 0);
    f.focus(); assert.equal(f.timers.size, 0);
});
