# GitHub 접근 권한 점검표 (평가·감사용)

작성: 평가 에이전트 2026-10-03 · 점검 방법: 평가 세션에서 읽기 전용 `gh api` 호출(변경 호출 없음). 권한은 **최소 권한**을 원칙으로 한다. 평가·감사 에이전트는 설정을 바꾸지 않고, 설정 변경은 사용자가 한다.

## 1. 현재 상태(2026-10-03 측정)
| 대상 | 결과 | 비고 |
|---|---|---|
| 저장소 정보, 워크플로·실행·job·아티팩트(성적표 115건), 체크 실행, 배포 기록 | **읽기 가능** | `점수 게이트` 기록·성적표를 직접 읽어 대조 |
| PR·이슈(현재 열린 것 0, PR 1·2 병합됨) | 읽기 가능 | |
| `main` 보호(`GET branches/main/protection`), 룰셋(없음), CODEOWNERS 오류(0), 의존성 SBOM | 읽기 가능 | 사용자가 Administration 읽기 연동을 승인한 뒤 가능 |
| 워크플로 수동 실행(`workflow_dispatch`) | 가능(쓰기) | CI 확인에 사용 |
| Actions 권한 설정·시크릿·변수, 환경, 비밀 스캔 경고, 취약점 경고 사용 여부, 협업자, 웹훅, 배포 키 | **프록시가 차단**("not permitted through this proxy") | GitHub 권한이 아니라 세션 프록시 정책이다. 비밀·접근 정보라 **열 필요가 없다**고 판단 |
| 코드 스캔 경고·분석 | **GitHub 권한 부족**(403) | 코드 스캔은 아직 설정되지 않음(`default-setup: not-configured`) |
| Dependabot 경고 | 기능이 꺼져 있음("disabled for this repository") | 권한 문제가 아니다 |

저장소 보안 설정(읽음): 공개 저장소, 비밀 스캔 **켬**·푸시 보호 **켬**, Dependabot 보안 업데이트 꺼짐, 비밀 스캔 비공급자 패턴·유효성 검사 꺼짐, `dependabot.yml` 없음. 병합 방식 병합·스쿼시·리베이스 모두 허용, 병합 후 브랜치 삭제 꺼짐.

## 2. 점검·감사·개선 도출에 필요한 것과 권장
| 목적 | 필요한 것 | 권장 | 조치자 |
|---|---|---|---|
| 의존성 취약점 점검 | 저장소의 **Dependabot alerts 켜기**(읽기는 이미 가능한 경로) | **켠다** | 사용자(Settings → Code security) |
| 정적 분석 결과 점검 | **CodeQL 기본 설정 켜기**(언어: actions·python·javascript-typescript) + 연동의 **Code scanning alerts: read** | 켠다. 결과를 읽으려면 연동 권한 승인이 필요할 수 있다 | 사용자(설정 → 필요 시 연동 권한 승인) |
| 병합 방어선 재점검 | Administration: read(이미 승인됨) | 유지 | — |
| 비밀 노출 점검 | 비밀 스캔은 이미 켜짐. 경고 목록은 프록시가 막음 | 사용자가 Security 탭에서 경고 수만 알려 준다 | 사용자 |
| 설정 변경(보호 규칙 등) | Administration: write | **주지 않는다**(승인 없이 바꾸지 않으며, 변경은 사용자 몫) | — |
| 시크릿·웹훅·배포 키·협업자 | 프록시 차단 + 불필요 | **요청하지 않는다** | — |

## 3. 재점검(2026-10-03, 사용자가 Dependabot alerts와 CodeQL을 켠 뒤)
| 대상 | 결과 |
|---|---|
| CodeQL 기본 설정 | **켜짐 확인**: `default-setup.state=configured`(주 1회, actions·python·javascript-typescript, 쿼리 `default`). 첫 분석이 `main` `9933548`에서 **세 언어 모두 성공**(실행 37080929233) |
| 코드 스캔 경고·분석 읽기 | **403 유지** — 연동에 "Code scanning alerts"(읽기) 권한이 없다. 분석 결과는 있으나 제가 읽지 못한다 |
| Dependabot alerts | 기능은 **켜진 것으로 보임**(오류가 "disabled for this repository"에서 "Resource not accessible by integration"으로 바뀜). 읽기는 **403** — 연동에 "Dependabot alerts"(읽기) 권한이 없다 |
| 보안 설정(변동 없음) | 비밀 스캔·푸시 보호 켜짐, Dependabot 보안 업데이트 꺼짐(의도) |

