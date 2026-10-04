# TK-37 관리자 화면 탭 이름 검증이 prototype 키를 통과시킴
- 유형: 보안(클라이언트 prototype 오염, 낮음~중간) · 기준 커밋: a5e89ae(경고 위치는 `main` `9933548` 기준, `admin.js`는 동일) · 작성: evaluator 2026-10-03 · **6차 라운드 범위 밖**(6차 직후 소규모 보안 보강 후보 — 사용자 결정으로 확정, README)
- 근거 경고: CodeQL `js/prototype-polluting-assignment`(medium) **13건**, 전부 `apps/web/static/admin.js` — 줄 83(2건)·93(2)·104(2)·194(1)·208(4)·241(2). 그리고 `js/xss-through-dom`(high) 1건 `admin.js:108`.

## 원인 하나가 13건을 만든다
- `apps/web/static/admin.js:48-60`: `const next = location.hash.slice(7); const selected = tabs[next] ? next : "users"; … tab = selected;`
  `tabs`(`admin.js:4`)는 객체 리터럴이어서 `tabs["__proto__"]`·`tabs["constructor"]`·`tabs["toString"]`이 truthy다. 그래서 **`#admin/__proto__` 같은 해시가 검증을 통과**하고 `tab === "__proto__"`가 된다. 그러면 `preferences[tab]`(`admin.js:81,83,88,128,174,192`)은 `Object.prototype`을 가리킨다.
- 경고된 13곳은 모두 `pref.* = …` 대입이다(`pref = preferences[tab]`): 검색 입력 `oninput`(93), `filter()`의 `onchange`(83), 집계월 변경(104), 페이지 보정(194), 필터 초기화(208), 페이지 이동(241). **원인(해시 검증)을 고치면 13건이 함께 해소된다**고 본다(경고 재스캔으로 확인 필요).
- 쓰기 도달: `buildToolbar()`(`admin.js:87-93`)는 **모든 탭에서** 검색 입력을 만들고, 그 `oninput`이 `pref.query = event.target.value; pref.page = 1;`을 실행한다.
- 논리 재현(`node`, `tabs`·`preferences` 초기화와 대입문만 옮긴 것이며 **실제 화면 실행은 아니다**): `#admin/__proto__`·`#admin/constructor`·`#admin/toString`은 `selected`가 그대로 나오고(`users`로 돌아오지 않음), `preferences["__proto__"] === Object.prototype`이 참이며, 같은 대입 뒤 `({}).query === "x"`, `({}).page === 1`이 된다.
- 전제와 한계: 로그인한 **ADMIN**이 조작된 링크(`…#admin/__proto__`)를 열고 **검색 상자에 입력**해야 발생한다. 오염되는 속성은 `query`·`page`(필터 상태 이름)이며, 이것이 다른 코드의 동작을 바꾸는지는 확인하지 못했다. 이후 `renderRows()`는 `pref.query.trim()`(`admin.js:174`)에서 멈출 수 있으나 오염 대입은 그 앞에서 이미 일어난다.

## `admin.js:108` DOM 경고(오탐 성격, 경미)
`location.href = "/api/admin/users/export.csv?year=" + year + "&month=" + Number(month);` — `year`는 `<input type="month">` 값(`pref.period.split("-")`)이다. 고정 접두어(`/api/…`)라 URL 스킴을 바꿀 수 없어 **XSS 경로는 아니다.** `month`는 `Number()`로 감싸지만 `year`는 아니므로 `Number(year)`로 맞추는 것이 일관적이다.

## 수용 기준(착수 시)
- `tabs[next]` 대신 **자기 속성 검사**(`Object.hasOwn(tabs, next)` 또는 `Map`)를 쓴다. `preferences`도 `Object.create(null)` 또는 `Map`으로 만든다. 해시에서 온 값으로 객체를 조회하는 곳이 더 있는지 점검한다(이 점검에서는 `admin.js`의 `location.hash` 사용만 찾았다).
- `year`를 `Number(year)`로 감싼다.
- 시험: `#admin/__proto__`·`#admin/constructor`·`#admin/toString`이 `users` 탭으로 돌아가고 `Object.prototype`이 오염되지 않는지. 평가 측 브라우저 시험 환경(Chromium·Playwright는 세션에 설치되어 있으나 앱 기동·관리자 계정 구성이 필요)은 착수 시 평가 측이 정한다.
