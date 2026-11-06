// MF-13-03B PR6: capacidades de OT que el SERVIDOR confirma a la sesión. PURO.
//
// La creación multimáquina solo se OFRECE si el backend lo confirma (compuerta WORK_ORDERS_MULTI_MACHINE_ENABLED, apagada por defecto). La interfaz no tiene su propia compuerta:
//  - no depende de una variable NEXT_PUBLIC (se compila en el navegador y no garantiza lo que el servidor autoriza);
//  - un 422 (incluido MULTI_MACHINE_DISABLED) NUNCA enciende nada, ni ningún otro error;
//  - lo ausente, mal formado o no estrictamente `true` es «apagado».
// MF-13-03B PR6.1: el servidor lo publica en GET /api/work-orders/capabilities ({"multi_machine": bool}, solo Jefatura y Supervisión, sin caché). Mientras la consulta carga, falla
// (401, 403, 404, 5xx, red) o devuelve algo que no es exactamente ese contrato, la aplicación usa NO_CAPABILITIES y la creación queda en el flujo tradicional de una sola máquina.
// La respuesta NO autoriza la creación: el POST vuelve a validar permisos, máquinas, artículos y la compuerta.

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

// Parser ESTRICTO de la respuesta del endpoint: debe ser un objeto con `multi_machine` booleano; cualquier otra cosa es una respuesta inválida (null) y el cliente la trata como
// fallo, es decir, capacidad apagada. Las claves adicionales se ignoran: nunca amplían nada.
export function parseCapabilitiesResponse(value: unknown): WorkOrderCapabilities | null {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
    const flag = (value as Record<string, unknown>).multi_machine;
    if (typeof flag !== "boolean") return null;
    return flag ? Object.freeze({ multiMachine: true }) : NO_CAPABILITIES;
}

export type CapabilityStatus = "idle" | "loading" | "ready" | "error";
type CapabilityView = { status: "idle" } | { status: "loading" } | { status: "ready"; data: WorkOrderCapabilities } | { status: "error" };

// Vista de la consulta -> capacidades efectivas. Solo un recurso `ready` con `true` habilita; idle, loading y error son «apagado» (falla cerrado).
export function capabilitiesOf(view: CapabilityView): { capabilities: WorkOrderCapabilities; status: CapabilityStatus } {
    if (view.status === "ready") return { capabilities: view.data.multiMachine === true ? view.data : NO_CAPABILITIES, status: "ready" };
    return { capabilities: NO_CAPABILITIES, status: view.status };
}

// MF-13-03B PR7: el botón «Activar todas las líneas» exige la confirmación del servidor (`multi_machine: true`), el permiso de ACTIVAR (`assignment.manage`; crear OT sigue siendo
// `work_order.manage`) y una OT publicada o en ejecución. Cualquier otra cosa lo deshabilita. Es solo presentación: el backend vuelve a verificarlo todo.
export function massActivationOffered(capabilities: WorkOrderCapabilities, canManageAssignments: boolean, orderStatus: string): boolean {
    return capabilities.multiMachine === true && canManageAssignments === true && (orderStatus === "published" || orderStatus === "in_progress");
}
