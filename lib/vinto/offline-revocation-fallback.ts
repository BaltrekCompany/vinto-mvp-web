/**
 * OFF-03C.4-R1: last-resort, fail-closed memory of a revocation that could NOT be sealed
 * into IndexedDB (sealing failed, transaction aborted, quota exceeded...).
 *
 * It stores ONLY a profile key (owner:device, already present in this browser) and the
 * millisecond time at which the online refusal was observed: no ciphertext, no permission,
 * no form, no token. Losing or tampering with it can only fail OPEN to the same historical
 * view that existed before OFF-03C.4; it can never grant anything.
 *
 * Two layers: process memory (always) and localStorage (best effort, survives a restart).
 * LIMIT: if the browser accepts no writes at all, nothing survives a restart; only the
 * current page context stays closed. That limit is documented in OFF-03C4.
 */
const PREFIX = "vinto:off03c4:revoked:";
const memory = new Map<string, number>();

function parse(raw: string | null): number | null {
    if (raw === null || !/^\d{10,16}$/.test(raw)) return null;
    const n = Number(raw);
    return Number.isSafeInteger(n) ? n : null;
}

export function noteUnrecordedRevocation(profileId: string, observedAtMs: number): void {
    if (!Number.isSafeInteger(observedAtMs) || observedAtMs <= 0) return;
    memory.set(profileId, Math.max(memory.get(profileId) ?? 0, observedAtMs));
    try {
        const previous = parse(localStorage.getItem(PREFIX + profileId));
        if (previous === null || previous < observedAtMs) localStorage.setItem(PREFIX + profileId, String(observedAtMs));
    } catch { /* storage refuses writes: the in-memory layer still closes this context */ }
}

/** Most recent observed refusal that has not been sealed, or null. */
export function unrecordedRevocationAt(profileId: string): number | null {
    let stored: number | null = null;
    try { stored = parse(localStorage.getItem(PREFIX + profileId)); } catch { stored = null; }
    const mem = memory.get(profileId) ?? null;
    if (stored === null) return mem;
    return mem === null ? stored : Math.max(stored, mem);
}

/** Forget a refusal that was sealed durably, or that a LATER verified online renewal superseded. */
export function clearUnrecordedRevocation(profileId: string, upToMs: number): void {
    const memNow = memory.get(profileId);
    if (memNow !== undefined && memNow <= upToMs) memory.delete(profileId);
    try {
        const stored = parse(localStorage.getItem(PREFIX + profileId));
        if (stored !== null && stored <= upToMs) localStorage.removeItem(PREFIX + profileId);
    } catch { /* nothing to clear */ }
}
