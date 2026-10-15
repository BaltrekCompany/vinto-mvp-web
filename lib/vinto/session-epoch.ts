// Generación de sesión (INT-01B, corrección de auditoría): protege las DEVOLUCIONES de operaciones asíncronas (POST de capturas, lecturas posteriores) frente a un cambio de sesión.
//
// `deriveView` ya aísla los recursos de LECTURA por clave, pero una promesa de escritura que sigue en vuelo (la captura POST de la cuenta A) puede resolverse DESPUÉS de que la cuenta A cerró sesión y la B
// inició la suya, y entonces ejecutaría sus devoluciones (setAttempt(null), onSessionLost(), onSubmitted(), onAssignmentChanged()…) sobre el estado compartido de B. Cada operación toma una «guarda»
// al empezar (`beginSessionOperation`) y, tras CADA await, comprueba `live()` antes de tocar nada: si la generación cambió (resetSessionState → `bumpSessionEpoch`: cierre de sesión, sesión perdida o cambio de
// identidad), la respuesta es de otra sesión y se descarta SIN efectos. Una respuesta tardía de la MISMA sesión (la generación no cambió) sigue funcionando con normalidad.
//
// No guarda ni compara cookies, tokens ni identidades: solo un contador en memoria. No sustituye al backend, que sigue siendo la autoridad de permisos, ni toca el capture_id, la idempotencia ni la reconciliación:
// descartar una respuesta nunca cancela el POST (el servidor lo procesa igual) ni cambia el intento pendiente de la sesión vigente.
let epoch = 0;

export type OperationGuard = () => boolean;

export const currentSessionEpoch = (): number => epoch;

/** Invalida TODAS las operaciones en vuelo iniciadas antes de este momento. Lo llama el descarte único del estado de sesión (resetSessionState). */
export const bumpSessionEpoch = (): number => (epoch += 1);

/** Marca el inicio de una operación asíncrona y devuelve su guarda: `true` mientras la sesión que la originó siga siendo la vigente. */
export function beginSessionOperation(): OperationGuard {
    const started = epoch;
    return () => started === epoch;
}
