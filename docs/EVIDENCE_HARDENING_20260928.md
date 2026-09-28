# 근거 연결과 검증 범위 보강

## 기준

- 시작 main: `de8b5f204e6652b937c17f38015138b6c1a146f7`.
- 급식 납품대금 사례 개선 설계서의 SEC/LAW/FACT/EVI/RAG/ARG/REP/COV 항목을 반영한다.
- 정답지와 사용자 원본은 저장소, Drive 코퍼스, 모델 입력에 추가하지 않는다. 테스트는 숫자·성명이 다른 합성 자료를 사용한다.
- 새 외부 서비스, 저장소 스키마, 상시 워커를 추가하지 않는다. 기존 정책과 호출 한도를 유지한다.

## 변경 계약

| 영역 | 구현 | 확인 위치 |
|---|---|---|
| SEC 01 | 대표자 라벨·괄호·셀 경계 탐지, 일반 명사 오탐 방지, 표 셀 간 문맥 마스킹 | pii_engine/detector.py, engine.py |
| SEC 01 | MASKED 클라우드 요청의 전체 LLMRequest 검사. 불통과 시 비용 예약·전송 전에 차단. 기록은 해시·유형별 개수뿐 | llm_router/privacy.py, router.py |
| LAW 01 | 완전한 정식명칭과 시행령·시행규칙 구별, 문장 내 마지막 인용 법률 보존 | legal_engine/normalize.py |
| LAW 01 | 모호한 식별·연결 장애·시간초과·429 원인과 재시도 가능성 구별 | legal_engine/verifier.py |
| LAW 01 | 국가계약법 제26조, 민법 제492·493조를 최대 3건의 별도 관련 근거로 조회. 명시 인용 개수에 넣지 않음 | legal_engine/related_authorities.py |
| FACT 01 | 존댓말·명사형 사실, 가정·예비·상대방 주장 구별. 납기·변경·부분/최종 납품 역할 기록 | claim_engine/classification.py, extractor.py |
| FACT 01 | 생략된 연도는 같은 블록의 명시 연도에 따른 후보만 기록. 충돌하면 미해결, 확정 Event로 승격하지 않음 | claims[].attributes.partial_date_candidates |
| EVI 01 | 한 문단의 여러 줄 첨부 목록을 개별 인식. 별지 제목만으로 첨부 실재를 단정하지 않음 | claim_engine/attachments.py |
| SEC 02 | 정중한 검증 생략·결론 유도 문구 탐지. 정상 보안 교육 인용과 구분. 지시문 제외 후 본문 검토 유지 | adversarial_engine, document_engine/analysis_text.py |
| RAG 01 | 참고자료 원문 해시·revision·인용 위치와 주장을 연결. 최초/변경 기한의 단순 모순 판정 방지 | rag_engine/contract_facts.py |
| RAG 01 | 같은 계약·동일 파일 버전의 명확한 금액·요율·날짜·집계 규칙만으로 Decimal 조건부 검산 | rag.contract_review |
| RAG 01 | 5개 의견 한도·미연결 주장·문자 제한을 별도 기록. 인용 일치와 의미·적법성 검증을 구별 | rag.claim_coverage, assessment_scope |
| ARG 01 | 모델 불일치·일부 실패는 UNVERIFIED. 자문 상태를 최종 Finding에서도 유지 | semantic_consensus.py, argument_validity_verifier.py |
| ARG 01 | 모델의 모순 의견을 같은 규칙 종류만으로 확정 결과에 합치지 않음. 값 표지 연결 필요 | ai_document_detector.py |
| REP 01 | 최종 levels에서 components 재계산. 과거 고정본은 복사본에서만 표시값 갱신 | report_engine/snapshot.py |
| REP 01 | 공유용 원문 페이지 제거 전 성명 식별, 반복 인용의 무라벨 이름도 보호 | shareable_snapshot |
| COV 01 | RAG 입력에 표 행 포함. 기본 reading_text 계약은 유지. 본문·표·바닥글·지시문·잘린 범위 구별 | document_engine/analysis_text.py |
| 추적성 | 실행 커밋, 관련 구현 파일 해시, 입력 검사·분석 범위 계약 버전 기록 | run_manifest.implementation |

