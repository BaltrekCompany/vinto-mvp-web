// node --test scripts/pra-dialog-a11y.test.mjs
// MF-13-03B PR-A: retorno del foco (DEF-1) y contraste (DEF-2) del diálogo de activación masiva. Lógica pura + garantías de fuente + matemática WCAG de los pares de color usados.
// El comportamiento real (foco, Escape, tema claro/oscuro, contraste medido en el navegador) lo prueba scripts/e2e/pra-e2e.mjs; esto NO es un E2E.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { isFocusable, pickReturnTarget } from "../lib/vinto/focus-return.ts";

const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
const noComments = (text) => text.replace(/\/\/.*$/gm, "");
const el = (over = {}) => ({ isConnected: true, disabled: false, getAttribute: () => null, getClientRects: () => ({ length: 1 }), focus() { this.focused = true; }, ...over });

// ---- DEF-1: a dónde vuelve el foco -------------------------------------------------------------------------------------------------------------------------------------

test("an enabled, connected, visible invoker is a valid focus target", () => {
  const invoker = el();
  assert.equal(isFocusable(invoker), true);
  assert.equal(pickReturnTarget([invoker, el()]), invoker, "the invoker wins over later candidates");
});

test("an invoker that is gone, disabled, hidden or aria-hidden is never focused: the next safe target is used", () => {
  const card = el(), panel = el();
  for (const bad of [el({ isConnected: false }), el({ disabled: true }), el({ getClientRects: () => ({ length: 0 }) }), el({ getAttribute: (n) => (n === "aria-hidden" ? "true" : null) }),
    el({ getAttribute: (n) => (n === "aria-disabled" ? "true" : null) }), null, undefined]) {
    assert.equal(isFocusable(bad), false);
    assert.equal(pickReturnTarget([bad, card, panel]), card);
  }
  assert.equal(pickReturnTarget([el({ isConnected: false }), el({ disabled: true }), panel]), panel);
});

test("with no usable target nothing is focused (never a missing or disabled element)", () => {
  assert.equal(pickReturnTarget([]), null);
  assert.equal(pickReturnTarget([null, undefined, el({ isConnected: false }), el({ disabled: true })]), null);
});

test("the helper only decides: it never calls focus() itself", () => {
  const invoker = el();
  pickReturnTarget([invoker]);
  assert.equal(invoker.focused, undefined);
});

// ---- cableado (garantías de fuente) ------------------------------------------------------------------------------------------------------------------------------------

