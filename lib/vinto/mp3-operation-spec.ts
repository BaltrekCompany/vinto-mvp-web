/**
 * RG-MP3-01 revisión 1 — inventario funcional de operación e inspección de MP3.
 * Fuente: fotografía facilitada y ocho decisiones funcionales del 09/11/2026.
 *
 * Esta definición NO publica ni habilita capturas: es el contrato preliminar
 * verificable de campos para el siguiente incremento backend/frontend.
 * MP1 conserva VINTO-P1-01 v4, sin reescribir su historia.
 */
export const MP3_INSPECTION_FORM_CODE = "VINTO-MP3-01";
export const MP3_INSPECTION_PRINT_CODE = "RG-MP3-01";
export const MP3_INSPECTION_MACHINE = "MP3";
export const MP3_INSPECTION_CAPTURE_POLICY = "one_per_machine_operating_date_shift" as const;

export type MP3FieldKind = "decimal" | "text" | "time" | "textarea";
export type MP3InspectionField = Readonly<{
    key: string;
    label: string;
    kind: MP3FieldKind;
    unit?: string;
    required: boolean;
    /** Posición técnica de una casilla repetida SIN imponer un nombre industrial. */
    slot?: 1 | 2 | 3;
}>;
export type MP3InspectionSection = Readonly<{ title: string; fields: readonly MP3InspectionField[] }>;

const num = (key: string, label: string, unit?: string, slot?: 1 | 2 | 3): MP3InspectionField =>
    ({ key, label, kind: "decimal", unit, required: false, ...(slot ? { slot } : {}) });
const txt = (key: string, label: string): MP3InspectionField => ({ key, label, kind: "text", required: false });
const time = (key: string, label: string): MP3InspectionField => ({ key, label, kind: "time", required: false });

