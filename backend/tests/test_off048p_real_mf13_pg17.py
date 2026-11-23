"""OFF-04.8P: test real MF-13 authority issuance against an ephemeral migrated database.

This deliberately does not assert that operational vinto_txn.capture E2E is complete.
No MF-13 authorization functions are mocked.
"""
import hashlib
import asyncio
from unittest.mock import patch
from pydantic import SecretStr
from app.config import settings
from app.offline_quality import bobbin_context
from tests.test_assignments_api import call, order_body
from tests.test_f3_bobbins_api import VALUES as F3_VALUES
from tests.test_quality_capture_api import P119_VALUES
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser, create_user
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.authz.capture_gate import gate_for
from app.authz.policies import Operation
from app.authz.errors import AuthorizationDenied, ResourceNotFound
from app.quality.machine_capture_service import submit_machine_capture
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database, database_url
import psycopg
from types import SimpleNamespace
from app.offline_capture.store import PgOfflineCaptureStore
from app.offline_capture.service import AuthzDecision, ContextVerdict, receive_capture
from app.quality.offline_operational_binding import registered_scope_promoter
from app.offline_capture.contract import CaptureIn, canonical_sha256
from app.offline_scope.signing import SigningKey, encode_b64
from app.quality.offline_capture_authority import (
    CaptureScopeDenied, issue_capture_scope, revoke_capture_scope, verify_registered_capture_scope,
)

DDL = Path(__file__).resolve().parents[1] / "offline_capture_migration"
FORM, MACHINE = "VINTO-P1-18", "MP1"


@pytest.fixture(scope="module")
def template():
    name = build_reference_template("off048p_mf13")
    try:
        yield name
    finally:
        drop_database(name)


@pytest.fixture
def db(template):
    name = copy_database(template, "off048p_mf13_case")
    try:
        with connect(name) as connection:
            connection.execute((DDL / "proposed_0032_offline_capture_receipt.sql").read_text(), prepare=False)
            connection.execute((DDL / "proposed_0033_offline_capture_scope_authority.sql").read_text(), prepare=False)
            yield connection
    finally:
        drop_database(name)


