# 마이그레이션 (Alembic)

접속 URL은 `alembic.ini`가 아니라 `LV_DATABASE_URL` 환경변수에서 읽는다.
자격증명을 설정파일에 남기지 않기 위함이다(제21.2장).

```bash
export LV_DATABASE_URL='postgresql+psycopg://legal:비밀번호@localhost:5432/legal_verifier'
alembic upgrade head          # 스키마 생성·갱신
alembic downgrade base        # 되돌리기
alembic revision --autogenerate -m "설명"   # 모델 변경 후 리비전 생성
```

`docker compose`의 api 서비스는 기동 시 `alembic upgrade head`를 먼저 실행한다.

## 초기 리비전이 하는 일

1. **pgvector 확장 생성** — `vector` 컬럼을 만들기 전에 `CREATE EXTENSION IF NOT EXISTS vector`를 실행한다.
2. **22개 테이블 생성** — 제17장 데이터 모델.
3. **인덱스**
   - `ix_document_blocks_embedding_hnsw` — 임베딩 근사 최근접 검색 (`vector_cosine_ops`)
   - `ix_findings_project_severity` — 제19.3장 Finding 필터 조합
4. **감사추적 불변성** — `audit_events`에 UPDATE·DELETE를 거부하는 트리거를 건다.
   부록 C 제7항(사용자 Review로 원래 Finding과 Audit Trail을 삭제하지 않는다)을
   애플리케이션이 아니라 DB가 강제한다.

   ```sql
   -- 확인
   UPDATE audit_events SET event_type = 'X';
   -- ERROR: audit_events는 append-only이다: UPDATE 는 허용되지 않는다
   ```

   운영에서는 애플리케이션 롤의 권한도 함께 회수할 것을 권장한다.

   ```sql
   REVOKE UPDATE, DELETE ON audit_events FROM app_role;
   ```

## 방언별 동작

| 컬럼 | PostgreSQL | SQLite |
|---|---|---|
| JSON 계열 | `JSONB` | `TEXT`(직렬화) |
| `document_blocks.embedding` | `vector(1536)` | `TEXT`(JSON 배열) |

`LV_EMBEDDING_DIM`으로 차원을 바꿀 수 있다. 차원을 바꾸면 새 리비전이 필요하다.
pgvector가 없는 PostgreSQL에서는 자동으로 JSON fallback으로 동작한다.

## SQLite

개발·테스트용이다. `init_db()`가 `create_all`로 스키마를 만들므로 마이그레이션 없이 동작하지만,
append-only 트리거와 pgvector 인덱스는 적용되지 않는다.