권한 근거(GitHub 문서): 경고 조회에는 fine-grained 토큰·앱 권한 **"Dependabot alerts" (read)**([문서](https://docs.github.com/en/rest/dependabot/alerts)), **"Code scanning alerts" (read)**([문서](https://docs.github.com/en/rest/code-scanning/code-scanning))가 필요하다.

**대기 중인 사용자 조치(둘 중 하나):** (a) GitHub → Settings → Applications → Installed GitHub Apps → Claude → Configure에서 위 두 권한이 목록에 있는지, 승인 대기 요청이 있는지 확인해 승인(앱이 해당 권한을 제공하는지는 확인하지 못함). (b) 불가하면 Security 탭의 경고 건수·심각도를 알려 주기(제가 대신 읽지 못하는 동안의 대안). (c) 선택: 이 저장소 한정 읽기 전용 fine-grained 토큰(Dependabot alerts·Code scanning alerts: read)을 세션 환경 설정에 저장.

## 4. 승인된 앱 권한 목록 대조(사용자 제공, 2026-10-03)
Claude 연동에 승인된 권한: **읽기** — administration, commit statuses, merge queues, metadata. **읽기·쓰기** — actions, checks, code, discussions, issues, pull requests, repository hooks, workflows.
- **403의 원인 확정:** 이 목록에 **Dependabot alerts·Code scanning alerts(·Secret scanning alerts)가 없다.** 앱 정의에 없는 권한이라 사용자가 승인할 수 있는 항목이 아니다(앱 제공자가 앱 권한을 바꿔야 한다). 따라서 3절의 조치 (a)는 성립하지 않는다.
- **이미 승인된 권한과 실제 동작이 일치:** administration 읽기 → `main` 보호 조회 가능, actions·workflows 쓰기 → 수동 실행 가능, code 쓰기 → 푸시 가능.
- **방어선 메모:** 앱에 `code`·`workflows`·`repository hooks` 쓰기가 있으므로 병합 방어선(필수 확인 2개 + 관리자 포함 적용 + 강제 푸시·삭제 금지)이 앱 토큰에도 적용되는 것이 중요하다. 이 세션에서는 `hooks` 경로를 프록시가 막는다.
- **대체 경로:** (A) 사용자가 Security 탭의 경고 건수·심각도를 알려 준다. (B) 평가 측이 읽기 전용 점검 워크플로를 `.github/workflows/`에 추가한다 — 코드 스캔은 워크플로의 `GITHUB_TOKEN`에 `security-events: read`를 주어 경고를 아티팩트로 내보내면 제가 Actions 읽기로 가져올 수 있다(Dependabot 경고는 `GITHUB_TOKEN`으로 읽을 수 없으므로 `pip-audit`로 의존성 취약점을 직접 점검하는 단계를 둔다). (C) 읽기 전용 fine-grained 토큰을 세션 환경에 저장(이 환경에서 통하는지는 시험 필요). **(B)는 새 워크플로 파일을 추가하는 변경이라 사용자 승인 후에만 만든다.**

## 5. 경고 건수(사용자 보고, 2026-10-03, 경로 A)
| 항목 | 보고된 값 | 평가 측 해석(한계 포함) |
|---|---|---|
| Dependabot vulnerabilities | **No open alerts** | 의존성 그래프가 읽는 매니페스트(pip)와 GitHub 권고 DB 기준으로 열린 경고가 없다는 뜻이다. 매니페스트에 없는 패키지, Docker 베이스 이미지의 OS 패키지는 이 신호가 다루지 않을 수 있다(범위는 확인하지 못함). 시점 값이며 평가 측이 직접 읽은 것이 아니다 |
| Dependabot malware alerts | **disabled** | 꺼짐으로 기록. 켤지는 선택이며 지원 범위는 확인하지 못했다 |
| 코드 스캔(CodeQL) 열린 경고 | **38건**(high 17: URL 부분 문자열 검사 불완전·평문 로깅·비효율 정규식·경로 표현식에 통제되지 않은 데이터·DOM 텍스트의 HTML 재해석 / medium 21: 예외를 통한 정보 노출·prototype 오염 대입·워크플로 permissions 없음) | 규칙별 건수·파일·줄은 6절의 읽기 전용 워크플로로 직접 수집해 **합계가 일치함을 확인**했다. 분류는 6절 |
| 비밀 스캔 열린 경고 | **0건** | 비밀 스캔(켜짐)·푸시 보호(켜짐) 기준 열린 경고가 없다는 뜻. 과거에 해소된 경고, 스캔 패턴 밖의 비밀(임의 형식 비밀번호 등)은 이 신호가 말해 주지 않는다 |

## 6. 코드 스캔 경고 38건 분류(경고 위치 수집 뒤, 2026-10-03)
**수집 방법:** 평가 세션의 연동에는 Code scanning alerts 읽기 권한이 없어, 읽기 전용 워크플로 [`보안 경고 내보내기`](../../.github/workflows/security-export.yml)(`security-events: read`)가 `GITHUB_TOKEN`으로 경고를 읽도록 했다. 아티팩트는 평가 세션의 `gh`가 다른 호스트로의 리다이렉트를 막아 내려받지 못해, 수동 실행에서 `show_locations`를 켜 위치를 실행 로그로 받았다(실행 `37084391114`, `main` 기준). **합계 38건(high 17·medium 21)이 사용자 보고와 일치**하고 규칙별 건수는 아래와 같다. 경고의 줄 번호는 **`main`(`9933548`) 기준**이며 현재 브랜치와 `residual.py`·`pdf_parser.py`가 다르다(제품 코드 19개 파일이 `main`보다 앞섬). 아래 "현재 브랜치" 표기는 그 차이를 뜻한다.

| 규칙(심각도) | 건수 | 위치(`main` 기준) | 판단 | 조치 |
|---|---|---|---|---|
| 워크플로 permissions 없음 (medium) | 6 | `ci.yml:15,86`, `live-source-check.yml:28`, `official-sources.yml:12`, `run-verification.yml:50`, `score-gate.yml:18` | **실제 개선점 — 조치 완료**(7절). `main`에 반영되고 CodeQL이 다시 돌아야 경고가 닫힌다 | 완료(`a5e89ae`) |
| 프로토타입 오염 대입 (medium) | 13 | `admin.js` 83×2·93×2·104×2·194·208×4·241×2 | **결함 확인** — 전부 `pref.* = …`(`pref = preferences[tab]`)이며 `tab`이 URL 해시에서 온다(`#admin/__proto__` 통과를 논리 재현) | [TK-37](TK-37_client_key_validation_prototype.md) |
| 경로 표현식 (high) | 10 | `storage.py:93,102,105,106,108,127`(6) · `storage.py:68,77`·`project_purge.py:67,68`(4) | 앞 6건은 `_abs` 접두 문자열 비교(형제 디렉터리 통과 재현, **결함 확인**). 뒤 4건은 `PROJECT_ID_RE`(허용 문자 `[A-Za-z0-9_-]`)가 이미 막고 있어 **영향 없음**이나 `match`+`$`는 끝 줄바꿈을 허용하므로 `fullmatch`가 맞다 | [TK-35](TK-35_storage_path_prefix_check.md) |
| 비효율 정규식 (high) | 2 | `pdf_parser.py:1297`(`main`; 현재 브랜치 1309-1311 `SINGLE_GLYPH_SHOW_RE`) · `korean_amount.py:65` | **`pdf_parser`는 실제 지수 증가 + 업로드 PDF로 도달 가능**(위치 지정 14회 105바이트 창이 20초 초과로 중단). `korean_amount`는 정규식 자체는 지수지만 호출부가 한글 금액 글자만 넘겨(`원`·`정` 불포함) **현재 도달 불가** | [TK-38](TK-38_regex_polynomial_growth.md) — **우선순위 높음** |
| 예외를 통한 정보 노출 (medium) | 2 | `access.py:369` · `main.py:264` | `access.py:369`: 키 설정 오류 문구(환경변수 이름)를 503 본문에 실음 — **구성 정보 노출**. `main.py:264`: **관리자 전용** 진단 응답에 `capabilities.py:125-127`의 `클래스명: 예외 문구`가 실림 — 낮음 | [TK-36](TK-36_exception_text_in_responses.md) |
| DOM 텍스트의 HTML 재해석 (high) | 1 | `admin.js:108` | `location.href = "/api/admin/users/export.csv?year=" + year + …` — 고정 접두어라 스킴을 바꿀 수 없다(**오탐 성격**). `year`는 `<input type=month>` 값이며 숫자 검증이 없어 `Number(year)`로 줄이는 것이 맞다(경미) | TK-37에 함께 기록 |
| URL 부분 문자열 검사 불완전 (high) | 2 | `residual.py:100`(2건, 같은 줄) | Office 보일러플레이트 XML 분류용 `"schemas.openxmlformats.org" in xml_lower`. **보안 검사가 아님 → 오탐** | 사용자가 GitHub에서 "오탐" 처리(아래 결정 사항) |
| 평문 로깅 (high) | 1 | `identity.py:629` | 관리자 부트스트랩 CLI가 1일 토큰을 한 번 출력 — 이 명령의 목적. **의도된 동작 후보.** 운영 메모: 컨테이너 로그 수집 환경에서 실행하면 토큰이 로그에 남는다 | 사용자가 "수정 안 함" 처리 + 운영 절차 문서화는 구현 측 |
| 평문 저장 (high) | 1 | `routers/identity.py:92` | 세션 쿠키 설정(`HttpOnly`·`SameSite=lax`·`Secure`는 HTTPS 또는 신뢰 프록시 `X-Forwarded-Proto: https`일 때, `access.py:234-240`). 쿠키가 세션 비밀을 담는 것은 설계. **의도된 동작 후보.** 운영 메모: HTTP로 배포하면 `Secure`가 붙지 않으므로 TLS 종단 뒤에서는 `LV_TRUSTED_PROXY_IPS` 설정이 필요 | 사용자가 "수정 안 함" 처리 |

**의존성 취약점(pip-audit, 2026-10-03):** `requirements-test.txt`를 해석해 **82개 패키지에서 취약점 0개**(종료 코드 0, 같은 날 두 번 실행). Dependabot "No open alerts"와 일치한다. 도구는 PyPI 권고 DB 기준이며 Docker 베이스 이미지·OS 패키지는 보지 않는다.

## 7. 조치 기록(사용자 결정 2026-10-03 '추천대로')
| 조치 | 결과 |
|---|---|
| 워크플로 5개에 `permissions: contents: read` 추가 | `a5e89ae`. 적용 뒤 `점수 게이트` 실행 **성공**(`37083839425`). 같은 커밋에서 `CI`를 수동 실행한 결과 **두 작업 모두 성공**(`37083845753`: `테스트 (SQLite + PostgreSQL/pgvector + Redis)`·`Docker OCR readiness`). `live-source-check`·`official-sources`·`run-verification`은 비밀·외부 호출을 쓰고 커밋 표식이나 수동 실행으로만 돌기 때문에 **실행으로 확인하지 않았다**(`actionlint` 정적 검사만 통과) |
| 읽기 전용 점검 워크플로 `보안 경고 내보내기` 추가 | 게이트 아님·필수 확인 아님. 토큰 권한 `contents: read`+`security-events: read`. 수동 실행·주 1회·파일 변경 시 동작 |
| 정규식 복잡도 측정 도구 보강 | `scripts/probe_regex_complexity.py`가 첫 판에서 바이트열 정규식을 건너뛰고 대안 반복 입력이 없어 CodeQL이 가리킨 두 곳을 놓쳤다. 두 가지를 보강했다(TK-38에 수치) |
| GitHub 경고 처리(오탐/수정 안 함) | **사용자 몫** — 오탐 후보 4건(`residual.py:100`×2, `identity.py:629`, `routers/identity.py:92`)을 위 사유와 함께 GitHub Security → Code scanning에서 처리 |
