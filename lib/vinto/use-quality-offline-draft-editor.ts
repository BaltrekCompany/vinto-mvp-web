"use client";

/**
 * Shared draft handling for the existing Quality forms.
 * Never creates credentials, device enrolment or an offline CAPTURE grant.
 * The port is provided only after verified preparation and vault unlock.
 */
import { useEffect, useRef, useState } from "react";
import { beginSessionOperation } from "./session-epoch";

export type QualityDraftValues = Readonly<Record<string, string | boolean>>;
export type QualityDraftSnapshot = Readonly<{
  revision: number;
  frozen: boolean;
  values: QualityDraftValues;
}>;
export type QualityDraftPort = Readonly<{
  recover: () => Promise<QualityDraftSnapshot | null>;
  save: (values: QualityDraftValues, expectedRevision: number) => Promise<QualityDraftSnapshot>;
}>;
type Phase = "inactive" | "loading" | "ready" | "frozen" | "missing" | "error";

const same = (a: QualityDraftValues, b: QualityDraftValues): boolean => {
  const ka = Object.keys(a).sort(), kb = Object.keys(b).sort();
  return ka.length === kb.length &&
    ka.every((key, i) => key === kb[i] && a[key] === b[key]);
};

export function useQualityOfflineDraftEditor<T extends Record<string, string>>(
  initial: () => T,
  port: QualityDraftPort | undefined,
  active: boolean,
) {
  const [values, setValues] = useState<T>(initial);
  const [phase, setPhase] = useState<Phase>("inactive");
  const [busy, setBusy] = useState(false);
  const revision = useRef<number | null>(null);
  const lastSaved = useRef<QualityDraftValues | null>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const failed = useRef(false);
  const ready = useRef(false);
  const current = useRef<T>(values);

  useEffect(() => {
    if (!active || !port) return;
    let cancelled = false;
    const live = beginSessionOperation();
    ready.current = false;
    failed.current = false;
    revision.current = null;
    lastSaved.current = null;
    Promise.resolve().then(() => {
      if (cancelled || !live()) return null;
      setPhase("loading");
      return port.recover();
    }).then(snapshot => {
      if (cancelled || !live()) return;
      if (!snapshot) { setPhase("missing"); return; }
      if (!Number.isSafeInteger(snapshot.revision) || snapshot.revision < 1) {
        setPhase("error"); return;
      }
      const template = initial();
      const keys = Object.keys(template);
      if (Object.entries(snapshot.values).some(([k,v]) =>
        !keys.includes(k) || typeof v !== "string")) {
        setPhase("error"); return;
      }
      if (snapshot.frozen) { setPhase("frozen"); return; }
      revision.current = snapshot.revision;
      const restored = {...template, ...snapshot.values} as T;
      lastSaved.current = restored;
      current.current = restored;
      setValues(restored);
      ready.current = true;
      setPhase("ready");
    }).catch(() => { if (!cancelled && live()) setPhase("error"); });
    return () => { cancelled = true; ready.current = false; };
    // A changed port signals an explicitly different prepared identity/context.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [port, active]);

  // Serialize encrypted saves; never store plaintext, lose the CAS revision or
  // restart from a new draft after an uncertain write.
  useEffect(() => {
    if (!active || !port || !ready.current || failed.current ||
        !lastSaved.current || same(lastSaved.current, values)) return;
    const snapshot = {...values};
    queue.current = queue.current.then(async () => {
      if (failed.current) return;
      const expected = revision.current;
      if (expected === null) throw new Error("offline_revision_missing");
      const next = await port.save(snapshot, expected);
      if (next.frozen || !same(next.values, snapshot))
        throw new Error("offline_draft_conflict");
      revision.current = next.revision;
      lastSaved.current = snapshot;
    }).catch(() => {
      failed.current = true;
      ready.current = false;
      setPhase("error");
    }).finally(() => setBusy(false));
    // Async effect work is only after the render; the save cannot be skipped
    // when edits occur while an earlier save is in flight.
    Promise.resolve().then(() => setBusy(true));
  }, [active, port, values]);

  const change = (updater: (previous: T) => T) => {
    if (active && (phase !== "ready" || failed.current)) return;
    const next = updater(current.current);
    current.current = next;
    setValues(next);
  };
  const flush = async (): Promise<boolean> => {
    if (!active || !port || phase !== "ready" || failed.current) return false;
    await queue.current;
    return !failed.current && same(lastSaved.current ?? {}, current.current);
  };
  return {
    values, change, flush,
    blocked: active && (phase !== "ready" || busy || failed.current),
    status: phase, busy,
  };
}
