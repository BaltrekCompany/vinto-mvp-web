// MF-13-03B PR-A (DEF-1): a dónde vuelve el foco cuando se cierra un diálogo que se abre POR ESTADO (sin `DialogTrigger`). PURO: sin DOM propio, solo la forma mínima de un elemento.
//
// Causa confirmada: el `DialogContent` modal de Radix responde a `onCloseAutoFocus` con `event.preventDefault(); context.triggerRef.current?.focus()`. Sin `DialogTrigger`, `triggerRef.current` es
// `null`: se CANCELA la restauración por defecto y no se enfoca nada, así que el foco cae en <body>. Se corrige devolviéndolo explícitamente desde ese mismo gancho.
//
// Reglas: el invocador solo recibe el foco si sigue siendo útil (conectado, habilitado, visible y no oculto a la tecnología de apoyo); si ya no lo es (cambió la OT, los permisos, la sesión o las
// capacidades) se prueba el siguiente destino seguro; si ninguno sirve NO se enfoca nada (nunca un elemento inexistente o deshabilitado).

export type FocusTarget = {
    isConnected: boolean;
    disabled?: boolean;
    getAttribute?: (name: string) => string | null;
    getClientRects?: () => { length: number };
    focus: (options?: { preventScroll?: boolean }) => void;
};

export function isFocusable(element: FocusTarget | null | undefined): element is FocusTarget {
    if (!element || !element.isConnected || element.disabled) return false;
    if (element.getAttribute?.("aria-disabled") === "true" || element.getAttribute?.("aria-hidden") === "true") return false;
    if (element.getClientRects && element.getClientRects().length === 0) return false; // display:none o fuera del árbol visible
    return true;
}

// El primer destino aprovechable, en orden de preferencia (invocador, su tarjeta, el panel), o null.
export function pickReturnTarget(candidates: ReadonlyArray<FocusTarget | null | undefined>): FocusTarget | null {
    for (const candidate of candidates) if (isFocusable(candidate)) return candidate;
    return null;
}