def test_real_mf13_grant_and_signed_authority_fail_closed(db):
    admin = create_user(
        db, username=f"offp.admin.{uuid4().hex[:10]}", display_name="OFF QA Admin",
        profile_code="DATA_BALTREK", password="pw-" + uuid4().hex,
        sectors=("BOBINAS",),
    ).user_id
    user = create_user(
        db, username=f"offp.quality.{uuid4().hex[:10]}", display_name="OFF QA Quality",
        profile_code="CALIDAD", password="pw-" + uuid4().hex,
        sectors=("BOBINAS",),
    ).user_id
    who = AuthenticatedUser(
        user_id=user, username="offp.quality", display_name="Quality QA",
        profile_codes=("CALIDAD",), permissions=frozenset({QUALITY_CAPTURE}),
        must_change=False, sectors=frozenset({"BOBINAS"}),
    )
    device = uuid4()
    key = Ed25519PrivateKey.generate()
    public = encode_b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    signer = SigningKey(key, public, "ed25519-" + hashlib.sha256(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:20])

    with pytest.raises(CaptureScopeDenied):
        issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)

    grant_machine_form(db, user_id=user, machine_code=MACHINE, form_code=FORM, actor_id=admin)
    envelope = issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)
    pairs = envelope["payload"]["form_scopes"]
    assert len(pairs) == 1
    assert pairs[0]["machine_code"] == MACHINE and pairs[0]["form_code"] == FORM
    version = pairs[0]["form_version"]
    assert version >= 1
    snapshot = UUID(envelope["payload"]["snapshot_id"])
    payload = {"synthetic": False, "payload": {"numero_de_cuba": "QA"}}
    incoming = CaptureIn(
        capture_id=uuid4(), author_user_id=user, device_key=device,
        form_code=FORM, form_version=version, machine_code=MACHINE,
        scope_snapshot_id=snapshot, context_version=str(snapshot),
        payload_sha256=canonical_sha256(payload), payload=payload,
    )
    with db.transaction():
        assert verify_registered_capture_scope(
            db, principal=who, capture=incoming, trusted_public_key_b64url=public,
        )
        assert not verify_registered_capture_scope(
            db, principal=who, capture=incoming.model_copy(update={"device_key": uuid4()}),
            trusted_public_key_b64url=public,
        )

    # The exact ONLINE service's enforce gate must accept the effective MF-13
    # grant. It may not rely on the previously signed offline snapshot.
    machine_id = db.execute(
        "SELECT id FROM vinto_master.machine WHERE code=%s", (MACHINE,),
    ).fetchone()[0]
    with db.transaction():
        gate_for(who, "enforce", "offline-mf13-positive", Operation.QUALITY_MACHINE_CAPTURE).check_new(
            db, machine_id, MACHINE, FORM,
        )

    revoke_machine_form(db, user_id=user, machine_code=MACHINE, form_code=FORM, actor_id=admin)

    # The offline signature remains stored, but promotion must now be DENIED
    # by the SAME locked MF-13 check that the online capture service invokes.
    # This assertion is about the real gate, not a mock or a second grant table.
    with pytest.raises((AuthorizationDenied, ResourceNotFound)):
        with db.transaction():
            gate_for(who, "enforce", "offline-mf13-revoked", Operation.QUALITY_MACHINE_CAPTURE).check_new(
                db, machine_id, MACHINE, FORM,
            )

    # Exercise the real online machine-capture service (not a stand-in).
    # It MUST deny at the live MF-13 enforce gate before resolving a device,
    # validating fields, or writing operational rows.
    denied_id = uuid4()
    with pytest.raises((AuthorizationDenied, ResourceNotFound)):
        submit_machine_capture(
            db, actor_id=user, machine_code=MACHINE, capture_id=denied_id,
            form_code=FORM, device_key=device, values={},
            sectors=who.sectors,
            gate=gate_for(who, "enforce", "off048p-real-service-revoked", Operation.QUALITY_MACHINE_CAPTURE),
        )
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (denied_id,),
    ).fetchone()[0] == 0

    # End-to-end NEGATIVE: a real receiver and PostgreSQL receipt use the
    # genuine machine service and MF-13 enforce gate after revocation.
    # This is not a successful vinto_txn.capture writing test.
    class Authorizer:
        def authorize(self, principal, capture):
            return AuthzDecision(True)

    class SameContext:
        def evaluate(self, capture):
            return ContextVerdict("same")

    class CentralValidator:
        def validate(self, principal, capture):
            return SimpleNamespace(
                ok=True, errors=[], calculated={}, context_kind="same",
                version_mismatch=False,
            )

    store = PgOfflineCaptureStore(
        lambda: psycopg.connect(database_url(db.info.dbname), autocommit=False)
    )
    actual = receive_capture(
        store, who, incoming, authorizer=Authorizer(),
        context=SameContext(), validator=CentralValidator(),
        promoter=registered_scope_promoter(trusted_public_key_b64url=public),
    )
    assert actual.status == 202
    assert actual.body["operational_registered"] is False
    assert actual.body["reason"] == "operational_not_authorized"
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (incoming.capture_id,),
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1
    replay = receive_capture(
        store, who, incoming, authorizer=Authorizer(),
        context=SameContext(), validator=CentralValidator(),
        promoter=registered_scope_promoter(trusted_public_key_b64url=public),
    )
    assert replay.status == 202 and replay.body == actual.body
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1

    with pytest.raises(CaptureScopeDenied):
        issue_capture_scope(db, who, device_key=device, machine_codes=[MACHINE], signer=signer)

    # Registered scope revocation is independent of MF-13 grant revocation.
    assert revoke_capture_scope(db, snapshot_id=snapshot, subject_user_id=user)
    with db.transaction():
        assert not verify_registered_capture_scope(
            db, principal=who, capture=incoming, trusted_public_key_b64url=public,
        )


