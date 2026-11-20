/** OFF-04.8E: opt-in renewal orchestration for eight-hour offline shifts.
 * All network/auth is injected. Never refreshes without original owner's
 * unlocked vault and current online authentication. An unsuccessful renewal
 * cannot delete/rebind existing frozen drafts or pending captures.
 */
import { evaluateCaptureScopeCoverage } from "./offline-capture-coverage.ts";

export type CaptureRenewalDeps = Readonly<{
  online: () => boolean;
  unlocked: () => boolean;
  authenticatedOriginalOwner: () => Promise<boolean>;
  verifiedExpiryMs: () => number | null;
  /** Server issues and persists a NEW signed snapshot, never mutates old ones. */
  renew: () => Promise<void>;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (id: unknown) => void;
  subscribe: (event: "online" | "focus", callback: () => void) => () => void;
  onError?: () => void;
}>;

export function createCaptureScopeRenewal(deps: CaptureRenewalDeps) {
  let started = false;
  let busy = false;
  let timer: unknown = null;
  let unsubs: (() => void)[] = [];
  const clear = () => { if (timer !== null) deps.clearTimer(timer); timer = null; };
  const plan = (delay: number) => {
    clear();
    if (!started) return;
    timer = deps.setTimer(() => { timer = null; void tick(); }, delay);
  };
  const tick = async () => {
    if (!started || busy || !deps.online() || !deps.unlocked()) return;
    busy = true;
    try {
      if (await deps.authenticatedOriginalOwner()) {
        const status = evaluateCaptureScopeCoverage(deps.verifiedExpiryMs(), Date.now());
        if (status.shouldRenewOnline) await deps.renew();
      }
    } catch {
      deps.onError?.();
    } finally {
      busy = false;
      // Retry non-invasively while the page is active. No reissuance when ready.
      if (started) plan(60 * 60 * 1000);
    }
  };
  const wake = () => { if (started && deps.online() && deps.unlocked()) plan(0); };
  return {
    start() {
      if (started) return;
      started = true;
      unsubs = ["online", "focus"].map(event => deps.subscribe(event as "online" | "focus", wake));
      wake();
    },
    notifyAuthenticated: wake,
    stop() { started = false; clear(); for (const un of unsubs) un(); unsubs = []; },
  };
}
