# 마이그레이션

MVP는 `apps/api/db.py: init_db()`가 스키마를 생성한다.
운영 배포에서는 Alembic을 사용한다.

```bash
alembic init migrations
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

PostgreSQL 전환 시 `DocumentBlock.embedding`을 `vector` 타입으로 바꾸고
pgvector 인덱스를 생성한다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE document_blocks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector;
CREATE INDEX ON document_blocks USING hnsw (embedding vector_cosine_ops);
```

`audit_events`는 append-only이다. UPDATE·DELETE 권한을 애플리케이션 롤에서 제거할 것을 권장한다.

```sql
REVOKE UPDATE, DELETE ON audit_events FROM app_role;
```
