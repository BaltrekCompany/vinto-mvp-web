"""Importación transaccional e idempotente del bundle de referencia hacia PostgreSQL.

Reglas:
- Un maestro que no existe se inserta; uno semánticamente idéntico no se toca; uno distinto es un
  conflicto (nunca se actualiza). No se usa ON CONFLICT DO UPDATE.
- Todo ocurre en una sola transacción protegida por un advisory lock transaccional derivado SOLO
  del `source` estable: dos bundles de checksum distinto del mismo source compiten por el mismo
  lock y nunca mutan los mismos maestros a la vez. El checksum identifica el import_batch, no la
  exclusión mutua. Un conflicto en cualquier punto revierte la importación completa.
- Un batch `completed` con el mismo checksum NO oculta el drift: la base se compara siempre contra
  el bundle. Si coincide exactamente es un NO-OP; si algo difiere o falta es un conflicto y nunca
  se "repara" automáticamente.
- El dry-run usa exactamente el mismo recorrido, pero sin escribir y dentro de una transacción
  READ ONLY de PostgreSQL.
"""

import hashlib
from uuid import UUID
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from psycopg.types.json import Jsonb

from app.seed.bundle import Bundle

SOURCE = "vinto-reference-bobinas"
REASON = f"reference import: {SOURCE}"
ENTITY_ORDER = (
    "unit", "material_class", "sector", "machine", "profile", "article", "article_version", "article_machine",
    "shift", "shift_schedule", "workflow", "form", "form_version", "form_version_machine", "field", "option",
)


class ReferenceConflictError(Exception):
    """Un maestro existente difiere del bundle. Nada se escribió (la transacción se revirtió)."""

    def __init__(self, conflicts):
        self.conflicts = list(conflicts)
        shown = "; ".join(f"{c.key}: {c.detail}" for c in self.conflicts[:5])
        more = f" (+{len(self.conflicts) - 5} más)" if len(self.conflicts) > 5 else ""
        super().__init__(f"{len(self.conflicts)} conflicto(s) con maestros existentes: {shown}{more}")


@dataclass(frozen=True)
class Conflict:
    entity: str
    key: str
    detail: str


@dataclass
class Action:
    entity: str
    source_key: str
    status: str  # "create" | "present"
    schema: str | None
    table: str | None
    target_id: object
    payload: dict


@dataclass
class ImportResult:
    mode: str  # "dry-run" | "applied" | "noop"
    source_checksum: str
    batch_id: object = None
    counts: dict = field(default_factory=dict)  # entity -> {"create": n, "present": n}
    conflicts: list = field(default_factory=list)

    @property
    def pending_creates(self) -> int:
        return sum(numbers["create"] for numbers in self.counts.values())

    @property
    def state(self) -> str:
        """dry-run: "conflict" (conflicto o drift), "consistent" (la base coincide) o "pending" (se crearían filas)."""
        if self.conflicts:
            return "conflict"
        return "pending" if self.pending_creates else "consistent"