test("the dialog returns focus from Radix's own onCloseAutoFocus hook, only preventing the default when it has a real target", () => {
  const source = noComments(read("components/vinto/activate-all-dialog.tsx"));
  assert.match(source, /onCloseAutoFocus=\{event => \{/);
  assert.match(source, /pickReturnTarget\(returnFocusTargets\?\.\(\) \?\? \[\]\)/);
  assert.match(source, /if \(target\) \{ event\.preventDefault\(\); target\.focus\(\); \}/);
});

test("PR7 guarantees are intact: Escape and outside clicks stay blocked while the confirmation is in flight, the close button is hidden, initial focus is on «Cerrar» (DOM order)", () => {
  const source = noComments(read("components/vinto/activate-all-dialog.tsx"));
  assert.match(source, /onInteractOutside=\{event => \{ if \(state\.phase === "confirming"\) event\.preventDefault\(\); \}\}/);
  assert.match(source, /onEscapeKeyDown=\{event => \{ if \(state\.phase === "confirming"\) event\.preventDefault\(\); \}\}/);
  assert.match(source, /showCloseButton=\{state\.phase !== "confirming"\}/);
  assert.match(source, /onOpenChange=\{open => \{ if \(!open && state\.phase !== "confirming"\) onClose\(\); \}\}/);
  assert.ok(source.indexOf(">Cerrar</Button>") < source.indexOf("Actualizar vista previa") && source.indexOf("Actualizar vista previa") < source.indexOf("Confirmar activación de"));
  assert.match(source, /if \(state\.phase !== "preview" \|\| !canConfirmPlan\(state\.plan\) \|\| guard\.busy\(\)\) return;/);
});

test("the panel remembers the invoker, offers its card and the panel as fallbacks, and those fallbacks are programmatically focusable", () => {
  const source = noComments(read("components/vinto/bobinas-programming.tsx"));
  assert.match(source, /invoker\.current = event\.currentTarget;/);
  assert.match(source, /returnFocusTargets=\{\(\) => \[invoker\.current, invoker\.current\?\.closest<HTMLElement>\("\[data-work-order\]"\), panel\.current\]\}/);
  assert.match(source, /<div ref=\{panel\} tabIndex=\{-1\}/);
  assert.match(source, /data-work-order=\{order\.number\} tabIndex=\{-1\}/);
});

test("the targets are read AT CLOSE (a function), not captured at open, so a vanished invoker is detected", () => {
  assert.match(noComments(read("components/vinto/bobinas-programming.tsx")), /returnFocusTargets=\{\(\) =>/);
});

// ---- DEF-2: contraste -------------------------------------------------------------------------------------------------------------------------------------------------------

test("the dialog no longer uses fixed light-only slate colours: it follows the theme tokens", () => {
  const source = noComments(read("components/vinto/activate-all-dialog.tsx"));
  assert.doesNotMatch(source, /slate-\d/);
  for (const token of ["bg-muted", "text-foreground", "text-muted-foreground"]) assert.ok(source.includes(token), token);
});

test("every fixed-colour alert has an explicit dark variant, and the confirm button has an explicit white text", () => {
  const source = noComments(read("components/vinto/activate-all-dialog.tsx"));
  assert.equal((source.match(/bg-red-50/g) ?? []).length, (source.match(/dark:bg-red-950/g) ?? []).length);
  assert.equal((source.match(/bg-emerald-50/g) ?? []).length, (source.match(/dark:bg-emerald-950/g) ?? []).length);
  assert.ok((source.match(/dark:bg-red-950/g) ?? []).length >= 2 && (source.match(/dark:bg-emerald-950/g) ?? []).length >= 1);
  assert.match(source, /className="bg-\[#146b4f\] text-white hover:bg-\[#0f5a41\]"/);
});

test("the global theme was not touched by this change", () => {
  const css = read("app/globals.css");
  assert.match(css, /--muted-foreground: #475569;/);
  assert.match(css, /--foreground: #ededed;/);
});

// WCAG 2.x: contraste entre dos colores hexadecimales.
const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const lum = (hex) => { const n = parseInt(hex.slice(1), 16); return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

test("the colour pairs the dialog uses reach WCAG AA (4.5:1) in the light theme", () => {
  for (const [name, fg, bg] of [["foreground on page", "#0f172a", "#f3f6f4"], ["muted text on page", "#475569", "#f3f6f4"], ["foreground on muted", "#0f172a", "#f5f5f5"], ["white on confirm green", "#ffffff", "#146b4f"],
    ["red alert", "#7f1d1d", "#fef2f2"], ["emerald alert", "#064e3b", "#ecfdf5"]]) assert.ok(ratio(fg, bg) >= 4.5, `${name}: ${ratio(fg, bg).toFixed(2)}`);
});

test("the colour pairs the dialog uses reach WCAG AA (4.5:1) in the dark theme", () => {
  for (const [name, fg, bg] of [["foreground on page", "#ededed", "#0a0a0a"], ["muted text on page", "#a1a1a1", "#0a0a0a"], ["foreground on muted", "#ededed", "#262626"], ["white on confirm green", "#ffffff", "#146b4f"],
    ["red alert", "#fee2e2", "#450a0a"], ["emerald alert", "#d1fae5", "#022c22"]]) assert.ok(ratio(fg, bg) >= 4.5, `${name}: ${ratio(fg, bg).toFixed(2)}`);
});

test("the defect being fixed is real: the old pair (dark foreground token on a light fixed fill) fails badly", () => {
  assert.ok(ratio("#ededed", "#f8fafc") < 1.2, `old summary: ${ratio("#ededed", "#f8fafc").toFixed(2)}`); // text-foreground (dark theme) on bg-slate-50
  assert.ok(ratio("#475569", "#0a0a0a") < 3, "old PV text (slate-600) on the dark dialog");
});