export const MP3_INSPECTION_SECTIONS: readonly MP3InspectionSection[] = [
    { title: "Pulper", fields: [
        num("pulper_nivel_t30", "Nivel tanque T-30", "%"),
        num("pulper_nivel_h1", "Nivel tanque H-1", "%"),
        num("pulper_nivel_h3", "Nivel tanque H-3", "%"),
        num("pulper_peso_balas_fc", "Peso balas F.C.", "kg"),
        num("pulper_peso_balas_fl", "Peso balas F.L.", "kg"),
        num("pulper_tiempo_fc", "T. de pulpeo F.C.", "min"),
        num("pulper_tiempo_fl", "T. de pulpeo F.L.", "min"),
    ].map(f => ({ ...f, required: true })) },

    { title: "Refinos · Fibra corta", fields: [
        num("ref_fc_presion_d205", "Presión de op. D2-05", "bar"),
        num("ref_fc_motor_d2a", "Motor D2-A", "Amp"),
        num("ref_fc_motor_d3a", "Motor D3-A", "Amp"),
        num("ref_fc_schoppers", "Schoppers", "°S"),
        num("ref_fc_valvula_entrada", "Válvula de entrada", "cm"),
        num("ref_fc_valvula_salida", "Válvula de salida", "cm"),
        num("ref_fc_ciclo_purga", "Ciclo de purga dep.", "min"),
        num("ref_fc_nivel_h2", "Nivel tanque H-2", "%"),
    ] },

    { title: "Refinos · Fibra larga", fields: [
        num("ref_fl_presion_d505", "Presión de op. D5-05", "bar"),
        num("ref_fl_motor_d5a", "Motor D5-A", "Amp"),
        num("ref_fl_ciclo_purga", "Ciclo de purga dep.", "min"),
        num("ref_fl_schoppers", "Schoppers", "°S"),
        num("ref_fl_valvula_entrada", "Válvula de entrada", "cm"),
        num("ref_fl_valvula_salida", "Válvula de salida", "cm"),
        num("ref_fl_nivel_h4", "Nivel tanque H-4", "%"),
        num("ref_fl_nivel_h20", "Nivel tanque H-20", "%"),
    ] },

    { title: "Cabeza de máquina", fields: [
        num("cabeza_caudal_b4", "Caudal B-4", "L/min"),
        num("cabeza_caudal_b7", "Caudal B-7", "L/min"),
        num("cabeza_mezcla_fc_fl_1", "Mezcla F.C./F.L.", "%", 1),
        num("cabeza_mezcla_fc_fl_2", "Mezcla F.C./F.L.", "%", 2),
        num("cabeza_nivel_h20", "Nivel tanque H-20", "%"),
        num("cabeza_nivel_h21", "Nivel tanque H-21", "%"),
        num("cabeza_consistencia_1", "Consistencia", "%", 1),
        num("cabeza_consistencia_2", "Consistencia", "%", 2),
        num("cabeza_apert_cons", "Apert. válv. cons.", "%"),
        num("cabeza_gramaje_valvula", "Gramaje válvula", "%"),
        num("cabeza_nivel_pit", "Nivel tanque PIT", "%"),
        num("cabeza_motor_b23a", "Motor Fan B23A", "RPM"),
        num("cabeza_motor_b23b", "Motor Fan B23B", "RPM"),
        num("cabeza_nivel_t21", "Nivel tanque T-21", "%"),
        num("cabeza_velocidad_chorro", "Velocidad chorro", "m/min"),
        num("cabeza_velocidad_tela", "Velocidad tela", "m/min"),
        num("cabeza_consig", "Consig", "RPM"),
        num("cabeza_error_chorro_tela", "Error chorro-tela", "m/min"),
        num("cabeza_presion_labio", "Presión labio", "bar"),
        num("cabeza_apertura_labio_1", "Apertura de labio", "mm", 1),
        num("cabeza_apertura_labio_2", "Apertura de labio", "mm", 2),
        num("cabeza_angulo_caja", "Ángulo caja", "°"),
        num("cabeza_reg_distancia", "Reg. distancia", "mm"),
    ] },

    { title: "Colador", fields: [
        num("colador_presion_entrada", "Presión de entrada", "kg/cm²"),
        num("colador_presion_salida", "Presión de salida", "kg/cm²"),
        num("colador_apertura_purga", "Apertura purga", "cm"),
    ] },

    { title: "Químicos", fields: [
        num("quim_coating_1", "Coating", undefined, 1),
        num("quim_coating_2", "Coating", undefined, 2),
        num("quim_release_1", "Release", undefined, 1),
        num("quim_release_2", "Release", undefined, 2),
        num("quim_fosfato_1", "Fosfato", undefined, 1),
        num("quim_fosfato_2", "Fosfato", undefined, 2),
        num("quim_pasiv_tela_1", "Pasiv. tela", undefined, 1),
        num("quim_pasiv_tela_2", "Pasiv. tela", undefined, 2),
        num("quim_pasiv_fieltro_1", "Pasiv. fieltro", undefined, 1),
        num("quim_pasiv_fieltro_2", "Pasiv. fieltro", undefined, 2),
    ] },

    { title: "Aguas", fields: [
        num("aguas_nivel_t30", "Nivel tanque T-30", "%"),
        num("aguas_apert_b30", "Apertura bomba B30", "%"),
        num("aguas_apert_b8_1", "Apertura bomba B8", "%", 1),
        num("aguas_apert_b8_2", "Apertura bomba B8", "%", 2),
        num("aguas_caudal_flot", "Caudal flotador", "m³/min"),
        num("aguas_traslacion_flot", "Traslación flot.", "%"),
        num("aguas_cuchara_flot", "Cuchara flot.", "%"),
        num("aguas_presion_flot", "Presión flot.", "mmH₂O"),
        num("aguas_nivel_t31", "Nivel tanque T-31", "%"),
        num("aguas_nivel_t32", "Nivel tanque T-32", "%"),
    ] },

    { title: "Campana", fields: [
        num("campana_motor_v30", "Motor V-30", "%"),
        num("campana_temp_aire", "Temperatura aire", "°C"),
        num("campana_motor_v40", "Motor V-40", "%"),
        num("campana_motor_v50", "Motor V-50", "%"),
        num("campana_temp_lado_seco", "Temp. lado seco", "°C"),
        num("campana_temp_lado_humedo", "Temp. lado húmedo", "°C"),
    ] },

    { title: "Lubricación", fields: [
        num("lub_presion_pt01", "Presión PT-01", "bar"),
        num("lub_temp_tt03", "Temperatura TT-03", "°C"),
        num("lub_presion_pt1", "Presión PT1", "bar"),
        num("lub_temp_tt1", "Temperatura TT1", "°C"),
    ] },

    { title: "Presión regaderas", fields: [
        num("reg_alta_tela", "Alta tela", "bar"),
        num("reg_alta_fieltro", "Alta fieltro", "bar"),
        num("reg_cuna_tela", "Cuña tela", "bar"),
        num("reg_cuna_fieltro", "Cuña fieltro", "bar"),
        num("reg_sello_vacio_1", "Sello caja vacío 1", "bar"),
        num("reg_sello_vacio_2", "Sello caja vacío 2", "bar"),
    ] },

    { title: "Accionamientos", fields: [
        num("accion_vel_maquina", "Velocidad máquina", "m/min"),
        num("accion_crepado", "Crepado", "%"),
        num("accion_produccion", "Producción", "ton/día"),
        num("accion_vel_fieltro", "Velocidad fieltro", "m/min"),
        num("accion_vel_secador", "Velocidad secador", "m/min"),
        num("accion_vel_pope", "Velocidad Pope", "m/min"),
    ] },

    { title: "Vapor", fields: [
        num("vapor_vel_cilindro", "Velocidad cilindro", "m/min"),
        num("vapor_pres_cilindro", "Presión cilindro", "bar"),
        num("vapor_pres_caldero", "Presión caldero", "bar"),
        num("vapor_apertura_pv104", "Apertura PV104", "%"),
        num("vapor_apertura_tpv105", "Apertura TPV105", "%"),
        num("vapor_apertura_dpv105", "Apertura DPV105", "%"),
        num("vapor_nivel_condensado", "Nivel condensado", "%"),
        num("vapor_dif_presion", "Dif. de presión", "bar"),
    ] },

    { title: "Máquina", fields: [
        num("maq_limpieza_tela", "Limpieza tela"),
        num("maq_limpieza_fieltro", "Limpieza fieltro"),
    ] },

    { title: "Bajo máquina", fields: [
        num("bajo_nivel_tanque", "Nivel tanque", "%"),
        num("bajo_apertura_bomba_p7", "Apertura bomba P7", "%"),
    ] },

    { title: "Prensa", fields: [
        num("prensa_angulo", "Ángulo", "°"),
        num("prensa_pres_agua", "Presión agua", "bar"),
        num("prensa_pres_aire", "Presión aire", "bar"),
        num("prensa_pres_vacio", "Presión vacío", "cmHg"),
        num("prensa_pres_fuelle_com", "Presión fuelle com.", "bar"),
        num("prensa_pres_fuelle_tran", "Presión fuelle tran.", "bar"),
    ] },

    { title: "Vacíos", fields: [
        num("vacios_bomba_ba1", "Bomba BA1", "%"),
        num("vacios_bomba_ba2_1", "Bomba BA2", "%", 1),
        num("vacios_bomba_ba2_2", "Bomba BA2", "%", 2),
        num("vacios_bomba_ba3_1", "Bomba BA3", "%", 1),
        num("vacios_bomba_ba3_2", "Bomba BA3", "%", 2),
        num("vacios_vacuometro_1", "Vacuómetro", "bar", 1),
        num("vacios_vacuometro_2", "Vacuómetro", "bar", 2),
        num("vacios_vacuometro_3", "Vacuómetro", "bar", 3),
        num("vacios_caudal_sello_1", "Caudal agua sello", "m³/h", 1),
        num("vacios_caudal_sello_2", "Caudal agua sello", "m³/h", 2),
        num("vacios_caudal_sello_3", "Caudal agua sello", "m³/h", 3),
    ] },

    { title: "Presión doctores", fields: [
        num("doc_cambio", "Cambio", "bar"),
        num("doc_crepado", "Crepado", "bar"),
        num("doc_limpieza", "Limpieza", "bar"),
    ] },

    { title: "Limpieza", fields: [
        txt("limp_filtro_agua_prensa", "Filtro agua prensa"),
        txt("limp_filtro_quimicos", "Filtro químicos"),
        txt("limp_boquillas_quimicos", "Boquillas químicos"),
        txt("limp_lado_comando", "Lado comando"),
        txt("limp_lado_transmision", "Lado transmisión"),
        txt("limp_pasos_escaleras", "Pasos y escaleras"),
    ] },

    { title: "Horas de cambio de cuchillas", fields: [
        time("cuchillas_cambio", "Cuchilla de cambio"),
        time("cuchillas_crepado", "Cuchilla de crepado"),
        time("cuchillas_limpieza", "Cuchilla de limpieza"),
    ] },

    { title: "Novedades", fields: [
        { key: "novedades", label: "Novedades", kind: "textarea", required: false },
    ] },
];

/** El encabezado rojo y las firmas NO son parte del payload de captura. */
export const MP3_INSPECTION_CONTEXT = [
    "operador_autenticado",
    "maquina",
    "fecha_operativa",
    "turno",
    "hora_registro_servidor",
    "ot",
    "linea",
    "producto",
] as const;

export const MP3_INSPECTION_FIELDS = MP3_INSPECTION_SECTIONS.flatMap(section => section.fields);