## 법률 판단 경계

제15조 제3항의 지급지연 이자 상계와 납품대금 원금 상계는 동일하지 않다. 관련 근거 탐색은 직접 인용 검증과 분리하고, 현재 조문을 확보했다는 이유만으로 사건 당시 적용법 또는 실제 상계 요건을 확인한 것으로 처리하지 않는다.

공식 근거: [국가계약법 제15조](https://law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq=1031511213), [제26조](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1033564301), [민법 제492·493조](https://law.go.kr/LSW/lsInfoP.do?lsiSeq=246569).

계산에는 자료의 달력상 집계 방식을 사용한다. 귀책, 부분 납품, 제외 기간, 시간 단위, 반올림, 약정 효력·감액·공제 적법성은 미해결 가정으로 남긴다. 청구인의 가정과 참고자료의 사실을 혼합해 단일 확정 계산을 만들지 않는다. 자동 시나리오는 근거가 명확한 참고자료의 집계에 한정한다.

## 검증과 운영

`tests/test_evidence_hardening.py`는 실제 생성한 DOCX 표·바닥글, 첨부 줄바꿈, 잘못된 계약 혼합, 날짜·요율 변형, 모델 불일치·실패, 전송 전 차단, 고정본 불변 등을 검사한다. 기존 법령명·보고서·권한·재시도·화면 테스트도 유지한다. 화면 검사는 데스크톱·태블릿·모바일에서 조건부 검산과 추가 근거 표시를 확인한다.

기존 main CI의 법/시행령 혼동과 두 법률명 선택 실패를 함께 수정한다. 재연결 UI 테스트는 이전 실패 횟수를 초기화하고 첫 4초 백오프를 검사할 시간을 확보한다. 실제 재연결 로직은 바꾸지 않는다. 내구성 테스트의 API fixture는 개발자의 기본 DB에 연결하지 않도록 격리한다.

검증 명령 예시:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_hardening.py tests/test_pii_and_claims.py tests/test_v096_statute_names.py
```

Windows에서는 쓰기 가능한 별도 `--basetemp`와 설치된 `LV_TEST_BROWSER_CHANNEL`을 사용할 수 있다. 전체 CI는 SQLite, PostgreSQL/pgvector/Redis, Docker OCR·기동·마이그레이션 검사를 포함한다. 성능 기준은 낮추지 않는다.

## 남아 있는 검증 한계

- 모의 공급자 검사는 실제 모델의 법리 해석 품질 또는 통계적 정확도를 증명하지 않는다.
- 공개 헬스체크와 배포 SHA 일치는 사용자 계정에서 Drive·실제 공급자를 이용한 전 구간 재분석을 대체하지 않는다.
- 패턴 기반 성명 탐지는 모든 이름을 보장하지 않는다. 공유 전 사람 확인을 유지한다.
- 임의 문서 전체의 시간 관계·주장 전제를 자동 복원하지 않는다. 연도 후보는 같은 블록으로 제한하며 모호한 경우 미해결이다.
- 현재 결정론 검산은 같은 계약의 명시적인 자료 집계에 한정한다. 자료에 없는 조건부 시나리오나 계산 정책을 생성하지 않는다.
- RAG 원문 위치는 실제 비교한 마스킹 발췌문 기준이며 원본 파일 해시·revision과 함께 보존한다. OCR 원본의 정확한 좌표와 동일하다고 주장하지 않는다.
- 12,000자와 선택 발췌문·5개 의견 제한을 유지한다. 미연결 주장이 남아 있으면 전체 내용 확인으로 해석하지 않는다.

작업 브랜치의 정확한 SHA에서 CI가 성공해야 main을 fast-forward 한다. CI 실패 또는 main 분기 시 병합하지 않는다. 배포 완료는 Render `/api/health`의 커밋과 DB 상태 및 공개 정적 자원으로 별도 확인한다.
