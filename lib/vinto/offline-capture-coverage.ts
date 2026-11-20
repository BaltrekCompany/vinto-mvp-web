/**
 * VINTO OFF-04.8E — coverage rule for a MAXIMUM eight-hour offline shift.
 *
 * A signed CAPTURE-capable scope lives for 24 hours on the server. The PWA
 * proactively renews it while connected when <=12 hours remain, providing
 * four hours of buffer for the eight-hour shift. This is an advisory UI
 * readiness test, NOT server authorization (server checks signature, expiry,
 * active snapshot and CURRENT grants again at upload).
 *
 * Existing frozen captures retain their original snapshot. Routine renewal
 * must NEVER overwrite/rebind their capture IDs, payloads or scope IDs.
 */
export const MAX_OFFLINE_HOURS = 8;
export const CAPTURE_SCOPE_TTL_HOURS = 24;
export const RENEW_WITHIN_HOURS = 12;
const HOUR_MS = 60 * 60 * 1000;
export const MAX_OFFLINE_MS = MAX_OFFLINE_HOURS * HOUR_MS;
export const RENEW_WITHIN_MS = RENEW_WITHIN_HOURS * HOUR_MS;

export type CoverageStatus = "missing" | "expired" | "insufficient" | "refresh_soon" | "ready";
export type ScopeCoverage = Readonly<{
    status: CoverageStatus;
    /** Does the currently verified scope cover a FULL 8-hour shift starting now? */
    coversFullShift: boolean;
    /** When connected and authenticated, request a new server-issued scope. */
    shouldRenewOnline: boolean;
    /** A local encrypted draft can be saved even if readiness is absent. */
    maySaveDraft: true;
}>;

export function evaluateCaptureScopeCoverage(
    verifiedExpiryMs: number | null, nowMs: number,
): ScopeCoverage {
    if (!Number.isFinite(nowMs)) throw new TypeError("invalid clock");
    const result = (status: CoverageStatus, coversFullShift: boolean, shouldRenewOnline: boolean): ScopeCoverage =>
        ({ status, coversFullShift, shouldRenewOnline, maySaveDraft: true });
    if (verifiedExpiryMs === null || !Number.isFinite(verifiedExpiryMs)) return result("missing", false, true);
    const remaining = verifiedExpiryMs - nowMs;
    if (remaining <= 0) return result("expired", false, true);
    // Conservatively reject equality to the shift limit; network/reconciliation needs time.
    if (remaining <= MAX_OFFLINE_MS) return result("insufficient", false, true);
    if (remaining <= RENEW_WITHIN_MS) return result("refresh_soon", true, true);
    return result("ready", true, false);
}

/** The UI may display these states, but MUST NOT use them as authz on the server. */
export type OfflineCoverageDisplay = "ready" | "renewing" | "online_needed" | "expired" | "pending";
export function coverageDisplay(coverage: ScopeCoverage, online: boolean, renewing: boolean): OfflineCoverageDisplay {
    if (renewing && online) return "renewing";
    if (coverage.status === "missing") return online ? "pending" : "online_needed";
    if (coverage.status === "expired") return "expired";
    if (!coverage.coversFullShift) return online ? "pending" : "online_needed";
    return "ready";
}
