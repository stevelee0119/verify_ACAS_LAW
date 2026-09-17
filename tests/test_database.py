"""DB 방언 대응 및 마이그레이션.

PostgreSQL 검증은 LV_TEST_DATABASE_URL이 지정된 경우에만 수행한다.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text

from apps.api.db import EmbeddingType, JSONType, get_engine, init_db

IS_POSTGRES = "postgresql" in (os.getenv("LV_TEST_DATABASE_URL") or "")
postgres_required = pytest.mark.skipif(not IS_POSTGRES, reason="PostgreSQL 테스트 DB 미지정")

EXPECTED_TABLES = {
    "organizations", "users", "projects", "project_members",
    "documents", "document_versions", "document_pages", "document_blocks",
    "citations", "claims", "entities", "events",
    "verification_runs", "verification_checks", "findings", "evidence",
    "source_records", "model_executions", "api_executions",
    "audit_events", "reports", "export_artifacts",
}


def test_all_tables_created():
    init_db()
    tables = set(inspect(get_engine()).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_json_roundtrip_on_current_dialect():
    """JSONType이 어떤 방언에서도 동일한 파이썬 값으로 왕복한다."""
    from apps.api.db import Project, get_session_factory

    session = get_session_factory()()
    try:
        payload = {"당사자": ["원고 홍길동", "피고 갑"], "중첩": {"값": 1}}
        project = Project(name="방언 테스트", parties=payload["당사자"], key_dates={"기준일": "2020-01-01"})
        session.add(project)
        session.commit()
        session.expunge_all()
        loaded = session.get(Project, project.id)
        assert loaded.parties == payload["당사자"]
        assert loaded.key_dates == {"기준일": "2020-01-01"}
    finally:
        session.close()


@pytest.fixture()
def owned_document():
    """FK 제약을 만족하는 Project·Document를 만들고 종료 시 정리한다."""
    from apps.api.db import Document, Project, get_session_factory

    session = get_session_factory()()
    project = Project(name="DB 테스트 사건")
    session.add(project)
    session.flush()
    document = Document(
        project_id=project.id, filename="t.pdf", sha256="0" * 64, storage_key="originals/t.pdf"
    )
    session.add(document)
    session.commit()
    yield session, document.id
    try:
        from apps.api.db import DocumentBlock

        session.query(DocumentBlock).filter(DocumentBlock.document_id == document.id).delete()
        session.query(Document).filter(Document.id == document.id).delete()
        session.query(Project).filter(Project.id == project.id).delete()
        session.commit()
    finally:
        session.close()


def test_embedding_roundtrip(owned_document):
    """embedding은 SQLite(JSON)·PostgreSQL(vector) 모두에서 float 리스트로 다룬다."""
    from apps.api.db import DocumentBlock

    session, document_id = owned_document
    if True:
        vector = [0.0] * 1536
        vector[0], vector[1] = 0.5, -0.25
        session.add(
            DocumentBlock(id="blk_embed_test", document_id=document_id, page=1, text="본문", embedding=vector)
        )
        session.commit()
        session.expunge_all()
        loaded = session.get(DocumentBlock, "blk_embed_test")
        assert len(loaded.embedding) == 1536
        assert abs(loaded.embedding[0] - 0.5) < 1e-6
        assert abs(loaded.embedding[1] + 0.25) < 1e-6


@postgres_required
def test_postgres_uses_jsonb_and_vector():
    engine = get_engine()
    assert engine.dialect.name == "postgresql"
    with engine.connect() as connection:
        jsonb_count = connection.execute(
            text("select count(*) from information_schema.columns "
                 "where table_schema='public' and data_type='jsonb'")
        ).scalar_one()
        assert jsonb_count > 0, "PostgreSQL에서는 JSONB로 저장되어야 한다"

        udt = connection.execute(
            text("select udt_name from information_schema.columns "
                 "where table_name='document_blocks' and column_name='embedding'")
        ).scalar_one()
        assert udt == "vector", "pgvector 설치 시 vector 타입을 사용해야 한다"


@postgres_required
def test_audit_events_are_append_only_in_db():
    """부록 C 제7항을 DB 제약으로도 강제한다.

    해시 체인을 깨뜨리지 않도록 정상 경로로 만든 이벤트에 대해
    UPDATE·DELETE가 거부되는지만 확인한다.
    """
    from sqlalchemy.exc import DatabaseError

    from packages.audit_engine import AuditChain
    from packages.common.enums import AuditEventType

    from apps.api.audit_sink import DBAuditSink
    from apps.api.db import get_session_factory

    engine = get_engine()
    with engine.connect() as connection:
        has_trigger = connection.execute(
            text("select count(*) from pg_trigger where tgname='audit_events_no_update_delete'")
        ).scalar_one()
    if not has_trigger:
        # create_all 경로에는 트리거가 없다. 마이그레이션을 적용한 환경(CI)에서는
        # 반드시 있어야 하므로 LV_REQUIRE_AUDIT_TRIGGER=1이면 실패시킨다.
        message = "감사추적 append-only 트리거가 없다. alembic upgrade head를 적용했는지 확인한다."
        if os.getenv("LV_REQUIRE_AUDIT_TRIGGER") == "1":
            pytest.fail(message)
        pytest.skip(message + " (create_all 경로에서는 정상)")

    session = get_session_factory()()
    try:
        chain = AuditChain(sink=DBAuditSink(session))
        event = chain.record(AuditEventType.UPLOAD, {"probe": True}, project_id="append_only_probe")
        assert chain.verify()["valid"] is True
    finally:
        session.close()

    for statement in (
        "update audit_events set event_type='TAMPERED' where event_hash=:hash",
        "delete from audit_events where event_hash=:hash",
    ):
        with pytest.raises(DatabaseError):
            with engine.begin() as connection:
                connection.execute(text(statement), {"hash": event.event_hash})

    # 변경이 거부되었으므로 체인은 그대로 유효해야 한다
    session = get_session_factory()()
    try:
        assert AuditChain(sink=DBAuditSink(session)).verify()["valid"] is True
    finally:
        session.close()


@postgres_required
def test_vector_similarity_search_works(owned_document):
    """pgvector 근사 검색이 동작한다(제3.2장 임베딩 검색 기반)."""
    from apps.api.db import DocumentBlock

    session, document_id = owned_document
    base = [0.0] * 1536
    near = base.copy(); near[0] = 1.0
    far = base.copy(); far[1] = 1.0
    session.add_all([
        DocumentBlock(id="blk_near", document_id=document_id, page=1, text="가까운 문단", embedding=near),
        DocumentBlock(id="blk_far", document_id=document_id, page=1, text="먼 문단", embedding=far),
    ])
    session.commit()

    query = "[" + ",".join(["1.0"] + ["0.0"] * 1535) + "]"
    rows = session.execute(
        text("select id from document_blocks where document_id=:doc "
             "order by embedding <=> CAST(:q AS vector) limit 1"),
        {"doc": document_id, "q": query},
    ).all()
    assert rows[0][0] == "blk_near"


# --- PaaS 접속정보 정규화 -------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        # Render·Heroku 계열이 주는 형식
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        # 드라이버 미지정 형식 (기본값 psycopg2를 찾아 실패한다)
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        # 이미 올바른 형식은 그대로 둔다
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
        ("", ""),
    ],
)
def test_database_url_normalization(raw, expected):
    from packages.common.config import normalize_database_url

    assert normalize_database_url(raw) == expected


def test_paas_standard_env_names_are_honoured(monkeypatch):
    """PaaS가 주입하는 DATABASE_URL·REDIS_URL을 별도 매핑 없이 인식한다."""
    from packages.common import config

    monkeypatch.delenv("LV_DATABASE_URL", raising=False)
    monkeypatch.delenv("LV_CELERY_BROKER", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    config.reset_settings()
    try:
        settings = config.get_settings()
        assert settings.database_url == "postgresql+psycopg://u:p@h:5432/db"
        assert settings.celery_broker == "redis://cache:6379"
        assert settings.celery_backend == "redis://cache:6379"
    finally:
        config.reset_settings()


def test_explicit_lv_vars_take_precedence(monkeypatch):
    from packages.common import config

    monkeypatch.setenv("DATABASE_URL", "postgres://ignored:p@h/db")
    monkeypatch.setenv("LV_DATABASE_URL", "postgresql+psycopg://chosen:p@h/db")
    config.reset_settings()
    try:
        assert "chosen" in config.get_settings().database_url
    finally:
        config.reset_settings()
