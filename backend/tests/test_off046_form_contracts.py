"""OFF-04.6 Phase A: integrated compatibility review of the ten Quality forms, as an executable contract (no database).

For each form: the contract the ONLINE route uses (seed definition, versions, machines, field types, options, required flags, calculated fields) must be exportable to a device with the
offline vocabulary, and every server-calculated field must have a rule derived from the same constants the online route calculates with. A difference here is a finding, not a surprise."""
import pytest

from app.offline_quality import registry, rules
from app.qa_pilot_auth import SUPPORTED_FORMS, synthetic_definition, synthetic_name
from tests import off046_support as T

DEVICE_TYPES = {"text", "textarea", "decimal", "integer", "boolean", "date", "time"}      # offline-draft-schema.ts
DEFINITION_KEYS = {"form_code", "form_name", "form_version", "area", "source_definition_checksum", "published_at", "groups", "fields", "calculated_rules", "option_dependencies",
                   "recipe_bundle_included", "capture_eligible", "note"}
FIELD_KEYS = {"key", "label", "description", "value_type", "source", "required", "unit", "classification", "proposal", "needs_validation", "display_order", "calculation_rule", "options"}


def test_the_batch_is_exactly_the_ten_forms_the_online_routes_admit():
    assert tuple(sorted(registry.machine_forms() & set(registry.BATCH_FORMS))) == T.BY_MACHINE
    assert tuple(sorted(registry.bobbin_forms() & set(registry.BATCH_FORMS))) == T.BY_BOBBIN
    assert set(registry.BATCH_FORMS) <= registry.machine_forms() | registry.bobbin_forms()
    assert not (registry.machine_forms() & registry.bobbin_forms())                      # the online policy sets are disjoint
    assert {s.code for s in registry.all_specs()} == set(T.FORMS) == set(SUPPORTED_FORMS)
    for code in T.BY_MACHINE:
        assert registry.spec_for(code).operation.value == "quality_machine_capture"
    for code in T.BY_BOBBIN:
        assert registry.spec_for(code).operation.value == "quality_bobbin_capture"
    assert registry.spec_for("VINTO-P1-03") is None and registry.spec_for("VINTO-P1-99") is None   # a form no Quality route admits is never exported


@pytest.mark.parametrize("form", T.FORMS)
def test_contract_of_each_form(form):
    seed = T.seed(form)
    assert seed["code"] == form and seed["area"] == "quality" and seed["groups"] == [] and set(seed["machines"]) >= {"MP1", "MP3"}
    assert isinstance(seed["version_number"], int) and seed["version_number"] >= 1
    fields = seed["fields"]
    assert 1 <= len(fields) <= 128                                                           # package and draft limits (MAX_FIELDS / MAX_VALUES)
    assert {f["value_type"] for f in fields} <= DEVICE_TYPES                                  # the editor supports every type the form uses
    assert len({f["key"] for f in fields}) == len(fields)
    for f in fields:
        assert f["source"] in ("manual", "calculated")                                       # no automatic source in the batch
        assert not (f["source"] == "calculated" and f["required"])
        for o in f.get("options", []):
            assert set(o) == {"option_key", "label", "display_order"}
    # every calculated field has a server rule, and every operand is a manual decimal of the same definition
    r = rules.calculated_rules(form, fields)
    assert set(r) == set(T.calculated_keys(form))
    by_key = {f["key"]: f for f in fields}
    for key, rule in r.items():
        assert tuple(rule) == rules.RULE_KEYS[rule["method"]]
        for operand in rule.get("operands", []) + [rule[k] for k in ("numerator", "denominator") if k in rule]:
            assert by_key[operand]["source"] == "manual" and by_key[operand]["value_type"] == "decimal"


@pytest.mark.parametrize("form", T.FORMS)
def test_the_synthetic_definition_of_each_form_is_exportable(form):
    d = synthetic_definition(form, T.version(form))
    assert set(d) == DEFINITION_KEYS and d["capture_eligible"] is False and d["recipe_bundle_included"] is False and d["groups"] == [] and d["option_dependencies"] == []
    assert d["form_name"] == synthetic_name(form) and d["form_name"].startswith("SINTÉTICO") and d["note"].startswith("Synthetic QA-only")
    assert d["source_definition_checksum"] == T.seed(form)["definition_checksum"] and len(d["source_definition_checksum"]) == 64
    assert all(set(f) == FIELD_KEYS for f in d["fields"])
    assert [(f["key"], f["value_type"], f["required"] if f["source"] == "manual" else False) for f in d["fields"]] == [
        (f["key"], f["value_type"], bool(f["required"]) if f["source"] == "manual" else False) for f in sorted(T.seed(form)["fields"], key=lambda x: x["display_order"])]
    assert set(d["calculated_rules"]) == set(T.calculated_keys(form))
    assert all(f["required"] is False for f in d["fields"] if f["source"] == "calculated")


def test_a_definition_whose_calculated_field_has_no_rule_is_refused_fail_closed():
    fields = [{"key": "a", "value_type": "decimal", "source": "manual"}, {"key": "extra_calc", "value_type": "decimal", "source": "calculated"}]
    with pytest.raises(rules.UnsupportedCalculation):
        rules.calculated_rules("VINTO-P1-22", fields)                    # P1-22 has no calculated field: an unknown one is refused, never silently exported
    with pytest.raises(rules.UnsupportedCalculation):                     # an operand that is not a manual decimal
        rules.calculated_rules("VINTO-P1-26", [{"key": "porcentaje_cantidad_de_seco", "value_type": "decimal", "source": "calculated"},
                                               {"key": "masa_seca", "value_type": "text", "source": "manual"}, {"key": "masa_humeda", "value_type": "decimal", "source": "manual"}])


def test_a_different_version_than_the_contract_is_not_issued():
    from app.qa_offline_pilot import PilotConfigError
    for form in T.FORMS:
        with pytest.raises(PilotConfigError):
            synthetic_definition(form, T.version(form) + 1)


def test_form_specific_findings_recorded_by_the_review():
    """Findings of the integrated review that the design resolves (documented in docs/OFF-04-6): see the assertions."""
    assert T.version("VINTO-P1-24") == 5 and T.version("VINTO-P1-25") == 4 and T.version("VINTO-P1-26") == 3     # versions are per form: the contract carries each one
    assert any(f.get("options") for f in T.seed("VINTO-P1-26")["fields"])                                          # closed option list (P1-26 sampling point)
    assert any(f["value_type"] == "time" for f in T.seed("VINTO-P1-18")["fields"])                                 # time field (P1-18 test hour)
    assert sum(1 for f in T.seed("VINTO-P1-21")["fields"] if f["source"] == "manual" and f["key"][-2:].isdigit()) == 81     # 27 positions x 3 columns
    assert [f["key"] for f in T.seed("VINTO-P1-28")["fields"] if "bobina" in f["key"]] == ["numero_de_bobina"]      # declared bobbin number: must equal the bobbin