@pytest.mark.parametrize("form_code,values", [
    (
        "VINTO-P1-18",
        {
            "producto": "Papel QA offline",
            "numero_de_cuba": "CUBA-TEST",
            "hora_del_ensayo": "08:30",
            "masa_humeda_g": "12.50",
            "masa_seca_g": "2.75",
            "papel_filtro_g": "1.20",
            "papel_muestra_g": "4.30",
            "peso_muestra_g": "3.10",
        },
    ),
    (
        "VINTO-P1-22",
        {
            "numero_de_cuba": "CUBA-TEST",
            "masa_humeda": "12.50",
            "grado_de_refinacion_sr": "23.40",
            "amperaje": "2.10",
        },
    ),
    (
        "VINTO-P1-26",
        {
            "punto_de_muestreo": "Fieltro I",
            "masa_humeda": "12.50",
            "masa_seca": "2.75",
            "absorcion_de_humedad": "0.50",
        },
    ),
    (
        "VINTO-P1-27",
        {
            "ablandador_ph": "7.10",
            "ablandador_dureza": "2.10",
            "ablandador_solidos_disueltos": "110",
            "ablandador_conductividad": "250",
            "agua_alimentacion_caldero_ph": "7.20",
            "agua_alimentacion_caldero_dureza": "2.20",
            "agua_alimentacion_caldero_solidos_disueltos": "120",
            "agua_alimentacion_caldero_conductividad": "260",
            "purga_caldero_ph": "7.30",
            "purga_caldero_dureza": "2.30",
            "purga_caldero_solidos_disueltos": "130",
            "purga_caldero_conductividad": "270",
            "purga_caldero_cloruros": "25",
            "condensado_mp1_ph": "7.40",
            "condensado_mp1_dureza": "2.40",
            "condensado_mp1_solidos_disueltos": "140",
            "condensado_mp1_conductividad": "280",
            "condensado_mp3_ph": "7.50",
            "condensado_mp3_dureza": "2.50",
            "condensado_mp3_solidos_disueltos": "150",
            "condensado_mp3_conductividad": "290",
            "calibracion_equipo_multiparametro": "Calibrado QA",
        },
    ),
])
def test_offline_receipt_registers_real_machine_capture_once_with_mf13(db, form_code, values):
    """Positive PG17 bridge: actual machine service writes vinto_txn.capture.

    The receiver's context/validation adapters are test doubles; the authority
    registry, signature verification, online MF-13 gate, machine service, SQL
    writes and idempotent receipt are NOT mocked.
    """
    admin = create_user(
        db, username=f"offp.admin.{uuid4().hex[:10]}", display_name="OFF QA Admin",
        profile_code="DATA_BALTREK", password="pw-" + uuid4().hex, sectors=("BOBINAS",),
    ).user_id
    quality = create_user(
        db, username=f"offp.quality.{uuid4().hex[:10]}", display_name="OFF QA Quality",
        profile_code="CALIDAD", password="pw-" + uuid4().hex, sectors=("BOBINAS",),
    ).user_id
    user = AuthenticatedUser(
        user_id=quality, username="offp.quality", display_name="Quality QA",
        profile_codes=("CALIDAD",), permissions=frozenset({QUALITY_CAPTURE}),
        must_change=False, sectors=frozenset({"BOBINAS"}),
    )
    grant_machine_form(db, user_id=quality, machine_code=MACHINE, form_code=form_code, actor_id=admin)
    private = Ed25519PrivateKey.generate()
    public_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    public = encode_b64(public_bytes)
    signer = SigningKey(private, public, "ed25519-" + hashlib.sha256(public_bytes).hexdigest()[:20])
    device = uuid4()
    envelope = issue_capture_scope(db, user, device_key=device, machine_codes=[MACHINE], signer=signer)
    pair = next(x for x in envelope["payload"]["form_scopes"] if x["form_code"] == form_code)
    snapshot = UUID(envelope["payload"]["snapshot_id"])

    # Form-specific valid values come from each published form's reference definition.
    # The online service owns final normalization and industrial validation.
    body = {"synthetic": False, "payload": values}
    incoming = CaptureIn(
        capture_id=uuid4(), author_user_id=quality, device_key=device,
        form_code=form_code, form_version=pair["form_version"], machine_code=MACHINE,
        scope_snapshot_id=snapshot, context_version=str(snapshot),
        payload_sha256=canonical_sha256(body), payload=body,
    )

    class Authorized:
        def authorize(self, principal, capture):
            return AuthzDecision(True)

    class SameContext:
        def evaluate(self, capture):
            return ContextVerdict("same")

    class Validator:
        def validate(self, principal, capture):
            return SimpleNamespace(
                ok=True, errors=[], calculated={}, context_kind="same",
                version_mismatch=False,
            )

    store = PgOfflineCaptureStore(
        lambda: psycopg.connect(database_url(db.info.dbname), autocommit=False)
    )
    promoter = registered_scope_promoter(trusted_public_key_b64url=public)

    def send():
        return receive_capture(
            store, user, incoming, authorizer=Authorized(),
            context=SameContext(), validator=Validator(), promoter=promoter,
        )

    previous_releases = db.execute(
        "SELECT count(*) FROM vinto_txn.quality_release"
    ).fetchone()[0]
    first = send()
    assert first.status == 201, first.body
    assert first.body["operational_registered"] is True, first.body
    assert first.body["operational_capture_id"] == str(incoming.capture_id)
    stored = db.execute(
        """SELECT c.id, c.status, c.created_by, c.bobbin_id, c.assignment_id,
                  fv.version_number, f.code
           FROM vinto_txn.capture c
           JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
           JOIN vinto_config.form f ON f.id = fv.form_id
           WHERE c.id=%s""",
        (incoming.capture_id,),
    ).fetchone()
    assert stored == (incoming.capture_id, "submitted", quality, None, None,
                      pair["form_version"], form_code)
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] >= len(values)

    retry = send()
    assert retry.status == 200 and retry.body["outcome"] == "duplicate"
    assert retry.body["operational_registered"] is True
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (incoming.capture_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.quality_release"
    ).fetchone()[0] == previous_releases


