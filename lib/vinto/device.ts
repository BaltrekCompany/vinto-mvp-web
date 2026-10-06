// Clave técnica estable del navegador/dispositivo (device_key). Es la ÚNICA persistencia nueva de la captura central F6: un UUID
// aleatorio, sin usuario, sesión, OT ni valores. Sobrevive a refresh, logout/login y reinicio del navegador (localStorage). PURO:
// el almacenamiento se inyecta para poder probarlo con Node.

export const DEVICE_KEY_STORAGE = "vinto-device-key";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (value: unknown): value is string => typeof value === "string" && UUID.test(value);

type DeviceStorage = Pick<Storage, "getItem" | "setItem">;

// Si el almacenamiento está bloqueado, la clave vive en memoria durante la sesión de la página (no se generan claves nuevas por envío).
let memoryKey: string | null = null;

function defaultStorage(): DeviceStorage | null {
    try { return typeof localStorage === "undefined" ? null : localStorage; } catch { return null; }
}

export function getDeviceKey(storage: DeviceStorage | null = defaultStorage(), generate: () => string = () => crypto.randomUUID()): string {
    try {
        const stored = storage?.getItem(DEVICE_KEY_STORAGE);
        if (isUuid(stored)) return stored;
    } catch { /* almacenamiento inaccesible: se usa la clave en memoria */ }
    const key = memoryKey ?? generate();
    memoryKey = key;
    try { storage?.setItem(DEVICE_KEY_STORAGE, key); } catch { /* no persistible: queda en memoria */ }
    return key;
}

// Solo para pruebas.
export function resetDeviceKeyMemory() { memoryKey = null; }
