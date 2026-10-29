// MF-12B: producto EXACTO (sin coma flotante) de dos números decimales escritos como texto, con dos decimales y redondeo «mitad hacia arriba» (alejándose de cero). Sirve solo para MOSTRAR un subtotal mientras
// se digita (P1-04: Cantidad de UM × Peso unitario real); nunca se envía ni se guarda. Un valor vacío o inválido da null (nunca 0). Todo es PURO. (BigInt sin literales: el proyecto compila por debajo de ES2020.)
const NUMBER = /^(-?)(\d+)(?:\.(\d+))?$/;
const ZERO = BigInt(0), TWO = BigInt(2), TEN = BigInt(10);

function parse(text: string): { negative: boolean; digits: bigint; scale: number } | null {
    const match = NUMBER.exec(text.trim().replace(",", "."));
    return match ? { negative: match[1] === "-", digits: BigInt(match[2] + (match[3] ?? "")), scale: (match[3] ?? "").length } : null;
}

export function productTwoDecimals(left: string, right: string): string | null {
    const a = parse(left), b = parse(right);
    if (a === null || b === null) return null;
    const scale = a.scale + b.scale;
    const raw = a.digits * b.digits; // valor absoluto con `scale` decimales
    const cents = scale <= 2 ? raw * TEN ** BigInt(2 - scale) : (TWO * raw + TEN ** BigInt(scale - 2)) / (TWO * TEN ** BigInt(scale - 2)); // mitad hacia arriba sobre el valor absoluto
    const negative = a.negative !== b.negative && cents !== ZERO;
    const text = cents.toString().padStart(3, "0");
    return `${negative ? "-" : ""}${text.slice(0, -2)}.${text.slice(-2)}`;
}
