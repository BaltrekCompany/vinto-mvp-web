/** OFF-04.8A: event-driven, opt-in sync scheduling. DOES NOT send by itself.
 *
 * The production caller must provide an unlocked owner-scoped queue, a frozen
 * draft-to-queue bridge and the authenticated sync engine. No worker is started
 * without start(), and no network operation occurs if the client is offline.
 *
 * This module is deliberately NOT mounted in the QA laboratory or production.
 */
export type AutoSyncResult = Readonly<{
    paused: string | null;
    stopped: string | null;
    counts: Readonly<{ queued: number; retry_wait: number }>;
}>;

export type AutoSyncDeps = Readonly<{
    online: () => boolean;
    unlocked: () => boolean;
    /** Called only for the original unlocked owner's pending local drafts. */
    prepareQueue: () => Promise<void>;
    /** Existing idempotent engine; it checks session and original author. */
    sync: () => Promise<AutoSyncResult>;
    setTimer: (handler: () => void, delayMs: number) => unknown;
    clearTimer: (timer: unknown) => void;
    subscribe: (name: "online" | "focus" | "visible", handler: () => void) => () => void;
    onError?: (reason: "preparation_failed" | "sync_failed") => void;
}>;

export type AutoSyncScheduler = Readonly<{
    start(): void;
    notifyReady(): void;
    stop(): void;
}>;

const RECHECK_MS = 30_000;

export function createAutoSyncScheduler(deps: AutoSyncDeps): AutoSyncScheduler {
    let started = false;
    let running = false;
    let rerun = false;
    let timer: unknown = null;
    let unsubs: Array<() => void> = [];

    const cancel = () => {
        if (timer !== null) {
            deps.clearTimer(timer);
            timer = null;
        }
    };

    const schedule = (delay: number) => {
        if (!started || !deps.online() || !deps.unlocked()) return;
        cancel();
        timer = deps.setTimer(() => {
            timer = null;
            void attempt();
        }, delay);
    };

    const attempt = async (): Promise<void> => {
        if (!started || !deps.online() || !deps.unlocked()) return;
        if (running) {
            rerun = true;
            return;
        }
        running = true;
        try {
            try {
                await deps.prepareQueue();
            } catch {
                deps.onError?.("preparation_failed");
                schedule(RECHECK_MS);
                return;
            }
            if (!started || !deps.online() || !deps.unlocked()) return;
            let result: AutoSyncResult;
            try {
                result = await deps.sync();
            } catch {
                deps.onError?.("sync_failed");
                schedule(RECHECK_MS);
                return;
            }
            // A paused session is not retried aggressively. Login/unlock calls
            // notifyReady(); pending data remains untouched.
            if (!result.paused && (result.stopped || result.counts.queued > 0 || result.counts.retry_wait > 0)) {
                schedule(RECHECK_MS);
            }
        } finally {
            running = false;
            if (rerun) {
                rerun = false;
                // User action / restored connectivity takes precedence over a
                // delayed attempt, but never starts two runners concurrently.
                cancel();
                if (started && deps.online() && deps.unlocked()) schedule(0);
            }
        }
    };

    const wake = () => {
        if (!started || !deps.online() || !deps.unlocked()) return;
        cancel();
        if (running) {
            rerun = true;
        } else {
            schedule(0);
        }
    };

    return {
        start() {
            if (started) return;
            started = true;
            unsubs = ["online", "focus", "visible"].map(name =>
                deps.subscribe(name as "online" | "focus" | "visible", wake));
            wake();
        },
        notifyReady: wake,
        stop() {
            started = false;
            rerun = false;
            cancel();
            for (const unsubscribe of unsubs) unsubscribe();
            unsubs = [];
        },
    };
}
