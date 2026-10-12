"""Lectura y validación del bundle canónico (backend/seed_data). No accede a PostgreSQL.

`load_bundle` valida todo antes de devolver un `Bundle`: manifest, SHA-256 y tamaños,
archivos faltantes o extra, conteos, checksum de definición de los formularios y
referencias internas. Si algo es inconsistente lanza `BundleError` y el bundle completo
se rechaza.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.shifts import ScheduleRow, ShiftResolutionError, resolve_shift_from_schedules

BUNDLE_DIR = Path(__file__).resolve().parents[2] / "seed_data"
SUPPORTED_SCHEMA_VERSION = 1
MANIFEST = "manifest.json"
VALUE_TYPES = {"text", "textarea", "decimal", "integer", "boolean", "date", "time"}
SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")
# Formato de los códigos de datos maestros (el exportador scripts/export-seed-data.mjs aplica los mismos).
CODE_PATTERNS = {
    "sector": re.compile(r"[A-Z][A-Z0-9_]{0,31}"), "machine": re.compile(r"[A-Z0-9][A-Z0-9_]{0,31}"), "unit": re.compile(r"[A-Z][A-Z0-9_]{0,15}"),
    "shift": re.compile(r"[A-Z][A-Z0-9_]{0,31}"), "article": re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}"),
}
MINUTES_PER_DAY = 1440

# entity file -> Bundle attribute, entity name inside the file
ENTITY_FILES = {
    "units.json": ("units", "unit"),
    "material_classes.json": ("material_classes", "material_class"),
    "sectors.json": ("sectors", "sector"),
    "machines.json": ("machines", "machine"),
    "articles.json": ("articles", "article"),
    "article_machines.json": ("article_machines", "article_machine"),
    "profiles.json": ("profiles", "profile"),
    "workflows.json": ("workflows", "workflow_definition"),
}
SHIFTS_FILE = "shifts.json"
FORMS_DIR = "forms"


class BundleError(Exception):
    """El bundle es inválido; el mensaje no contiene rutas absolutas ni secretos."""


@dataclass(frozen=True)
class Bundle:
    manifest: dict
    source_checksum: str
    units: tuple
    material_classes: tuple
    sectors: tuple
    machines: tuple
    articles: tuple
    article_machines: tuple
    profiles: tuple
    workflows: tuple
    shifts: tuple
    schedules: tuple
    forms: tuple


def canonical_json(value) -> str:
    """JSON compacto con claves ordenadas y sin escapar no-ASCII (igual que el exportador Node)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_source_checksum(manifest: dict) -> str:
    """SHA-256 del JSON canónico de manifest.json.

    El manifest contiene el SHA-256 de cada archivo y de cada fuente, así que identifica
    el bundle completo. No incluye marcas de tiempo ni datos del entorno.
    """
    return sha256_hex(canonical_json(manifest))


def compute_definition_checksum(form: dict) -> str:
    """SHA-256 canónico de la definición del formulario (sin schema_version ni el propio checksum)."""
    definition = {k: v for k, v in form.items() if k not in ("schema_version", "definition_checksum")}
    return sha256_hex(canonical_json(definition))


def _read_text(path: Path) -> str:
    try:
        # Git en Windows puede entregar CRLF; el manifest hashea la forma LF.
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError) as error:
        raise BundleError(f"No se pudo leer {path.name}: {type(error).__name__}") from None


