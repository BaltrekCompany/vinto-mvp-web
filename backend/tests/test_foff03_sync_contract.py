"""FOFF-03: signed producer data is untrusted until server verification."""
import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response
from pydantic import SecretStr

from app.foff_conversion_preparation import sign_conversion_preparation
from app.foff_conversion_capture_authority import sign_conversion_capture_authority
from app.foff_conversion_sync_router import (
    OfflineConversionIn, _verified_preparation, _verified_capture_authority, _require_original_context, OriginalContextChanged, receive_conversion_capture,
)
from app.quality.offline_capture_scope import _canonical


def fixture():
    user=SimpleNamespace(user_id=uuid.uuid4())
    device=uuid.uuid4()
    assignment=uuid.uuid4()
    capture=uuid.uuid4()
    references={
        "schema":"vinto.foff.conversion.references.v1",
        "machine_code":"GAMBINI","form_code":"VINTO-P1-16","form_version":4,
        "article_code":"10342",
        "definition":{"fields":[{"key":"merma_kg","source":"manual"}],"groups":[]},
        "references":{"recipe_material_codes":[],"pallet":None},
    }
    reference_sha=hashlib.sha256(_canonical(references)).hexdigest()
    context={
        "assignment_id":str(assignment),"work_order_id":str(uuid.uuid4()),
        "line_id":str(uuid.uuid4()),"machine_code":"GAMBINI",
        "form_code":"VINTO-P1-16","form_version":4,
        "article_code":"10342","shift_code":"M","operating_date":"2026-11-27",
        "reference_sha256":reference_sha,
    }
    context["context_digest"]=hashlib.sha256(_canonical(context)).hexdigest()
    envelope=sign_conversion_preparation(seed_hex="01"*32,user_id=str(user.user_id),
        device_key=str(device),context=context,now=datetime.now(timezone.utc))
    values={"merma_kg":"1.25"}
    body=OfflineConversionIn(
        capture_id=capture,author_user_id=user.user_id,device_key=device,
        form_code="VINTO-P1-16",form_version=4,assignment_id=assignment,
        machine_code="GAMBINI",scope_snapshot_id=envelope["payload"]["snapshot_id"],
        payload_sha256=hashlib.sha256(_canonical(values)).hexdigest(),
        values=values,preparation=envelope,reference_package=references,
    )
    return user,body


def check(user,body):
    with patch("app.foff_conversion_sync_router.settings.offline_conversion_preparation_signing_seed_hex",
               SecretStr("01"*32)):
        return _verified_preparation(body,user)


def test_signed_reference_and_identity_accepted_without_capture_right():
    user,body=fixture()
    context,expired=check(user,body)
    assert context["assignment_id"]==str(body.assignment_id)
    assert expired is False


def test_changed_reference_package_rejected():
    user,body=fixture()
    body.reference_package["definition"]["fields"][0]["key"]="alterado"
    with pytest.raises(HTTPException) as error:
        check(user,body)
    assert error.value.status_code==409


def test_cross_user_preparation_rejected():
    user,body=fixture()
    with pytest.raises(HTTPException) as error:
        check(SimpleNamespace(user_id=uuid.uuid4()),body)
    assert error.value.status_code==403


def test_signed_context_cannot_be_retargeted():
    user,body=fixture()
    body.machine_code="OMET_I"
    with pytest.raises(HTTPException) as error:
        check(user,body)
    assert error.value.status_code==409


def test_disabled_capture_does_not_access_database():
    user,body=fixture()
    with patch("app.foff_conversion_sync_router.settings.offline_conversion_capture_enabled",False):
        with pytest.raises(HTTPException) as error:
            receive_conversion_capture(body,Response(),user,connection=object())
    assert error.value.status_code==503

def test_separate_capture_authority_required_and_not_interchangeable():
    user,body=fixture()
    with patch("app.foff_conversion_sync_router.settings.offline_conversion_capture_signing_seed_hex",
               SecretStr("02"*32)):
        with pytest.raises(HTTPException) as missing:
            _verified_capture_authority(body,user)
        assert missing.value.status_code==403
        context=body.preparation["payload"]["context"]
        scope=sign_conversion_capture_authority(
            seed_hex="02"*32,user_id=str(user.user_id),device_key=str(body.device_key),
            snapshot_id=str(body.scope_snapshot_id),assignment_id=str(body.assignment_id),
            machine_code=body.machine_code,form_code=body.form_code,
            form_version=body.form_version,grant_id=str(uuid.uuid4()),
            reference_sha256=context["reference_sha256"],
        )
        body.capture_authority=scope
        assert _verified_capture_authority(body,user) is False
        # An attacker cannot promote the preparation_only envelope into CAPTURE.
        body.capture_authority=body.preparation
        with pytest.raises(HTTPException):
            _verified_capture_authority(body,user)

def test_original_assignment_snapshot_must_match_signed_OT_line_turn():
    user,body=fixture()
    ctx=body.preparation["payload"]["context"]
    view=SimpleNamespace(
        work_order_id=uuid.UUID(ctx["work_order_id"]),
        line=SimpleNamespace(id=uuid.UUID(ctx["line_id"]),article_code=ctx["article_code"]),
        machine_code=ctx["machine_code"],shift_code=ctx["shift_code"],
        operating_date=datetime.fromisoformat(ctx["operating_date"]).date(),
    )
    with patch("app.foff_conversion_sync_router.assignment_service.get_assignment",return_value=view):
        _require_original_context(object(),context=ctx,assignment_id=body.assignment_id,
                                  sectors=("CONVERSION",))
    for attribute,bad in (
        ("shift_code","N"),("machine_code","OMET_II"),
        ("work_order_id",uuid.uuid4()),
        ("line",SimpleNamespace(id=uuid.uuid4(),article_code=ctx["article_code"])),
    ):
        invalid=SimpleNamespace(**{**vars(view),attribute:bad})
        with patch("app.foff_conversion_sync_router.assignment_service.get_assignment",return_value=invalid):
            with pytest.raises(OriginalContextChanged):
                _require_original_context(object(),context=ctx,assignment_id=body.assignment_id,
                                          sectors=("CONVERSION",))
