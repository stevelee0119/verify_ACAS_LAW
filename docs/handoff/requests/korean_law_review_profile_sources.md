# 한국법 검토 프로필: 공개 방법론 출처·선별 기록

- 저장소: https://github.com/anthropics/claude-for-legal
- 고정 커밋: `4a6c651889c97cc9140580363c73e0eb17379c2b` (2026-07-23)
- 확인일: 2026-10-10. GitHub API의 커밋 SHA와 해당 SHA의 파일을 직접 확인했다.
- 라이선스: Apache License 2.0. Copyright 2026 Anthropic PBC.
- [원 라이선스 사본](claude_for_legal_LICENSE.txt). 해당 커밋 트리에 별도 NOTICE 파일은 없다.
- 변경 표시: ACASia_LAW가 아래 방법론만 한국어·한국법·기존 JSON 계약에 맞게 선별하고 재작성했다. 원 플러그인/자동 실행 에이전트/지침 파일은 설치하거나 실행하지 않았다.

| 원 파일 (모두 위 커밋 기준) | 확인한 지침과 적용 | 제외 |
|---|---|---|
| [claim-chart/SKILL.md](https://github.com/anthropics/claude-for-legal/blob/4a6c651889c97cc9140580363c73e0eb17379c2b/litigation-legal/skills/claim-chart/SKILL.md), blob `bc7048b2b0925bd689b658f09075c1a516da9c18` | Workflow 7–8, Review mode, Civil claim chart: 요건마다 증거·위치 연결, 공백/상충 표시, 가장 강한 반론 | CACI/NY PJI/Restatement 요건 목록, MSJ·배심 절차, Markman·특허 규칙, 기본 미국 관할, 편향된 공백 과대 표기 |
| [brief-section-drafter/SKILL.md](https://github.com/anthropics/claude-for-legal/blob/4a6c651889c97cc9140580363c73e0eb17379c2b/litigation-legal/skills/brief-section-drafter/SKILL.md), blob `724834ca8fd5d36ffd9cebe95f2dd76ccd6c3a07` | Never fill the gap / Source attribution / No silent supplement / 상대방 최선 반론: 원문 없는 인용 금지, 출처 누락 시 유보, 반론 근거 검토 | Rule 11·미국 local rules·제출 절차, model knowledge에서 회상한 인용의 허용, 외부 검색·설치·자동화 |
| [chronology/SKILL.md](https://github.com/anthropics/claude-for-legal/blob/4a6c651889c97cc9140580363c73e0eb17379c2b/litigation-legal/skills/chronology/SKILL.md), blob `15ba24ba1ad7a332a64b579d016c8fd7081f3432` | Step 2 Source attribution, What this skill does not do: 문서 사실과 법적 해석의 출처 구분, 자료 공백/모순 비보충 | 미국/영국 privilege·discovery 규칙, 소송 기한 계산, 계정·MCP·matter 자동 관리 |

모델이 사용하는 지침은 `packages/legal_engine/argument_validity_verifier.py`의 고정 상수 `_KOREAN_OPINION_SYSTEM`이다. 이 지침은 법적 권위가 아니라 검토 방법이다. 한국의 실체법·절차·시행본은 기존 공식 DB와 전달된 원문을 통해 확인해야 한다. Claude Code 플러그인 설치는 서버 API 요청에 자동 반영되지 않는다.
