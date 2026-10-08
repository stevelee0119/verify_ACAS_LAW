# 은퇴 봉인 세트 (개발용)

점수를 확인한 봉인 세트를 개발용으로 옮겨 둔다(AGENT_ROLES 4절, SEALED_SET_FORMAT_GUIDE 9절). 다시 봉인 시험으로 쓰지 않는다.

- 고정 시험(dev `legal_verifier_testset`·holdout)과 기준선(`docs/scorecards/baseline.json`)에는 섞지 않는다. 측정 조건을 바꾸지 않기 위해서다.
- 형식은 개발 시험과 같다(`ground_truth.json`, `match_spec.json`, PDF). 채점기 `scripts/eval_testset.py`로 잴 수 있다.
- 이 세트의 문장·정답에 맞춘 규칙을 제품 코드에 넣지 않는다. 문서 키 접두 `SD-`는 하드코딩 점검(`scripts/check_hardcoding_diff.py`)이 평가 자료 표식으로 본다.

| 폴더 | 작성 | 봉인 채점(사용자, 비교 전용) | 개발용 이동 |
|---|---|---|---|
| `sealed_20261008` | Codex 격리 세션, 2026-10-08, 문서 8·결함 46 | 운영본 43d3132 = F3 후보 7c36435 = 19.0 / 0.19 / 오탐 0 / 인젝션 방어 | 2026-10-08(사용자 결정) |
| `sealed_20261008b` | Codex 격리 세션, 2026-10-08, 문서 8·결함 54, 지문 835a4090b1fce43b | 운영본 9192b44 = TK-63 후보 97d597a = 24.6 / 0.296 / 오탐 1(A 1) / 인젝션 방어 | 2026-10-09(사용자 결정) |
