"""FOFF-02B: la preparación no ofrece máquinas ni formularios sin grant efectivo."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Response

from app.offline_production import list_offline_production_offers


def _form(code, eligible):
    return SimpleNamespace(code=code, name=code, version_number=4, eligible=eligible)


def _machine(code, forms, bobbin_forms=None):
    return SimpleNamespace(code=code, name=code, forms=forms, bobbin_forms=bobbin_forms)


def test_offline_production_offers_fail_closed():
    catalog = SimpleNamespace(sectors=[
        SimpleNamespace(code="CONVERSION", machines=[
            _machine("GAMBINI", [_form("VINTO-P1-11", True), _form("VINTO-P1-12", False)]),
            _machine("SINCRO_II", [_form("VINTO-P1-16", None)]),
        ]),
        SimpleNamespace(code="REBOBINADO", machines=[
            _machine("COPASA", [_form("VINTO-P1-07", False)]),
        ]),
        SimpleNamespace(code="BOBINAS", machines=[
            _machine("MP3", [], [_form("VINTO-P1-03", True)]),
        ]),
        SimpleNamespace(code="UNRECOGNIZED", machines=[
            _machine("X", [_form("VINTO-P1-99", True)]),
        ]),
    ])
    user = SimpleNamespace(sectors=["CONVERSION", "BOBINAS"])
    response = Response()
    with patch("app.offline_production.production_machines", return_value=catalog) as resolver:
        result = list_offline_production_offers(response=response, user=user, connection=object())
    assert response.headers["Cache-Control"] == "private, no-store"
    assert result["captureEnabled"] is False
    assert [(x["sectorCode"], x["machineCode"], x["formCode"]) for x in result["offers"]] == [
        ("CONVERSION", "GAMBINI", "VINTO-P1-11"),
        ("BOBINAS", "MP3", "VINTO-P1-03"),
    ]
    assert resolver.call_args.kwargs["user"] is user


def test_offline_production_offers_empty_is_not_demo_fallback():
    user = SimpleNamespace(sectors=[])
    with patch("app.offline_production.production_machines",
               return_value=SimpleNamespace(sectors=[])):
        assert list_offline_production_offers(response=Response(), user=user, connection=object()) == {
            "offers": [], "captureEnabled": False,
        }
