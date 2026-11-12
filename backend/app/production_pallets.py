"""CV-P112-01: pallets P1-12 v4. Snapshot de peso y correlativo por OT/linea.

Fuente nominal: catalogo versionado de INInventario.Peso, no rutas de materiales.
Las capturas v1/v2/v3 no generan pallets; el POST repetido retorna el registro
original por la idempotencia de capture_service y nunca consume otro numero.
"""
from app.capture_errors import CaptureNotFoundError, CaptureValidationError
from app.sectors import SECTOR_CONVERSION, scoped_sector_codes

FORM = "VINTO-P1-12"
P113_FORM = "VINTO-P1-13"
P112_MACHINES = ("GAMBINI", "SINCRO_II", "SINCRO_III")
P113_MACHINES = ("OMET_I", "OMET_II", "8_2", "8_5", "8002", "SERV_4", "WALLY", "PANUELERA")


def form_for_machine(machine):
    if machine in P112_MACHINES:
        return FORM
    if machine in P113_MACHINES:
        return P113_FORM
    return None


def _nominal(connection, article_code: str):
    return connection.execute(
        """SELECT nominal_weight_kg, source_sha256
           FROM vinto_master.pallet_nominal_weight
           WHERE article_code = %s
           ORDER BY revision DESC LIMIT 1""",
        (article_code,),
    ).fetchone()


def _source(connection, assignment_id):
    return connection.execute(
        """SELECT a.status, m.code, s.code, wo.id, wo.number,
                  l.line_code, l.pv_reference, av.id, ar.code, av.description
           FROM vinto_txn.assignment a
           JOIN vinto_master.machine m ON m.id = a.machine_id
           JOIN vinto_master.sector s ON s.id = m.sector_id
           JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
           JOIN vinto_master.article_version av ON av.id = l.article_version_id
           JOIN vinto_master.article ar ON ar.id = av.article_id
           WHERE a.id = %s""",
        (assignment_id,),
    ).fetchone()


def preview(connection, assignment_id, sectors):
    """Solo lectura; nunca promete/reserva un numero de pallet."""
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        source = _source(connection, assignment_id)
        if source is None or source[0] != "active" or source[2] not in scoped_sector_codes(sectors):
            raise CaptureNotFoundError()
        _, machine, _, _, number, line, pv, _, article, description = source
        if form_for_machine(machine) is None:
            raise CaptureNotFoundError()
        nominal = _nominal(connection, article)
        return {
            "work_order": number, "line_code": line, "pv_reference": pv,
            "machine": machine, "article_code": article,
            "article_description": description,
            "nominal_weight_kg": str(nominal[0]) if nominal else None,
            "weight_available": nominal is not None,
            "unit": "kg/jaba" if nominal else None,
        }


def create_pallet(connection, *, capture_id, assignment_id, machine_id, form_version_id, clean, form_code=FORM):
    """Llamado DENTRO de la transaccion de /api/captures, tras validar el formulario.

    Una sola serializacion por OT+linea evita duplicados entre sesiones. La clave
    unica en PostgreSQL es la barrera definitiva aun ante capturas concurrentes.
    """
    version = connection.execute(
        "SELECT version_number FROM vinto_config.form_version WHERE id = %s",
        (form_version_id,),
    ).fetchone()
    if form_code not in (FORM, P113_FORM):
        raise CaptureValidationError("Pallet: formulario no admitido")
    minimum_version = 4 if form_code == FORM else 3
    if version is None or version[0] < minimum_version:
        return
    amount = clean.get("cantidad_jabas")
    # CV-P113-02: v4 permite registrar la bobina sin generar pallet.
    # Sin jabas no se crea una fila ni se consume un correlativo.
    if form_code == P113_FORM and version[0] >= 4 and amount is None:
        return
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise CaptureValidationError("Cantidad de jabas: debe ser un entero positivo")

    source = _source(connection, assignment_id)
    if source is None:
        raise CaptureNotFoundError()
    _, machine, sector, work_order_id, _, line_code, _, article_version_id, article_code, _ = source
    if sector != SECTOR_CONVERSION or form_for_machine(machine) != form_code:
        raise CaptureValidationError("Pallet: maquina y formulario no corresponden")

    # Segundo cerrojo por la clave funcional, adicional al de maquina ya obtenido.
    from app.capture_service import _lock
    _lock(connection, f"vinto-pallet:{work_order_id}:{line_code}")
    nominal = _nominal(connection, article_code)
    if nominal is None:
        raise CaptureValidationError("Pallet: el articulo programado no tiene peso nominal por jaba en el maestro aprobado")
    weight, source_hash = nominal

    next_number = connection.execute(
        """SELECT COALESCE(MAX(pallet_number), 0) + 1
           FROM vinto_txn.production_pallet
           WHERE work_order_id = %s AND line_code = %s""",
        (work_order_id, line_code),
    ).fetchone()[0]
    connection.execute(
        """INSERT INTO vinto_txn.production_pallet
           (capture_id, work_order_id, line_code, machine_id, article_version_id,
            pallet_number, quantity_jabas, nominal_weight_kg, total_weight_kg, weight_source_sha256)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (capture_id, work_order_id, line_code, machine_id, article_version_id,
         next_number, amount, weight, weight * amount, source_hash),
    )


def snapshot(connection, capture_id):
    """Snapshot inmutable del pallet vinculado a la captura autorizada."""
    row = connection.execute(
        """SELECT pallet_number, quantity_jabas, nominal_weight_kg, total_weight_kg
           FROM vinto_txn.production_pallet WHERE capture_id=%s""", (capture_id,)
    ).fetchone()
    if row is None:
        return None
    return {"number": row[0], "quantity_jabas": row[1],
            "nominal_weight_kg": str(row[2]), "total_weight_kg": str(row[3])}
