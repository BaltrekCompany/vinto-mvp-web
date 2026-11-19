// OFF-04.3: engine scenarios against the in-memory store (same transition rules as the IndexedDB store).
import assert from "node:assert/strict";
import { test } from "node:test";
import { createMemorySyncStore } from "./off-04-sync-memory-store.ts";
import { runSyncScenarios } from "./off-04-sync-scenarios.ts";

test("sync engine scenarios (in-memory store)", async () => {
    const stores = [];
    const results = await runSyncScenarios({
        makeStore: () => { const s = createMemorySyncStore(); stores.push(s); return s; },
        tamperCiphertext: async (id) => {
            for (const s of stores) { const r = s.rows.get(id); if (r) s.rows.set(id, { ...r, sealed: { ...r.sealed, ciphertext: (r.sealed.ciphertext[0] === "A" ? "B" : "A") + r.sealed.ciphertext.slice(1) } }); }
        },
        tamperHash: async (id) => { for (const s of stores) { const r = s.rows.get(id); if (r) s.rows.set(id, { ...r, payloadSha256: "0".repeat(64) }); } },
    });
    for (const r of results) console.log((r.ok ? "PASS " : "FAIL ") + r.name + (r.detail ? " :: " + r.detail : ""));
    assert.deepEqual(results.filter(r => !r.ok), []);
    assert.ok(results.length >= 24);
});