def advisory_lock_key(source: str) -> int:
    """Clave bigint determinista derivada únicamente del source (primeros 8 bytes de SHA-256, con signo)."""
    digest = hashlib.sha256(f"vinto-import-lock:{source}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _same(left, right) -> bool:
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return left is not None and right is not None and Decimal(str(left)) == Decimal(str(right))
    return left == right


class _Run:
    """Un recorrido ordenado del bundle. write=False solo consulta."""

    def __init__(self, connection, bundle: Bundle, batch_id=None, write=False):
        self.connection, self.bundle, self.batch_id, self.write = connection, bundle, batch_id, write
        self.actions, self.conflicts, self.ids = [], [], {}

    # -- helpers -----------------------------------------------------------------------------
    def query(self, sql, params=()):
        cursor = self.connection.execute(sql, params)
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, sql, params):
        return self.connection.execute(sql, params).fetchone()[0]

    def resolve(self, entity, key, schema, table, payload, existing, desired, insert_sql=None, insert_params=()):
        """Compara con lo existente. Devuelve el id (None si se crearía en dry-run)."""
        if existing is None:
            new_id = self.insert(insert_sql, insert_params) if self.write else None
            self.actions.append(Action(entity, key, "create", schema, table, new_id, payload))
            return new_id
        diff = [f"{name}: bd={existing.get(name)!r} bundle={value!r}" for name, value in desired.items()
                if not _same(existing.get(name), value)]
        if diff:
            self.conflicts.append(Conflict(entity, key, ", ".join(diff)))
        else:
            self.actions.append(Action(entity, key, "present", schema, table, existing.get("id"), payload))
        return existing.get("id")

    # -- entities ----------------------------------------------------------------------------
    def run(self):
        self.simple_masters()
        self.articles()
        self.shifts()
        self.workflows_and_forms()
        return self

    def simple_masters(self):
        for u in self.bundle.units:
            self.ids[("unit", u["code"])] = self.resolve(
                "unit", f"unit:{u['code']}", "vinto_master", "unit", u,
                self.one("SELECT id,label,active FROM vinto_master.unit WHERE code=%s", (u["code"],)),
                {"label": u["label"], "active": True},
                "INSERT INTO vinto_master.unit (code,label) VALUES (%s,%s) RETURNING id", (u["code"], u["label"]))
        for c in self.bundle.material_classes:
            self.ids[("material_class", c["code"])] = self.resolve(
                "material_class", f"material_class:{c['code']}", "vinto_master", "material_class", c,
                self.one("SELECT id,name FROM vinto_master.material_class WHERE code=%s", (c["code"],)),
                {"name": c["name"]},
                "INSERT INTO vinto_master.material_class (code,name) VALUES (%s,%s) RETURNING id", (c["code"], c["name"]))
        for s in self.bundle.sectors:
            self.ids[("sector", s["code"])] = self.resolve(
                "sector", f"sector:{s['code']}", "vinto_master", "sector", s,
                self.one("SELECT id,name,active FROM vinto_master.sector WHERE code=%s", (s["code"],)),
                {"name": s["name"], "active": True},
                "INSERT INTO vinto_master.sector (code,name) VALUES (%s,%s) RETURNING id", (s["code"], s["name"]))
        for m in self.bundle.machines:
            self.ids[("machine", m["code"])] = self.resolve(
                "machine", f"machine:{m['code']}", "vinto_master", "machine", m,
                self.one("""SELECT m.id,m.name,s.code AS sector,m.active FROM vinto_master.machine m
                            JOIN vinto_master.sector s ON s.id=m.sector_id WHERE m.code=%s""", (m["code"],)),
                {"name": m["name"], "sector": m["sector"], "active": True},
                "INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,%s,%s) RETURNING id",
                (self.ids[("sector", m["sector"])], m["code"], m["name"]))
        for p in self.bundle.profiles:
            self.ids[("profile", p["code"])] = self.resolve(
                "profile", f"profile:{p['code']}", "vinto_master", "profile", p,
                self.one("SELECT id,name,active FROM vinto_master.profile WHERE code=%s", (p["code"],)),
                {"name": p["name"], "active": True},
                "INSERT INTO vinto_master.profile (code,name) VALUES (%s,%s) RETURNING id", (p["code"], p["name"]))

    def articles(self):
        for a in self.bundle.articles:
            code, version = a["code"], a["version"]
            payload = {"code": code, "is_product": a["is_product"], "is_material": a["is_material"]}
            article_id = self.resolve(
                "article", f"article:{code}", "vinto_master", "article", payload,
                self.one("SELECT id,is_product,is_material,active FROM vinto_master.article WHERE code=%s", (code,)),
                {"is_product": a["is_product"], "is_material": a["is_material"], "active": True},
                "INSERT INTO vinto_master.article (code,is_product,is_material) VALUES (%s,%s,%s) RETURNING id",
                (code, a["is_product"], a["is_material"]))
            self.ids[("article", code)] = article_id
            existing = None
            if article_id is not None:
                existing = self.one("""SELECT v.id,v.description,u.code AS unit,c.code AS material_class,v.nominal_weight_kg
                    FROM vinto_master.article_version v JOIN vinto_master.unit u ON u.id=v.unit_id
                    LEFT JOIN vinto_master.material_class c ON c.id=v.material_class_id
                    WHERE v.article_id=%s AND v.version_number=%s""", (article_id, version["version_number"]))
            weight = None if version["nominal_weight_kg"] is None else Decimal(str(version["nominal_weight_kg"]))
            class_id = None if version["material_class"] is None else self.ids[("material_class", version["material_class"])]
            self.resolve(
                "article_version", f"article_version:{code}:{version['version_number']}", "vinto_master", "article_version",
                {"article_code": code, **version}, existing,
                {"description": version["description"], "unit": version["unit"],
                 "material_class": version["material_class"], "nominal_weight_kg": weight},
                """INSERT INTO vinto_master.article_version
                   (article_id,version_number,description,unit_id,material_class_id,nominal_weight_kg,source_batch_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (article_id, version["version_number"], version["description"], self.ids[("unit", version["unit"])],
                 class_id, weight, self.batch_id))
        for r in self.bundle.article_machines:
            article_id = self.ids[("article", r["article_code"])]
            machine_id = self.ids[("machine", r["machine_code"])]
            existing = None
            if article_id is not None and machine_id is not None:
                found = self.one("SELECT 1 AS present FROM vinto_master.article_machine WHERE article_id=%s AND machine_id=%s",
                                 (article_id, machine_id))
                existing = {"id": None} if found else None
            before = len(self.actions)
            self.resolve(
                "article_machine", f"article_machine:{r['article_code']}:{r['machine_code']}", "vinto_master", "article_machine",
                r, existing, {},
                "INSERT INTO vinto_master.article_machine (article_id,machine_id) VALUES (%s,%s) RETURNING article_id",
                (article_id, machine_id))
            for action in self.actions[before:]:
                action.target_id = None  # clave compuesta: no hay id de fila

    def shifts(self):
        for s in self.bundle.shifts:
            self.ids[("shift", s["code"])] = self.resolve(
                "shift", f"shift:{s['code']}", "vinto_config", "shift", s,
                self.one("SELECT id,name,active FROM vinto_config.shift WHERE code=%s", (s["code"],)),
                {"name": s["name"], "active": True},
                "INSERT INTO vinto_config.shift (code,name) VALUES (%s,%s) RETURNING id", (s["code"], s["name"]))
        for sc in self.bundle.schedules:
            shift_id, sector_id = self.ids[("shift", sc["shift"])], self.ids[("sector", sc["sector"])]
            starts, ends = time.fromisoformat(sc["starts_at"]), time.fromisoformat(sc["ends_at"])
            valid_from = date.fromisoformat(sc["valid_from"])
            valid_to = None if sc["valid_to"] is None else date.fromisoformat(sc["valid_to"])
            existing = None
            if shift_id is not None and sector_id is not None:
                existing = self.one("""SELECT id,starts_at,ends_at,timezone,valid_to FROM vinto_config.shift_schedule
                                       WHERE shift_id=%s AND sector_id=%s AND valid_from=%s""", (shift_id, sector_id, valid_from))
            self.resolve(
                "shift_schedule", f"shift_schedule:{sc['sector']}:{sc['shift']}:{sc['valid_from']}", "vinto_config", "shift_schedule",
                sc, existing,
                {"starts_at": starts, "ends_at": ends, "timezone": sc["timezone"], "valid_to": valid_to},
                """INSERT INTO vinto_config.shift_schedule (shift_id,sector_id,starts_at,ends_at,timezone,valid_from,valid_to)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (shift_id, sector_id, starts, ends, sc["timezone"], valid_from, valid_to))

    def workflows_and_forms(self):
        for w in self.bundle.workflows:
            self.ids[("workflow", w["code"])] = self.resolve(
                "workflow", f"workflow:{w['code']}", "vinto_config", "workflow_definition", w,
                self.one("SELECT id,name FROM vinto_config.workflow_definition WHERE code=%s", (w["code"],)),
                {"name": w["name"]},
                "INSERT INTO vinto_config.workflow_definition (code,name) VALUES (%s,%s) RETURNING id", (w["code"], w["name"]))
        for form in self.bundle.forms:
            self.form(form)

    def form(self, form):
        code, number = form["code"], form["version_number"]
        header = {k: form[k] for k in ("legacy_key", "code", "legacy_number")}
        rows = self.query("SELECT id,legacy_key,code,legacy_number,active FROM vinto_config.form WHERE legacy_key=%s OR code=%s",
                          (form["legacy_key"], code))
        existing = rows[0] if len(rows) == 1 else None
        if len(rows) > 1:
            self.conflicts.append(Conflict("form", f"form:{code}", "legacy_key y code pertenecen a formularios distintos"))
            return
        form_id = self.resolve(
            "form", f"form:{code}", "vinto_config", "form", header, existing,
            {**header, "active": True},
            "INSERT INTO vinto_config.form (legacy_key,code,legacy_number) VALUES (%s,%s,%s) RETURNING id",
            (form["legacy_key"], code, form["legacy_number"]))
        self.ids[("form", code)] = form_id
        version = None
        if form_id is not None:
            version = self.one("""SELECT v.id,v.name,v.area,w.code AS workflow,v.status,v.definition_checksum
                FROM vinto_config.form_version v JOIN vinto_config.workflow_definition w ON w.id=v.workflow_id
                WHERE v.form_id=%s AND v.version_number=%s""", (form_id, number))
        version_key = f"form_version:{code}:{number}"
        payload = {k: form[k] for k in ("legacy_key", "code", "name", "area", "workflow", "version_number", "machines", "definition_checksum")}
        desired = {"name": form["name"], "area": form["area"], "workflow": form["workflow"],
                   "status": "published", "definition_checksum": form["definition_checksum"]}
        if version is not None:
            self.resolve("form_version", version_key, "vinto_config", "form_version", payload, version, desired)
            if not any(c.key == version_key for c in self.conflicts):
                self.compare_children(form, version["id"])
            return
        version_id = None
        if self.write:
            version_id = self.insert(
                """INSERT INTO vinto_config.form_version (form_id,version_number,name,area,workflow_id,status,definition_checksum,source_batch_id)
                   VALUES (%s,%s,%s,%s,%s,'draft',%s,%s) RETURNING id""",
                (form_id, number, form["name"], form["area"], self.ids[("workflow", form["workflow"])],
                 form["definition_checksum"], self.batch_id))
        self.actions.append(Action("form_version", version_key, "create", "vinto_config", "form_version", version_id, payload))
        for machine in form["machines"]:
            if self.write:
                self.connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)",
                                        (version_id, self.ids[("machine", machine)]))
            self.actions.append(Action("form_version_machine", f"form_version_machine:{code}:{number}:{machine}", "create",
                                       "vinto_config", "form_version_machine", None, {"form": code, "version_number": number, "machine": machine}))
        for f in form["fields"]:
            field_id = None
            if self.write:
                field_id = self.insert(
                    """INSERT INTO vinto_config.field_definition
                       (form_version_id,key,label,value_type,source,required,unit_id,display_order)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (version_id, f["key"], f["label"], f["value_type"], f["source"], f["required"],
                     None if f["unit"] is None else self.ids[("unit", f["unit"])], f["display_order"]))
            self.actions.append(Action("field", f"field:{code}:{number}:{f['key']}", "create", "vinto_config", "field_definition",
                                       field_id, {k: v for k, v in f.items() if k != "options"}))
            for o in f.get("options", []):
                if self.write:
                    self.connection.execute(
                        """INSERT INTO vinto_config.field_option (form_version_id,field_definition_id,option_key,label,display_order)
                           VALUES (%s,%s,%s,%s,%s)""", (version_id, field_id, o["option_key"], o["label"], o["display_order"]))
                self.actions.append(Action("option", f"option:{code}:{number}:{f['key']}:{o['option_key']}", "create", "vinto_config",
                                           "field_option", None, {"field": f["key"], **o}))
        if self.write:  # publish last: draft children can only be inserted while the version is a draft
            self.connection.execute(
                "UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s", (version_id,))

    def compare_children(self, form, version_id):
        code, number = form["code"], form["version_number"]
        db_machines = {r["code"] for r in self.query(
            """SELECT m.code FROM vinto_config.form_version_machine fvm JOIN vinto_master.machine m ON m.id=fvm.machine_id
               WHERE fvm.form_version_id=%s""", (version_id,))}
        if db_machines != set(form["machines"]):
            self.conflicts.append(Conflict("form_version_machine", f"form_version_machine:{code}:{number}",
                                           f"bd={sorted(db_machines)} bundle={sorted(form['machines'])}"))
        else:
            for machine in form["machines"]:
                self.actions.append(Action("form_version_machine", f"form_version_machine:{code}:{number}:{machine}", "present",
                                           "vinto_config", "form_version_machine", None,
                                           {"form": code, "version_number": number, "machine": machine}))
        db_fields = {r["key"]: r for r in self.query(
            """SELECT f.id,f.key,f.label,f.value_type,f.source,f.required,u.code AS unit,f.display_order,f.field_group_id
               FROM vinto_config.field_definition f LEFT JOIN vinto_master.unit u ON u.id=f.unit_id
               WHERE f.form_version_id=%s""", (version_id,))}
        if set(db_fields) != {f["key"] for f in form["fields"]}:
            self.conflicts.append(Conflict("field", f"field:{code}:{number}",
                                           f"campos bd={sorted(db_fields)} bundle={sorted(f['key'] for f in form['fields'])}"))
            return
        for f in form["fields"]:
            row = db_fields[f["key"]]
            desired = {k: f[k] for k in ("label", "value_type", "source", "required", "unit", "display_order")}
            desired["field_group_id"] = None
            self.resolve("field", f"field:{code}:{number}:{f['key']}", "vinto_config", "field_definition",
                         {k: v for k, v in f.items() if k != "options"}, row, desired)
            db_options = self.query("SELECT option_key,label,display_order FROM vinto_config.field_option WHERE field_definition_id=%s ORDER BY display_order",
                                    (row["id"],))
            wanted = [{"option_key": o["option_key"], "label": o["label"], "display_order": o["display_order"]} for o in f.get("options", [])]
            if db_options != wanted:
                self.conflicts.append(Conflict("option", f"option:{code}:{number}:{f['key']}", f"bd={db_options!r} bundle={wanted!r}"))
                continue
            for o in f.get("options", []):
                self.actions.append(Action("option", f"option:{code}:{number}:{f['key']}:{o['option_key']}", "present", "vinto_config",
                                           "field_option", None, {"field": f["key"], **o}))


def _counts(actions):
    counts = {}
    for action in actions:
        counts.setdefault(action.entity, {"create": 0, "present": 0})[action.status] += 1
    return {entity: counts[entity] for entity in ENTITY_ORDER if entity in counts}


def _find_completed_batch(connection, bundle: Bundle):
    row = connection.execute(
        "SELECT id FROM vinto_audit.import_batch WHERE source=%s AND source_checksum=%s AND status='completed' ORDER BY imported_at LIMIT 1",
        (SOURCE, bundle.source_checksum)).fetchone()
    return row[0] if row else None


def _drift(run, completed) -> list:
    """Conflictos de un recorrido de solo lectura. Con un batch completed, lo que falta también es drift."""
    conflicts = list(run.conflicts)
    if completed is not None:
        conflicts += [Conflict(a.entity, a.source_key, f"ausente en la base de datos (drift tras el batch completed {completed})")
                      for a in run.actions if a.status == "create"]
    return conflicts


def dry_run(connection, bundle: Bundle) -> ImportResult:
    """Compara SIEMPRE con el estado actual, sin escribir: transacción READ ONLY y solo SELECT.

    Requiere conexión autocommit. Con un batch completed del mismo checksum, cualquier diferencia o fila
    ausente se informa como conflicto (drift).
    """
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        completed = _find_completed_batch(connection, bundle)
        run = _Run(connection, bundle, write=False).run()
    return ImportResult("dry-run", bundle.source_checksum, batch_id=completed, counts=_counts(run.actions),
                        conflicts=_drift(run, completed))


def apply(connection, bundle: Bundle) -> ImportResult:
    """Importa en una sola transacción. Requiere conexión autocommit; lanza ReferenceConflictError si hay conflictos o drift."""
    with connection.transaction():
        connection.execute("SELECT set_config('vinto.request_id', %s, true)", (f"import:{SOURCE}:{bundle.source_checksum[:12]}",))
        connection.execute("SELECT set_config('vinto.reason', %s, true)", (REASON,))
        # Lock por source ANTES de consultar import_batch: 0001 no tiene UNIQUE(source, source_checksum) y
        # bundles de checksum distinto del mismo source modifican los mismos maestros.
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (advisory_lock_key(SOURCE),))
        completed = _find_completed_batch(connection, bundle)
        if completed is not None:
            # Ya importado: no se crea otro batch, pero se verifica que la base siga igual que el bundle.
            run = _Run(connection, bundle, write=False).run()
            drift = _drift(run, completed)
            if drift:
                raise ReferenceConflictError(drift)
            return ImportResult("noop", bundle.source_checksum, batch_id=completed, counts=_counts(run.actions))
        batch_id = connection.execute(
            "INSERT INTO vinto_audit.import_batch (source,source_checksum,status) VALUES (%s,%s,'pending') RETURNING id",
            (SOURCE, bundle.source_checksum)).fetchone()[0]
        run = _Run(connection, bundle, batch_id=batch_id, write=True).run()
        if run.conflicts:
            raise ReferenceConflictError(run.conflicts)  # revierte batch y maestros ya insertados
        keys = [a.source_key for a in run.actions]
        if len(keys) != len(set(keys)):
            raise RuntimeError("source_key duplicado dentro del batch")
        for action in run.actions:
            connection.execute(
                """INSERT INTO vinto_audit.import_record
                   (batch_id,source_key,raw_payload,target_schema,target_table,target_id,status,issues)
                   VALUES (%s,%s,%s,%s,%s,%s,'accepted',%s)""",
                (batch_id, action.source_key, Jsonb(action.payload), action.schema, action.table,
                 action.target_id if isinstance(action.target_id, UUID) else None,
                 Jsonb(["already_present"] if action.status == "present" else [])))
        counts = _counts(run.actions)
        connection.execute(
            "UPDATE vinto_audit.import_batch SET status='completed',completed_at=clock_timestamp(),summary=%s WHERE id=%s",
            (Jsonb({"bundle": bundle.manifest.get("bundle"), "schema_version": bundle.manifest["schema_version"],
                    "records": len(run.actions), "entities": counts}), batch_id))
    return ImportResult("applied", bundle.source_checksum, batch_id=batch_id, counts=counts)
