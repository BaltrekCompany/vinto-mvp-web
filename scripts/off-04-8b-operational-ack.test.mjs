// OFF-04.8B: technical receipt does not mean operationally registered.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createLocalVault } from "../lib/vinto/offline-vault.ts";
import { createSyncCapture, openSyncPayload } from "../lib/vinto/offline-sync-capture.ts";
import { syncNow } from "../lib/vinto/offline-sync-engine.ts";
import { createHttpSyncTransport } from "../lib/vinto/offline-sync-http-transport.ts";
import { createMemorySyncStore } from "./off-04-sync-memory-store.ts";

const OWNER = "11111111-1111-4111-8111-111111111111";
const DEVICE = "33333333-3333-4333-8333-333333333333";

async function makeEnv() {
    const identity = { ownerId: OWNER, deviceKey: DEVICE };
    const store = createMemorySyncStore();
    const { key } = await createLocalVault(identity, "VINTO-OFF-04-8B-synthetic-secret-10203");
    const record = await createSyncCapture(key, identity, store, {
        payload: { test: "synthetic" }, captureId: crypto.randomUUID(),
        formCode: "VINTO-P1-22", formVersion: 2, contextVersion: "synthetic-context", seq: 1,
    });
    const deps = (transport) => ({
        store, transport, identity, session: async () => ({ userId: OWNER }),
        openPayload: openSyncPayload(key, identity), tabId: crypto.randomUUID(),
        options: { requireOperationalAck: true },
    });
    return { record, store, deps };
}

test("accepted technical receipt alone is retained as review, not operational sync", async () => {
    const e = await makeEnv();
    const transport = {
        send: async () => ({ status: 201, body: { outcome: "created", server_id: "srv-1" } }),
        lookup: async () => ({ found: false }),
    };
    const r = await syncNow(e.deps(transport));
    assert.equal(r.counts.synced, 0);
    assert.equal(r.counts.requires_review, 1);
    assert.equal((await e.store.get(e.record.capture_id)).lastError, "operational_unconfirmed");
});

test("durable, correctly bound operational ack marks sync complete", async () => {
    const e = await makeEnv();
    const transport = {
        send: async () => ({ status: 201, body: { outcome: "created", server_id: "srv-1", operational_registered: true, operational_capture_id: e.record.capture_id } }),
        lookup: async () => ({ found: false }),
    };
    const r = await syncNow(e.deps(transport));
    assert.equal(r.counts.synced, 1);
    assert.equal(r.counts.requires_review, 0);
});

test("reconciliation must also include operational ack after lost response", async () => {
    const e = await makeEnv();
    const row = e.store.rows.get(e.record.capture_id);
    e.store.rows.set(e.record.capture_id, { ...row, uncertain: true });
    const transport = {
        send: async () => { throw Error("should-not-send"); },
        lookup: async () => ({ found: true, outcome: "accepted", server_id: "srv-1",
            operational_registered: true, operational_capture_id: e.record.capture_id }),
    };
    const r = await syncNow(e.deps(transport));
    assert.equal(r.reconciled, 1);
    assert.equal(r.sent, 0);
    assert.equal(r.counts.synced, 1);
});

test("old historical receipt reconciles only technically and cannot be marked operational", async () => {
    const e = await makeEnv();
    const row = e.store.rows.get(e.record.capture_id);
    e.store.rows.set(e.record.capture_id, { ...row, uncertain: true });
    const transport = {
        send: async () => { throw Error("should-not-send"); },
        lookup: async () => ({ found: true, outcome: "accepted", server_id: "srv-1" }),
    };
    const r = await syncNow(e.deps(transport));
    assert.equal(r.reconciled, 1);
    assert.equal(r.sent, 0);
    assert.equal(r.counts.requires_review, 1);
});

test("HTTP transport rejects false operational capture identity", async () => {
    const e = await makeEnv();
    const http = async ({ method, path, body }) => ({
        status: 201,
        json: {
            capture_id: e.record.capture_id, payload_sha256: e.record.payloadSha256,
            server_id: "srv-1", outcome: "created", technical_acceptance: true,
            operational_registered: true, operational_capture_id: crypto.randomUUID(),
        },
    });
    const r = await syncNow(e.deps(createHttpSyncTransport(http)));
    assert.equal(r.counts.synced, 0);
    assert.equal(r.counts.conflict, 1);
});
