"""OFF-04.6: the vocabulary of server-calculated fields that an offline definition can carry, derived from the SAME constants the online routes calculate with.

The device never calculates: a calculated field is shown read-only ("calculado por el servidor") and the backend computes it at reception (central validation). The rules
travel in the signed definition so the device can show WHAT the server will do, and a definition that declares a calculated field WITHOUT a rule is refused (fail closed)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.quality import capture_service as bobbin_service
from app.quality import machine_capture_service as machine_service

METHOD_PERCENT = "percent_two_decimals_half_up"
METHOD_MEAN = "mean_two_decimals_half_up"
METHOD_PROFILE_MEAN = "profile_mean_two_decimals_half_up"
METHOD_PROFILE_COUNT = "profile_complete_positions_count"
RULE_KEYS = {
    METHOD_PERCENT: ("method", "numerator", "denominator", "denominator_zero"),
    METHOD_MEAN: ("method", "operands"),
    METHOD_PROFILE_MEAN: ("method", "column", "complete_columns"),
    METHOD_PROFILE_COUNT: ("method", "complete_columns"),
}
_POSITION = re.compile(r"^(gramaje|peso_seco|humedad)_(\d{2})$")


class UnsupportedCalculation(Exception):
    """A calculated field without a known rule, or a rule whose operands are not manual decimals: the definition is not exported."""


@dataclass(frozen=True)
class FieldInfo:
    key: str
    value_type: str
    source: str


def _by_key(fields) -> dict:
    return {f.key: f for f in fields}


def _require_manual_decimals(by_key: dict, keys) -> None:
    for key in keys:
        f = by_key.get(key)
        if f is None or f.source != "manual" or f.value_type != "decimal":
            raise UnsupportedCalculation(key)


def calculated_rules(form_code: str, fields) -> dict:
    """{calculated_key: rule} for every calculated field of the definition; raises UnsupportedCalculation if any has no rule or a malformed operand set."""
    infos = [f if isinstance(f, FieldInfo) else FieldInfo(f["key"], f["value_type"], f["source"]) for f in fields]
    by_key = _by_key(infos)
    calculated = [f for f in infos if f.source == "calculated"]
    rules: dict = {}
    for key, (numerator, denominator) in machine_service.PERCENT_RULES.get(form_code, {}).items():
        if key in by_key and by_key[key].source == "calculated":
            _require_manual_decimals(by_key, (numerator, denominator))
            if by_key[key].value_type != "decimal":
                raise UnsupportedCalculation(key)
            rules[key] = {"method": METHOD_PERCENT, "numerator": numerator, "denominator": denominator, "denominator_zero": "omit_calculation"}
    for key, operands in bobbin_service.MEAN_RULES.get(form_code, {}).items():
        if key in by_key and by_key[key].source == "calculated":
            _require_manual_decimals(by_key, operands)
            if by_key[key].value_type != "decimal":
                raise UnsupportedCalculation(key)
            rules[key] = {"method": METHOD_MEAN, "operands": list(operands)}
    if form_code == bobbin_service.PROFILE_FORM:
        columns = list(bobbin_service.PROFILE_COLUMNS)
        for column, key in bobbin_service.PROFILE_AVERAGE_KEYS.items():
            if key in by_key and by_key[key].source == "calculated":
                if by_key[key].value_type != "decimal":
                    raise UnsupportedCalculation(key)
                rules[key] = {"method": METHOD_PROFILE_MEAN, "column": column, "complete_columns": columns}
        count = bobbin_service.PROFILE_COUNT_KEY
        if count in by_key and by_key[count].source == "calculated":
            if by_key[count].value_type != "integer":
                raise UnsupportedCalculation(count)
            rules[count] = {"method": METHOD_PROFILE_COUNT, "complete_columns": columns}
        positions = [f.key for f in infos if f.source == "manual" and _POSITION.match(f.key)]
        if positions:
            _require_manual_decimals(by_key, positions)
    missing = sorted(f.key for f in calculated if f.key not in rules)
    if missing:
        raise UnsupportedCalculation(",".join(missing))
    return rules
