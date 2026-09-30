# 인계 티켓(평가 → 구현)

평가 에이전트(claude-code)가 측정에서 나온 결함을 **원인 유형별**로 적는다. 구현 에이전트(Antigravity)는 티켓 단위로 고친다.
서면 한 건에 맞춘 수정은 하지 않는다(AGENTS.md). 수용 기준은 측정 도구의 출력이다. 기준 커밋은 측정한 코드다.

| 티켓 | 유형 | 제목 | 수용 기준(측정) | 상태 |
|---|---|---|---|---|
| [TK-01](TK-01_input_private_use_glyphs.md) | 입력 단계 | 글꼴 구두점 글리프가 사용자 영역 문자로 읽힘 | 서면7 pdf TEXT-1~3, PII-2·7·9·10 | 열림 |
| [TK-02](TK-02_pii_address_detail.md) | 개인정보 | 세부 주소(도로명·번지·동호) 미마스킹 | 서면7 PII-5·6 (pdf·text) | 열림 · 정책 확인 필요 |
| [TK-03](TK-03_injection_audit_stamp.md) | 인젝션 | 감사·권한 표지 미탐지(문구 하나에 맞춘 패턴) | 서면7 INJ-1 (pdf·text) | 열림 |
| [TK-04](TK-04_temporal_internal_contradiction.md) | 규칙 부족 | 처분일보다 뒤의 개정을 그 처분에 적용하라는 주장 | 서면7 TMP-1 (pdf·text) | 열림 |
| [TK-05](TK-05_unreasonable_argument.md) | 규칙 부족 | 공금 유용에 사무관리·정당행위 원용 | 서면7 LEG-1·2 (pdf·text) | 열림 |
| [TK-06](TK-06_false_positive_actualtext_zwsp.md) | 오탐 | Google Docs 줄바꿈 표시를 은닉 신호로 알림(재발) | 서면7 pdf FA-1 | 열림 |
| [TK-07](TK-07_hard_wrapped_citation.md) | 입력 단계 | 줄바꿈으로 갈라진 「법령명」 인용 | 서면7 text CIT-3·6 | 열림 |
| [TK-08](TK-08_exhibit_facts_overfit.md) | 하드코딩 | `exhibit_facts.py`의 사건 문구 의존·오탐 | 문구 부채 0, 변형 시험 | 열림 |
| [TK-09](TK-09_llm_role_redesign.md) | 설계(명세만) | 모델 의견을 판정에 쓰는 구조 | 온라인 채점 도구로 확인 | 열림 |
| [TK-10](TK-10_local_mirror_invented_fields.md) | 증거 계층 | 로컬 미러 자동 보강이 시행일을 지어내고 가지조문을 뭉갬 | 미러 시험(가지조문·항·시행일 null) | 열림 |

## 측정 명령
```
python scripts/probe_document.py run --spec tests/fixtures/probes/case7_suspension.json [--text]
python scripts/score_report.py --report <온라인 보고서.json> --spec tests/fixtures/probes/case7_suspension_online.json
python -m pytest tests/acceptance -q -rxX
python scripts/check_case_literals.py
python scripts/scorecard.py && python scripts/score_gate.py
```
서면7 항목 시험은 미해결을 strict xfail로 두었다. 고쳐서 XPASS(strict)로 시험이 실패하면 평가 에이전트에게 알려 xfail 표시를 지우게 한다.

## 사용자 결정이 필요한 것
- 대리인·법원 주소도 마스킹할지(TK-02)
- 모델 3개가 모두 AI 작성 쪽이어도(라벨이 PARTIAL·FULL로 갈리면) 문서 판정이 `UNCERTAIN`이 되는 현재 합의 규칙을 유지할지(TK-09 말미)
- 기준선(`baseline.json`)은 올리지 않았다. 4ad64a7의 81.7/79.2는 미러 자료 효과(TK-10)라서다. 올릴지는 TK-10 처리 뒤에 정한다.