@pytest.mark.parametrize("form_code", (
    "VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21",
    "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28",
))
def test_offline_receipt_registers_real_f3_bobbin_quality_p119(db, form_code):
    """F3 -> signed Quality scope -> OFF receiver -> REAL Quality submit.

    The F3 context is created by existing online HTTP services in an ephemeral
    PostgreSQL database, not by hand-inserting rows into operational tables.
    """
    password = "offp-" + uuid4().hex
    def user(profile):
        return create_user(
            db, username=f"offp.f3.{profile.lower()}.{uuid4().hex[:8]}",
            display_name=f"OFF F3 {profile}", profile_code=profile,
            password=password, sectors=("BOBINAS",),
        )
    jefatura, supervision, operacion, calidad, admin = [
        user(p) for p in ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK")
    ]

    async def create_f3():
        async def login(account):
            reply = await call(
                "POST", "/api/auth/login",
                json_body={"username": account.username, "password": password},
            )
            assert reply.status == 200, (account.username, reply.text)
            return reply.set_cookie_value()

        j_cookie = await login(jefatura)
        s_cookie = await login(supervision)
        o_cookie = await login(operacion)
        work = await call(
            "POST", "/api/work-orders",
            json_body=order_body("MP1"), cookie=j_cookie,
        )
        assert work.status == 201, work.text
        published = await call(
            "POST", f"/api/work-orders/{work.json()['id']}/publish",
            cookie=j_cookie,
        )
        assert published.status == 200, published.text
        order = published.json()
        assigned = await call(
            "POST", "/api/assignments/activate",
            cookie=s_cookie,
            json_body={
                "work_order_id": order["id"],
                "baseline_line_id": order["baseline"]["lines"][0]["id"],
            },
        )
        assert assigned.status == 201, assigned.text
        assignment = assigned.json()["assignment"]
        f3 = await call(
            "POST", "/api/bobbins",
            cookie=o_cookie,
            json_body={
                "capture_id": str(uuid4()), "assignment_id": assignment["id"],
                "device_key": str(uuid4()), "values": dict(F3_VALUES),
            },
        )
        assert f3.status == 201, f3.text
        return UUID(f3.json()["bobbin"]["id"])

    # Patching only the app database address is necessary for existing online
    # HTTP creation of the F3 fixture; never mounts an offline route.
    with patch.object(settings, "database_url", SecretStr(database_url(db.info.dbname))):
        bobbin_id = asyncio.run(create_f3())

    who = AuthenticatedUser(
        user_id=calidad.user_id, username=calidad.username,
        display_name=calidad.display_name,
        profile_codes=("CALIDAD",), permissions=frozenset({QUALITY_CAPTURE}),
        must_change=False, sectors=frozenset({"BOBINAS"}),
    )
    from app.authz.policies import Operation
    form = form_code
    grant_machine_form(
        db, user_id=calidad.user_id, machine_code="MP1", form_code=form,
        actor_id=admin.user_id,
    )
    private = Ed25519PrivateKey.generate()
    pub_bytes = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub = encode_b64(pub_bytes)
    signer = SigningKey(
        private, pub, "ed25519-" + hashlib.sha256(pub_bytes).hexdigest()[:20],
    )
    device = uuid4()
    envelope = issue_capture_scope(
        db, who, device_key=device, machine_codes=["MP1"], signer=signer,
    )
    scope = next(e for e in envelope["payload"]["form_scopes"] if e["form_code"] == form)
    assert scope["operation"] == Operation.QUALITY_BOBBIN_CAPTURE.value
    snapshot = UUID(envelope["payload"]["snapshot_id"])
    historical = bobbin_context.load_by_id(db, bobbin_id, who.sectors)
    assert historical is not None and historical["machine_code"] == "MP1"

    # Values are taken from the published form definitions. No automatic or
    # calculated field is supplied by the offline client.
    bobbin_code = historical["bobbin_code"]
    bobbin_values = {
        "VINTO-P1-19": dict(P119_VALUES),
        "VINTO-P1-20": {
            "crepado": "1.20", "gramaje": "20.50",
            **{f"resistencia_{axis}_{position}": "2.50"
               for axis in ("longitudinal", "transversal")
               for position in ("centro", "medio", "extremo")},
            **{f"espesor_{position}": "0.25"
               for position in ("centro", "medio", "extremo")},
        },
        "VINTO-P1-21": {
            "gramaje_01": "20.50", "peso_seco_01": "18.50",
            "humedad_01": "6.50",
        },
        "VINTO-P1-24": {
            "crepado": "1.20", "gramaje": "20.50",
            **{f"resistencia_{axis}_humeda_{position}": "2.50"
               for axis in ("longitudinal", "transversal")
               for position in ("centro", "medio", "extremo")},
            "tiempo_de_curado_condicion": "5.00",
        },
        "VINTO-P1-25": {
            "crepado": "1.20", "curado_min": "5",
            **{f"resistencia_longitudinal_{position}_kgf": "2.50"
               for position in ("centro", "medio", "extremo")},
            **{f"resistencia_longitudinal_humeda_{position}_kgf": "2.20"
               for position in ("centro", "medio", "extremo")},
            "elongacion_media_longitudinal": "1.20",
            "elongacion_media_transversal": "1.10",
            "n_cortes": 2,
        },
        "VINTO-P1-28": {
            "numero_de_bobina": bobbin_code,
            "producto": "Papel de prueba",
            "detalle_motivo_de_rechazo": "Ficha documental ficticia QA",
            "accion_correctiva": "Revisión documental de prueba",
            "peso_rechazado": "1.50",
            "estado_disposicion_final": "Pendiente de revisión",
        },
    }
    values = bobbin_values[form_code]
    payload = {
        "synthetic": False, "payload": values,
        "bobbin": {
            "bobbin_id": str(bobbin_id),
            "context_digest": historical["context_digest"],
        },
    }
    incoming = CaptureIn(
        capture_id=uuid4(), author_user_id=calidad.user_id,
        device_key=device, form_code=form,
        form_version=scope["form_version"], machine_code="MP1",
        scope_snapshot_id=snapshot,
        context_version=bobbin_context.context_version(
            str(snapshot), str(bobbin_id), historical["context_digest"],
        ),
        payload_sha256=canonical_sha256(payload), payload=payload,
    )

    class Authorizer:
        def authorize(self, principal, capture):
            return AuthzDecision(True)
    class Context:
        def evaluate(self, capture):
            return ContextVerdict("same")
    class Validator:
        def validate(self, principal, capture):
            return SimpleNamespace(
                ok=True, errors=[], calculated={}, context_kind="same",
                version_mismatch=False,
            )

    store = PgOfflineCaptureStore(
        lambda: psycopg.connect(database_url(db.info.dbname), autocommit=False)
    )
    promoter = registered_scope_promoter(trusted_public_key_b64url=pub)
    def send():
        return receive_capture(
            store, who, incoming, authorizer=Authorizer(), context=Context(),
            validator=Validator(), promoter=promoter,
        )
    prior_release = db.execute(
        "SELECT status FROM vinto_txn.quality_release WHERE bobbin_id=%s",
        (bobbin_id,),
    ).fetchone()
    first = send()
    assert first.status == 201, first.body
    assert first.body["operational_registered"] is True, first.body
    row = db.execute(
        "SELECT id, bobbin_id, status, created_by FROM vinto_txn.capture WHERE id=%s",
        (incoming.capture_id,),
    ).fetchone()
    assert row == (incoming.capture_id, bobbin_id, "submitted", calidad.user_id)
    replay = send()
    assert replay.status == 200 and replay.body["operational_registered"] is True
    assert db.execute(
        "SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (incoming.capture_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT count(*) FROM vinto_offline.capture_receipt WHERE capture_id=%s",
        (incoming.capture_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT status FROM vinto_txn.quality_release WHERE bobbin_id=%s",
        (bobbin_id,),
    ).fetchone() == prior_release
