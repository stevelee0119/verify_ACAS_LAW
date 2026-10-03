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
| 코드 스캔(CodeQL) 열린 경고 | **38건**(high 17: URL 부분 문자열 검사 불완전·평문 로깅·비효율 정규식·경로 표현식에 통제되지 않은 데이터·DOM 텍스트의 HTML 재해석 / medium 21: 예외를 통한 정보 노출·prototype 오염 대입·워크플로 permissions 없음) | 종류만 받았고 **종류별 건수와 파일·줄은 받지 못했다.** 분류는 6절 |
| 비밀 스캔 열린 경고 | **0건** | 비밀 스캔(켜짐)·푸시 보호(켜짐) 기준 열린 경고가 없다는 뜻. 과거에 해소된 경고, 스캔 패턴 밖의 비밀(임의 형식 비밀번호 등)은 이 신호가 말해 주지 않는다 |

## 6. 코드 스캔 경고 38건 분류(평가 측 코드 읽기, 2026-10-03)
**한계(먼저):** 평가 측은 경고 목록을 읽지 못해(연동에 Code scanning alerts 권한 없음) 경고의 파일·줄·종류별 건수를 모른다. 아래는 보고된 **규칙 이름**에 해당할 만한 코드를 저장소에서 직접 찾은 것이다. 찾은 지점이 실제 경고와 같은지, 경고 건수와 맞는지는 **확정하지 못했다.** `tests/`·`scripts/`·`docs/`의 일부는 점검 범위 밖이다. 제품 코드는 수정하지 않았다.

| 규칙(심각도, 보고된 합계) | 평가 측이 찾은 후보 | 판단 | 조치 |
|---|---|---|---|
| 워크플로 permissions 없음 (medium) | 작업(job) 6개: `ci.yml` 2(`test`·`docker-ocr`), `live-source-check.yml`·`official-sources.yml`·`run-verification.yml`·`score-gate.yml` 각 1. 이 워크플로들은 checkout·아티팩트 업로드만 하고 `git push`·PR·이슈 쓰기가 없다 | **실제 개선점**(기본 토큰 권한이 저장소 설정에 따라 넓어질 수 있음). 작업 단위 6개라 21건 중 6건에 해당할 가능성이 높다 | **제안(사용자 승인 대기):** 다섯 파일 최상단에 `permissions:\n  contents: read` 추가. 필수 확인(`ci.yml` test·`score-gate`)에 영향이 없는지 변경 후 실행으로 확인 |
| 경로 표현식에 통제되지 않은 데이터 (high) | `packages/common/storage.py:92-96` 접두 문자열 비교(형제 디렉터리 `storage2` 통과를 재현). `apps/api/routers/viewer.py:203-204`의 임시 파일명은 업로드 시 `_safe_filename`이 구분자를 제거해 완화됨 | **결함 확인(방어 심층), 현재 호출 경로의 악용은 확인하지 못함** | [TK-35](TK-35_storage_path_prefix_check.md) |
| 예외를 통한 정보 노출 (medium) | `access.py:369`, `calculations.py:101,164`, `jobs.py:67,80`, `verification.py:78,127` — 예외 문구를 응답에 실음(7곳). 구성 정보(환경변수 이름)를 싣는 것은 `access.py:369`뿐 | **일부 실제**(구성 정보), 나머지는 고정·입력 오류 문구 | [TK-36](TK-36_exception_text_in_responses.md) |
| prototype 오염 대입 (medium) | `apps/web/static/admin.js:83,93` — `tabs[next]` 검증이 `__proto__`를 통과해 검색 입력이 `Object.prototype`에 대입함(논리 재현) | **결함 확인(낮음~중간)**, 영향은 확인하지 못함 | [TK-37](TK-37_client_key_validation_prototype.md) |
| 비효율 정규식 (high) | Python 863개 점검: **지수 증가 0건**, 이차 이상 33건(`scripts/probe_regex_complexity.py`). JS 후보: `calculation-workbench.js:15`(이차 증가) | 경고가 가리키는 정규식 **미특정**. 다항 증가는 견고성 사항 | [TK-38](TK-38_regex_polynomial_growth.md) |
| URL 부분 문자열 검사 불완전 (high) | `packages/forensic_engine/residual.py:100` — `"schemas.openxmlformats.org" in xml_lower` 등. 보안 경계가 아니라 Office 보일러플레이트 XML 분류. `local_mirror.py:34-43`은 호스트가 아닌 조각 포함 검사이며 로컬 미러 등록용 | **오탐 후보**(보안 검사가 아님). `local_mirror`의 "공식" 판정이 호스트를 확인하지 않는 점은 정확성 사항이며 보안 경계는 아님 | 사용자가 GitHub에서 경고별로 "오탐" 처리 여부를 정한다(아래 결정 사항). 위치를 못 읽어 개별 처리는 하지 않음 |
| 평문 로깅 (high) | `apps/api/identity.py:629` — 관리자 부트스트랩 CLI가 1일 토큰을 **한 번 출력**(운영자가 터미널에서 받는 것이 이 명령의 목적). `scripts/check_hardcoding_diff.py:248-254`는 코드 낱말(`item['token']`)을 출력할 뿐 비밀이 아님 | **의도된 동작/오탐 후보.** 운영 메모: 이 명령은 컨테이너 로그가 수집되는 환경에서 실행하면 토큰이 로그에 남을 수 있다 | 사용자가 경고별 "수정 안 함" 또는 "오탐"과 사유를 정한다. 운영 절차(로그 수집 밖 실행) 문서화는 구현 측 몫 |
| DOM 텍스트의 HTML 재해석 (high) | 앱 JS·`index.html`에서 `innerHTML`·`insertAdjacentHTML`·`document.write`·`DOMParser`·`srcdoc`·`eval`을 **찾지 못함**. 벤더 `lucide.min.js`의 `outerHTML`은 `console.warn` 문자열 안에서만 쓰임(대입 아님) | **원인 미특정.** 이 규칙은 경고 위치가 필요하다 | 경고 파일·줄을 받으면 재분류 |

합계: 위 표로 건수에 맞출 수 있는 것은 워크플로 6건뿐이다(작업 단위가 6개인 근거). 나머지는 후보일 뿐 38건 전부를 설명했다고 주장하지 않는다.

**경고 위치를 받는 방법(사용자 승인 필요):** (B) 읽기 전용 점검 워크플로를 평가 측이 추가한다 — `GITHUB_TOKEN`에 `security-events: read`를 주어 코드 스캔 경고(규칙·파일·줄·심각도)를 아티팩트로 내보내고, 제가 Actions 읽기로 가져온다. Dependabot 경고는 `GITHUB_TOKEN`으로 읽을 수 없어 `pip-audit` 단계를 둔다. 새 워크플로 파일 추가이므로 승인 후에만 만든다. (A') 대안: 사용자가 Security → Code scanning에서 규칙별 건수와 각 경고의 파일·줄을 알려 준다(38건이면 표 한 장 분량).
