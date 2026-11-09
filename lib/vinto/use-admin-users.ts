"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { accountApi } from "@/lib/vinto/admin-api";
import {
    ACCOUNT_CLOSED, createAccountController,
    type AccountController, type AccountInput, type AccountOutcome, type AccountState, type AccountTarget,
} from "@/lib/vinto/admin-users";
import type { AdminResult } from "@/lib/vinto/admin";

// El controlador se libera al cambiar de sesión. Abortar un POST no garantiza revertir la BD;
// una respuesta tardía no puede afectar a la siguiente sesión ni producir éxito ficticio.
export function useAccountChange(onSettled: (result: AdminResult<AccountOutcome>, target: AccountTarget) => void) {
    const [state, setState] = useState<AccountState>(ACCOUNT_CLOSED);
    const settled = useRef(onSettled), controller = useRef<AccountController | null>(null);
    useEffect(() => { settled.current = onSettled; });
    useEffect(() => {
        const current = createAccountController(accountApi, setState, (result, target) => settled.current(result, target));
        controller.current = current;
        return () => { current.dispose(); controller.current = null; };
    }, []);
    const open = useCallback((target: AccountTarget) => controller.current?.open(target), []);
    const close = useCallback(() => controller.current?.close(), []);
    const submit = useCallback((input: AccountInput) => controller.current?.submit(input) ?? Promise.resolve(), []);
    return { state, open, close, submit };
}
