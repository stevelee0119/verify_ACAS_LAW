# Codex 전달문 (통합본 — 이 파일 하나만 전달한다)

갱신: 2026-10-04 평가 측(PR #15 수용·병합 뒤). 이전 전달문을 모두 대체한다.

```
[Codex 작업 — 통합 지시 2026-10-04]

[A] 버전 커밋 0.10.0 — 완료(PR #15 472861e 수용·병합). 할 일 없음.

[B] (낮음, 0.10.0 배포 뒤) CodeQL 로그 주입 경보 2건 정리 — apps/api/project_purge.py 63·73행
 - 실제 위험은 없다(%r 기록, 값은 DB의 프로젝트 ID·PROJECT_ID_RE 검증). CodeQL이 repr을 정화로 인식하지 않아 경보가 남는다.
 - 73행은 PROJECT_ID_RE 검증 블록 안인데도 경보가 났다. 따라서 검증을 앞에 두는 방식으로는 경보가 사라지지 않을 수 있다.
   기록용 값을 CodeQL이 정화로 인식하는 형태로 만든다: 도우미 하나(예: _log_id(v) = str(v).replace("\r", "").replace("\n", "")[:40])를 두고
   63·73행(과 routers/projects.py의 project_purge_retry 로그)에 쓴다. 동작·메시지 형식은 바꾸지 않는다.
 - 새 브랜치 codex/codeql-purge-log에서 커밋 1개. 관련 시험(tests/test_project_lifecycle.py, tests/test_storage_encryption.py)만 돌린다(로그 문구를 단언하는 기존 시험은 없음, 평가 측 확인). Steve_ACASiaLAW 대상 PR, CI 뒤 '검토 요청'.

[C] (보통, 0.10.0 다음 릴리스 전) TK-58 계좌번호의 RRN 분류 — docs/handoff/TK-58_account_number_labeled_rrn.md
 - 가림은 되나 종류가 RRN으로 표시된다(서면9 PDF, 9933548 ACCOUNT → 22ca134 RRN).
 - 요구·수용은 티켓 3·4절. 필수 보장(연락처·주민등록번호 누락 0)을 깨지 않는다. 평가 측 비공개 세트는 평가 측이 잰다.
 - 새 브랜치 codex/tk58-account-kind, 관련 시험(tests/ 중 pii 관련)만 돌린다. Steve_ACASiaLAW 대상 PR, CI 뒤 '검토 요청'.
```