def _parse(text: str, name: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise BundleError(f"{name} no es JSON válido") from None


def _safe_relative(path: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or "\\" in path or not pure.parts:
        raise BundleError(f"Ruta no permitida en el manifest: {path}")
    return pure


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleError(message)


def _unique(items, key, label):
    values = [item[key] for item in items]
    _require(len(values) == len(set(values)), f"{label}: códigos duplicados")
    return set(values)


def load_bundle(directory: Path = BUNDLE_DIR) -> Bundle:
    directory = Path(directory)
    manifest_path = directory / MANIFEST
    _require(manifest_path.is_file(), f"Falta {MANIFEST}")
    manifest = _parse(_read_text(manifest_path), MANIFEST)
    _require(isinstance(manifest, dict), "manifest.json debe ser un objeto")
    _require(manifest.get("schema_version") == SUPPORTED_SCHEMA_VERSION,
             f"schema_version {manifest.get('schema_version')!r} no soportada (se soporta {SUPPORTED_SCHEMA_VERSION})")
    declared = manifest.get("files")
    _require(isinstance(declared, list) and declared, "manifest.json no declara archivos")

    texts, seen = {}, set()
    for entry in declared:
        _require(isinstance(entry, dict) and {"path", "sha256"} <= entry.keys(), "Entrada de archivo inválida en el manifest")
        relative = _safe_relative(entry["path"]).as_posix()
        _require(relative not in seen and relative != MANIFEST, f"Archivo repetido o inválido en el manifest: {relative}")
        seen.add(relative)
        _require(SHA256_HEX.match(str(entry["sha256"])) is not None, f"SHA-256 inválido para {relative}")
        file_path = directory / relative
        _require(file_path.is_file(), f"Falta el archivo declarado: {relative}")
        text = _read_text(file_path)
        _require(sha256_hex(text) == entry["sha256"], f"SHA-256 no coincide: {relative}")
        if "bytes" in entry:
            _require(len(text.encode("utf-8")) == entry["bytes"], f"Tamaño no coincide: {relative}")
        texts[relative] = text

    on_disk = {p.relative_to(directory).as_posix() for p in directory.rglob("*.json")} - {MANIFEST}
    extra = sorted(on_disk - seen)
    _require(not extra, f"JSON no declarado en el manifest: {', '.join(extra)}")

    parsed = {name: _parse(text, name) for name, text in texts.items()}
    for name, document in parsed.items():
        _require(isinstance(document, dict) and document.get("schema_version") == SUPPORTED_SCHEMA_VERSION,
                 f"{name}: schema_version no soportada")

    collections = {}
    for file_name, (attribute, entity) in ENTITY_FILES.items():
        _require(file_name in parsed, f"Falta el archivo de entidad {file_name}")
        document = parsed[file_name]
        _require(document.get("entity") == entity and isinstance(document.get("items"), list), f"{file_name}: formato inválido")
        collections[attribute] = tuple(document["items"])
    _require(SHIFTS_FILE in parsed, f"Falta {SHIFTS_FILE}")
    shifts_doc = parsed[SHIFTS_FILE]
    _require(shifts_doc.get("entity") == "shift", f"{SHIFTS_FILE}: formato inválido")
    collections["shifts"] = tuple(shifts_doc["shifts"])
    collections["schedules"] = tuple(shifts_doc["schedules"])
    form_files = sorted(n for n in parsed if n.startswith(FORMS_DIR + "/"))
    _require(form_files, "El bundle no incluye formularios")
    collections["forms"] = tuple(parsed[n] for n in form_files)

    bundle = Bundle(manifest=manifest, source_checksum=compute_source_checksum(manifest), **collections)
    _validate_counts(bundle)
    _validate_content(bundle)
    return bundle


def _validate_counts(bundle: Bundle) -> None:
    counts = bundle.manifest.get("counts")
    _require(isinstance(counts, dict), "manifest.json no incluye conteos")
    actual = {
        "units": len(bundle.units),
        "material_classes": len(bundle.material_classes),
        "sectors": len(bundle.sectors),
        "machines": len(bundle.machines),
        "articles": len(bundle.articles),
        "article_machines": len(bundle.article_machines),
        "articles_also_material": sum(1 for a in bundle.articles if a["is_material"]),
        "articles_with_nominal_weight": sum(1 for a in bundle.articles if a["version"]["nominal_weight_kg"] is not None),
        "articles_with_grammage": sum(1 for a in bundle.articles if a["version"].get("grammage_g_m2") is not None),
        "profiles": len(bundle.profiles),
        "workflows": len(bundle.workflows),
        "shifts": len(bundle.shifts),
        "shift_schedules": len(bundle.schedules),
        "forms": len(bundle.forms),
        "form_fields": sum(len(f["fields"]) for f in bundle.forms),
        "form_options": sum(len(field.get("options", [])) for f in bundle.forms for field in f["fields"]),
    }
    for name, value in actual.items():
        _require(counts.get(name) == value, f"Conteo inconsistente en {name}: manifest={counts.get(name)!r}, datos={value}")


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _runs(items, label) -> str:
    """Lista ordenada de minutos (enteros) -> "desde–hasta" por tramos continuos (máx. 3)."""
    runs: list[list[int]] = []
    for item in items:
        if runs and item == runs[-1][1] + 1:
            runs[-1][1] = item
        else:
            runs.append([item, item])
    text = ", ".join(f"{label(a)}–{label(b + 1)}" for a, b in runs[:3])
    return text + (f" (+{len(runs) - 3})" if len(runs) > 3 else "")


def _validate_codes(bundle: Bundle) -> None:
    for kind, label, items in (("sector", "sector", bundle.sectors), ("machine", "machine", bundle.machines), ("unit", "unit", bundle.units),
                               ("shift", "shift", bundle.shifts), ("article", "article", bundle.articles)):
        for item in items:
            code = item.get("code")
            _require(isinstance(code, str) and CODE_PATTERNS[kind].fullmatch(code) is not None, f"{label}: código inválido {code!r}")


def _validate_schedules(schedules) -> None:
    """Horarios por sector: una sola zona horaria, sin huecos entre vigencias, cada minuto del día cubierto UNA vez dentro de cada vigencia y
    también a través de cada cambio de vigencia (un cambio de horario puede dejar el tiempo real sin turno o con turnos solapados aunque cada
    régimen sea correcto por separado). Los turnos nocturnos cruzan la medianoche y su fecha operativa es la del INICIO. Las transiciones se
    simulan con el resolvedor real (app.shifts), de modo que se valida exactamente lo que ocurrirá en ejecución. Supone una zona sin saltos de
    horario de verano (America/La_Paz)."""
    by_sector: dict[str, list[ScheduleRow]] = {}
    for sc in schedules:
        by_sector.setdefault(sc["sector"], []).append(ScheduleRow(
            shift_schedule_id=(sc["shift"], sc["sector"], sc["valid_from"]), shift_id=sc["shift"], shift_code=sc["shift"], shift_name=sc["shift"],
            starts_at=time.fromisoformat(sc["starts_at"]), ends_at=time.fromisoformat(sc["ends_at"]), timezone=sc["timezone"],
            valid_from=date.fromisoformat(sc["valid_from"]), valid_to=None if sc["valid_to"] is None else date.fromisoformat(sc["valid_to"])))
    for sector, rows in by_sector.items():
        zones = {r.timezone for r in rows}
        _require(len(zones) == 1, f"Horarios del sector {sector}: todas las vigencias deben usar la misma zona horaria")
        try:
            zone = ZoneInfo(next(iter(zones)))
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise BundleError(f"Horarios del sector {sector}: zona horaria inválida {next(iter(zones))!r}") from None
        bounds = sorted({r.valid_from for r in rows} | {r.valid_to + timedelta(days=1) for r in rows if r.valid_to is not None})
        previous = None
        for index, bound in enumerate(bounds):
            following = bounds[index + 1] if index + 1 < len(bounds) else None
            active = [r for r in rows if r.valid_from <= bound and (r.valid_to is None or r.valid_to >= bound)]
            if not active:
                _require(following is None, f"Horarios del sector {sector}: no hay turnos vigentes entre {bound} y {following - timedelta(days=1)}")
                previous = None  # todas las vigencias terminaron: nada configurado después
                continue
            cover = [0] * MINUTES_PER_DAY
            for r in active:
                minute = r.starts_at.hour * 60 + r.starts_at.minute
                end = r.ends_at.hour * 60 + r.ends_at.minute
                while minute != end:
                    cover[minute] += 1
                    minute = (minute + 1) % MINUTES_PER_DAY
            holes = [m for m, n in enumerate(cover) if n == 0]
            overlaps = [m for m, n in enumerate(cover) if n > 1]
            _require(not holes, f"Horarios del sector {sector} desde {bound}: minutos sin turno (hueco) {_runs(holes, _hhmm)}")
            _require(not overlaps, f"Horarios del sector {sector} desde {bound}: turnos solapados {_runs(overlaps, _hhmm)}")
            if previous:  # cambio de vigencia: tiempo real desde un día antes hasta un día después
                start = datetime.combine(bound - timedelta(days=1), time.min, tzinfo=zone)
                bad = []
                for k in range(2 * MINUTES_PER_DAY):
                    try:
                        resolve_shift_from_schedules(rows, start + timedelta(minutes=k))
                    except ShiftResolutionError:
                        bad.append(k)
                _require(not bad, f"Horarios del sector {sector}: el cambio de vigencia del {bound} deja el tiempo real sin turno o con turnos solapados "
                                  f"({_runs(bad, lambda k: (start + timedelta(minutes=k)).strftime('%Y-%m-%d %H:%M'))})")
            previous = active


def _validate_content(bundle: Bundle) -> None:
    units = _unique(bundle.units, "code", "units")
    classes = _unique(bundle.material_classes, "code", "material_classes")
    sectors = _unique(bundle.sectors, "code", "sectors")
    machines = _unique(bundle.machines, "code", "machines")
    articles = _unique(bundle.articles, "code", "articles")
    _unique(bundle.profiles, "code", "profiles")
    workflows = _unique(bundle.workflows, "code", "workflows")
    shifts = _unique(bundle.shifts, "code", "shifts")
    _unique(bundle.forms, "code", "forms")
    _unique(bundle.forms, "legacy_key", "forms")

    for machine in bundle.machines:
        _require(machine["sector"] in sectors, f"machine {machine['code']}: sector inexistente {machine['sector']}")
    _validate_codes(bundle)
    names = [str(m.get("name", "")).strip().casefold() for m in bundle.machines]
    _require(all(names), "machine: nombre vacío")
    _require(len(names) == len(set(names)), "machines: nombres repetidos")
    for article in bundle.articles:
        version = article["version"]
        _require(version["version_number"] == 1, f"article {article['code']}: solo se admite la versión 1")
        _require(version["unit"] in units, f"article {article['code']}: unidad inexistente {version['unit']}")
        _require(version["material_class"] is None or version["material_class"] in classes,
                 f"article {article['code']}: clase inexistente {version['material_class']}")
        _require(article["is_product"] or article["is_material"], f"article {article['code']}: debe ser producto o material")
        _require("grammage_g_m2" in version, f"article {article['code']}: falta grammage_g_m2 (null cuando no existe)")
        grammage = version["grammage_g_m2"]
        _require(grammage is None or (isinstance(grammage, (int, float)) and not isinstance(grammage, bool) and grammage > 0),
                 f"article {article['code']}: grammage_g_m2 inválido")
    pairs = [(r["article_code"], r["machine_code"]) for r in bundle.article_machines]
    _require(len(pairs) == len(set(pairs)), "article_machines: relaciones duplicadas")
    for article_code, machine_code in pairs:
        _require(article_code in articles, f"article_machine: artículo inexistente {article_code}")
        _require(machine_code in machines, f"article_machine: máquina inexistente {machine_code}")
    related = {article_code for article_code, _ in pairs}
    for article in bundle.articles:
        _require(not article["is_product"] or article["code"] in related, f"article {article['code']}: producto sin relación con ninguna máquina")

    schedule_keys = set()
    for schedule in bundle.schedules:
        _require(schedule["shift"] in shifts, f"shift_schedule: turno inexistente {schedule['shift']}")
        _require(schedule["sector"] in sectors, f"shift_schedule: sector inexistente {schedule['sector']}")
        try:
            starts, ends = time.fromisoformat(schedule["starts_at"]), time.fromisoformat(schedule["ends_at"])
            valid_from = date.fromisoformat(schedule["valid_from"])
            valid_to = None if schedule["valid_to"] is None else date.fromisoformat(schedule["valid_to"])
        except (ValueError, KeyError, TypeError):
            raise BundleError(f"shift_schedule {schedule.get('shift')}: hora o fecha inválida") from None
        _require(starts != ends, f"shift_schedule {schedule['shift']}: inicio y fin iguales")
        _require(valid_to is None or valid_to >= valid_from, f"shift_schedule {schedule['shift']}: valid_to anterior a valid_from")
        _require(bool(schedule["timezone"]), f"shift_schedule {schedule['shift']}: sin zona horaria")
        key = (schedule["shift"], schedule["sector"], schedule["valid_from"])
        _require(key not in schedule_keys, "shift_schedule duplicado")
        schedule_keys.add(key)
    _validate_schedules(bundle.schedules)

    for form in bundle.forms:
        label = form["code"]
        _require(compute_definition_checksum(form) == form.get("definition_checksum"),
                 f"{label}: definition_checksum no coincide con el contenido")
        _require(form["workflow"] in workflows, f"{label}: workflow inexistente {form['workflow']}")
        _require(form["area"] in ("production", "quality"), f"{label}: area inválida")
        _require(form["version_number"] >= 1, f"{label}: version_number inválido")
        _require(form["machines"] and len(form["machines"]) == len(set(form["machines"])), f"{label}: máquinas vacías o repetidas")
        for machine in form["machines"]:
            _require(machine in machines, f"{label}: máquina inexistente {machine}")
        _require(form["groups"] == [], f"{label}: los grupos de campos no están soportados por este importador")
        keys = [f["key"] for f in form["fields"]]
        _require(keys and len(keys) == len(set(keys)), f"{label}: campos vacíos o con claves repetidas")
        for field in form["fields"]:
            _require(field["value_type"] in VALUE_TYPES, f"{label}/{field['key']}: tipo inválido")
            _require(field["source"] == "manual", f"{label}/{field['key']}: solo se importan campos manuales")
            _require(field["unit"] is None or field["unit"] in units, f"{label}/{field['key']}: unidad inexistente {field['unit']}")
            option_keys = [o["option_key"] for o in field.get("options", [])]
            _require(len(option_keys) == len(set(option_keys)), f"{label}/{field['key']}: opciones duplicadas")
