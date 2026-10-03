# TK-37 관리자 화면 탭 이름 검증이 prototype 키를 통과시킴
- 유형: 보안(클라이언트 prototype 오염, 낮음~중간) · 기준 커밋: 028ca14 · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정 대기)
- 근거 경고: CodeQL "Prototype-polluting assignment"(medium). 경고 위치는 읽지 못했다. 아래는 코드에서 찾은 가장 유력한 지점이며 **경고와 같은 곳인지는 확정하지 못했다.**

## 증상·증거
- `apps/web/static/admin.js:48-60`: `const next = location.hash.slice(7); const selected = tabs[next] ? next : "users"; … tab = selected;`
  `tabs`(`admin.js:4`)는 객체 리터럴이어서 `tabs["__proto__"]`·`tabs["constructor"]`·`tabs["toString"]`이 truthy다. 그래서 **`#admin/__proto__` 같은 해시가 검증을 통과**하고 `tab === "__proto__"`가 된다. 그러면 `preferences[tab]`(`admin.js:12`, `87`)은 `Object.prototype`을 가리킨다.
- 쓰기 도달: `buildToolbar()`(`admin.js:87-93`)는 **모든 탭에서** 검색 입력을 만들고, 그 `oninput`이 `pref.query = event.target.value; pref.page = 1;`을 실행한다(`pref = preferences[tab]`). `admin.js:83`의 `filter()`도 같은 형태다.
- 논리 재현(`node`, 위 `tabs`·`preferences` 초기화와 대입문만 옮긴 것이며 **실제 화면 실행은 아니다**): `#admin/__proto__`·`#admin/constructor`·`#admin/toString`은 `selected`가 그대로 나오고(`users`로 돌아오지 않음), `preferences["__proto__"] === Object.prototype`이 참이며, 같은 대입 뒤 `({}).query === "x"`, `({}).page === 1`이 된다.
- 전제와 한계: 로그인한 **ADMIN**이 조작된 링크(`…#admin/__proto__`)를 열고 **검색 상자에 입력**해야 발생한다. 오염되는 속성은 `query`·`page`(필터 상태 이름)이며, 이것이 다른 코드의 동작을 바꾸는지는 확인하지 못했다. 이후 `renderRows()`는 `pref.query.trim()`(`admin.js:174`)에서 멈출 수 있으나 오염 대입은 그 앞에서 이미 일어난다.
- 다른 동적 키 대입(`calculation-workbench.js:91` `target[name] = input`, `workflow.js:15` `lastTabs[selectedGroup] = tab`, `report-workbench.js:122`)은 키가 코드 상수이거나 `Object.keys(...)` 결과라 외부 입력 경로를 확인하지 못했다.

## 수용 기준(착수 시)
- `tabs[next]` 대신 **자기 속성 검사**(`Object.hasOwn(tabs, next)` 또는 `Map`)를 쓴다. `preferences`도 `Object.create(null)` 또는 `Map`으로 만든다. 해시에서 온 값으로 객체를 조회하는 곳이 더 있는지 점검한다(이 점검에서는 `admin.js`의 `location.hash` 사용만 찾았다).
- 시험: `#admin/__proto__`·`#admin/constructor`·`#admin/toString`이 `users` 탭으로 돌아가고 `Object.prototype`이 오염되지 않는지. 평가 측 브라우저 시험 환경(Chromium·Playwright는 세션에 설치되어 있으나 앱 기동·관리자 계정 구성이 필요)은 착수 시 평가 측이 정한다.
