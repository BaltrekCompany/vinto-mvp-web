// Contrato de lectura de Tubetes Utilizados. La API es la autoridad; el cliente valida
// la respuesta completa y no deriva fechas, códigos ni cantidades.

type Rec = Record<string, unknown>;
const isRec = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string";
const isIsoDate = (value: unknown): value is string => {
    if (typeof value !== "string" || value.length !== 10 || value[4] !== "-" || value[7] !== "-") return false;
    const parsed = new Date(value + "T00:00:00Z");
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
};
const INTEGER_TEXT = /^-?\d+$/;

export type TubeteUsage = { code: string; usage_count: number; dates: string[] };
export type MachineTubetes = { machine: "MP1" | "MP3"; usage_total: number; records_without_code: number; tubetes: TubeteUsage[] };
export type TubetesReport = {
    generated_at: string;
    source_form: "VINTO-P1-03";
    date_basis: "operating_date";
    timezone: "America/La_Paz";
    machines: [MachineTubetes, MachineTubetes];
};

function parseMachine(value: unknown, expected: "MP1" | "MP3"): MachineTubetes | null {
    if (!isRec(value) || value.machine !== expected || !Number.isSafeInteger(value.usage_total) || (value.usage_total as number) < 0
        || !Number.isSafeInteger(value.records_without_code) || (value.records_without_code as number) < 0 || !Array.isArray(value.tubetes)) return null;
    const tubetes: TubeteUsage[] = [];
    let total = 0;
    let previous = -Infinity;
    for (const item of value.tubetes) {
        if (!isRec(item) || !isText(item.code) || !INTEGER_TEXT.test(item.code) || !Number.isSafeInteger(item.usage_count)
            || (item.usage_count as number) < 1 || !Array.isArray(item.dates) || item.dates.length !== item.usage_count
            || !item.dates.every(date => isIsoDate(date))) return null;
        const codeNumber = Number(item.code);
        if (!Number.isSafeInteger(codeNumber) || String(codeNumber) !== item.code || codeNumber <= previous) return null;
        previous = codeNumber;
        const dates = item.dates as string[];
        if (dates.some((date, index) => index > 0 && date < dates[index - 1])) return null;
        total += item.usage_count as number;
        tubetes.push({ code: item.code, usage_count: item.usage_count as number, dates: [...dates] });
    }
    if (total !== value.usage_total) return null;
    return { machine: expected, usage_total: value.usage_total as number, records_without_code: value.records_without_code as number, tubetes };
}

export function parseTubetesReport(value: unknown): TubetesReport | null {
    if (!isRec(value) || !isText(value.generated_at) || !Number.isFinite(Date.parse(value.generated_at))
        || !/(Z|[+-]\d{2}:?\d{2})$/.test(value.generated_at)
        || value.source_form !== "VINTO-P1-03" || value.date_basis !== "operating_date"
        || value.timezone !== "America/La_Paz" || !Array.isArray(value.machines) || value.machines.length !== 2) return null;
    const mp1 = parseMachine(value.machines[0], "MP1");
    const mp3 = parseMachine(value.machines[1], "MP3");
    if (!mp1 || !mp3) return null;
    return { generated_at: value.generated_at, source_form: "VINTO-P1-03", date_basis: "operating_date", timezone: "America/La_Paz", machines: [mp1, mp3] };
}


export type TubetesMachineSelection = "all" | "MP1" | "MP3";

export function visibleTubetesMachines(
    report: TubetesReport,
    selection: TubetesMachineSelection,
): MachineTubetes[] {
    if (selection === "all") return [...report.machines];
    return report.machines.filter(machine => machine.machine === selection);
}
