// MF-13-03B PR6: capacidades de OT que el SERVIDOR confirma a la sesión. PURO.
//
// La creación multimáquina solo se OFRECE si el backend lo confirma (compuerta WORK_ORDERS_MULTI_MACHINE_ENABLED, apagada por defecto). La interfaz no tiene su propia compuerta:
//  - no depende de una variable NEXT_PUBLIC (se compila en el navegador y no garantiza lo que el servidor autoriza);
//  - un 422 (incluido MULTI_MACHINE_DISABLED) NUNCA enciende nada, ni ningún otro error;
//  - lo ausente, mal formado o no estrictamente `true` es «apagado».
// Hoy no existe un contrato para consultarlo (ver docs/MF-13-03B-PR6-ui-ot-multimaquina.md, endpoint propuesto): mientras tanto la aplicación pasa NO_CAPABILITIES y la
// creación queda en el flujo tradicional de una sola máquina.

export type WorkOrderCapabilities = { readonly multiMachine: boolean };

export const NO_CAPABILITIES: WorkOrderCapabilities = Object.freeze({ multiMachine: false });

export function parseCapabilities(value: unknown): WorkOrderCapabilities {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return NO_CAPABILITIES;
    return (value as Record<string, unknown>).multi_machine === true ? Object.freeze({ multiMachine: true }) : NO_CAPABILITIES;
}

// Se ofrece multimáquina solo con confirmación del servidor, permiso de gestión y más de una máquina elegible para la sesión.
export function multiMachineOffered(capabilities: WorkOrderCapabilities, canManageOrders: boolean, machineCount: number): boolean {
    return capabilities.multiMachine === true && canManageOrders && machineCount > 1;
}
