// MF-07: media aritmética simple EXACTA (sin coma flotante) con dos decimales, redondeo «mitad hacia arriba» (alejándose de cero). Es la misma regla que aplica el backend (fuente de verdad); aquí solo sirve para
// MOSTRAR los promedios mientras se digita. Un promedio sin valores es null (nunca 0). Todo es PURO. (BigInt sin literales: el proyecto compila por debajo de ES2020.)
const NUMBER = /^(-?)(\d+)(?:\.(\d+))?$/;
const ZERO = BigInt(0), ONE = BigInt(1), TWO = BigInt(2), TEN = BigInt(10), HUNDRED = BigInt(100);

export function meanTwoDecimals(values: readonly string[]): string | null {
    if (values.length === 0) return null;
    const parsed = values.map((text) => NUMBER.exec(text.trim().replace(",", ".")));
    if (parsed.some((m) => m === null)) return null;
    const rows = parsed.map((m) => ({ negative: m![1] === "-", digits: BigInt(m![2] + (m![3] ?? "")), scale: (m![3] ?? "").length }));
    const scale = Math.max(...rows.map((r) => r.scale));
    const total = rows.reduce((sum, r) => sum + (r.negative ? -ONE : ONE) * r.digits * TEN ** BigInt(scale - r.scale), ZERO);
    const numerator = total * HUNDRED, denominator = BigInt(rows.length) * TEN ** BigInt(scale);
    const negative = numerator < ZERO, absolute = negative ? -numerator : numerator;
    const cents = (TWO * absolute + denominator) / (TWO * denominator); // mitad hacia arriba sobre el valor absoluto
    const text = cents.toString().padStart(3, "0");
    return `${negative && cents !== ZERO ? "-" : ""}${text.slice(0, -2)}.${text.slice(-2)}`;
}

/** Promedio de cada grupo de claves (`means`: clave del calculado -> claves de las mediciones) usando solo valores digitados; si falta alguno, null. Visualización: el backend es la fuente de verdad. */
export function previewMeans(means: Readonly<Record<string, readonly string[]>>, values: Readonly<Record<string, string | undefined>>): Record<string, string | null> {
    return Object.fromEntries(Object.entries(means).map(([key, sources]) => {
        const given = sources.map((source) => values[source]?.trim() ?? "");
        return [key, given.every((v) => v !== "") ? meanTwoDecimals(given) : null];
    }));
}

/** Porcentaje exacto `numerador / denominador × 100` con dos decimales (mitad hacia arriba, alejándose de cero). Sin denominador, con denominador cero o con un valor no numérico: null (nunca se inventa un resultado). Visualización: el backend es la fuente de verdad. */
export function percentTwoDecimals(numerator: string | undefined, denominator: string | undefined): string | null {
    const parse = (text: string | undefined) => { const m = NUMBER.exec((text ?? "").trim().replace(",", ".")); return m ? { negative: m[1] === "-", digits: BigInt(m[2] + (m[3] ?? "")), scale: (m[3] ?? "").length } : null; };
    const n = parse(numerator), d = parse(denominator);
    if (!n || !d || d.digits === ZERO) return null;
    const top = n.digits * TEN ** BigInt(d.scale) * BigInt(10000), bottom = d.digits * TEN ** BigInt(n.scale);
    const cents = (TWO * top + bottom) / (TWO * bottom);
    const negative = n.negative !== d.negative && cents !== ZERO;
    const text = cents.toString().padStart(3, "0");
    return `${negative ? "-" : ""}${text.slice(0, -2)}.${text.slice(-2)}`;
}
