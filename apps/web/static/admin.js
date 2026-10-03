"use strict";

const adminUI = (() => {
  const tabs = {users:"사용자", pending:"승인 대기", usage:"이용 통계", mail:"메일 기록"};
  const roles = {ADMIN:"관리자", MEMBER:"검토자", VIEWER:"열람자"};
  const accountStates = {ACTIVE:"사용 중", PENDING:"승인 대기", REJECTED:"반려", DISABLED:"중지"};
  const mailStates = {QUEUED:"발송 대기", SENDING:"전송 중", SMTP_ACCEPTED:"SMTP 서버 접수",
    FAILED:"전송 실패", UNAVAILABLE:"설정 확인 필요", UNKNOWN:"접수 여부 불명", CANCELLED:"발송 취소"};
  let identity = null, root, navigation, panel, toolbar, rows, pager, feedback, summary, detail;
  let active = false, tab = "users", epoch = 0, data = [], usersById = new Map(), smtp = null;
  let ready = false, initialized = false, previousHash = "";
  // 보안(TK-37): prototype 오염 방지를 위해 preferences를 null prototype 객체로 생성
  const preferences = Object.assign(Object.create(null), Object.fromEntries(Object.keys(tabs).map(key => [key, {
    query:"", status:"", role:"", page:1, size:20, period:new Date().toISOString().slice(0, 7),
  }])));
  const statusOf = user => user.approval_status === "APPROVED"
    ? (user.enabled ? "ACTIVE" : "DISABLED") : user.approval_status;
  const number = value => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("ko-KR") : "미집계";
  const stamp = value => value ? dateText(value) : "-";
  const read = path => api(path, {interactiveAuth:false});
  const command = (text, icon, callback, cls = "") => {
    const result = button(text, callback, cls);
    const glyph = node("i"); glyph.dataset.lucide = icon; result.prepend(glyph);
    return result;
  };
  function badge(text, state) {
    const result = node("span", text || "확인 필요", "admin-badge");
    result.dataset.state = state || "UNKNOWN";
    return result;
  }
  function announce(message, error = false) {
    feedback.replaceChildren(node("span", message));
    feedback.className = error ? "admin-feedback error" : "admin-feedback";
    feedback.hidden = !message;
  }
  function closeDetail() { if (detail?.open) detail.close(); }
  function open(next = "users") {
    if (!identity || identity.role !== "ADMIN" || !identity.organization_id) return;
    if (!active) previousHash = location.hash.startsWith("#admin/") ? "" : location.hash;
    // 보안(TK-37): Object.hasOwn 검사로 __proto__ 등 prototype 키 통과 방지
    location.hash = "#admin/" + (Object.hasOwn(tabs, next) ? next : "users");
    route();
  }
  function leave() {
    location.hash = previousHash;
    route();
    navigation.focus();
  }
  function route() {
    const next = location.hash.slice(7);
    const requested = location.hash.startsWith("#admin/");
    const allowed = identity?.role === "ADMIN" && identity.organization_id;
    if (!requested || !allowed) {
      if (active) {epoch++; closeDetail();}
      active = false;
      document.body.classList.remove("admin-active");
      root.hidden = true; navigation.setAttribute("aria-pressed", "false");
      return;
    }
    // 보안(TK-37): Object.hasOwn 검사로 __proto__ 등 prototype 키 통과 방지
    const selected = Object.hasOwn(tabs, next) ? next : "users";
    if (active && tab === selected) return;
    active = true; tab = selected;
    document.body.classList.add("admin-active");
    root.hidden = false; navigation.setAttribute("aria-pressed", "true");
    for (const control of root.querySelectorAll('[role="tab"]')) {
      const current = control.dataset.adminTab === tab;
      control.setAttribute("aria-selected", String(current)); control.tabIndex = current ? 0 : -1;
    }
    panel.setAttribute("aria-labelledby", "admin-tab-" + tab);
    announce(""); buildToolbar(); load();
  }
  function setIdentity(next) {
    if (!initialized) return;
    if (identity?.user_id !== next?.user_id || identity?.role !== next?.role || identity?.organization_id !== next?.organization_id) {
      epoch++; ready = false; data = []; usersById.clear(); closeDetail(); active = false;
      rows.replaceChildren(); summary.replaceChildren(); pager.replaceChildren(); announce("");
    }
    identity = next;
    navigation.hidden = !(next?.role === "ADMIN" && next.organization_id);
    route();
  }
  function filter(name, label, choices) {
    const field = workflowUI.field(name, label, preferences[tab][name], "text", choices);
    field.querySelector("select").onchange = event => {
      preferences[tab][name] = event.target.value; preferences[tab].page = 1; renderRows();
    };
    return field;
  }
  function buildToolbar() {
    const pref = preferences[tab];
    toolbar.replaceChildren();
    const search = workflowUI.field("query", tab === "mail" ? "수신자 검색" : "사용자 검색", pref.query, "search");
    search.className = "admin-search";
    search.querySelector("input").placeholder = "이름, 이메일, 소속";
    search.querySelector("input").oninput = event => {pref.query = event.target.value; pref.page = 1; renderRows();};
    toolbar.append(search);
    if (tab === "users" || tab === "usage") {
      toolbar.append(filter("status", "계정 상태", {"":"전체 상태", ...accountStates}),
        filter("role", "역할", {"":"전체 역할", ...roles}));
    }
    if (tab === "usage") {
      const field = workflowUI.field("period", "집계월 (UTC)", pref.period, "month");
      const input = field.querySelector("input"); input.min = "2000-01"; input.max = "9998-12";
      input.onchange = () => {
        if (!input.value || !input.validity.valid) return;
        pref.period = input.value; pref.page = 1; load();
      };
      const download = command("CSV", "download", () => {
        const [year, month] = pref.period.split("-");
        // 보안(TK-37): CSV export 주소의 year를 Number(year)로 변환
        location.href = "/api/admin/users/export.csv?year=" + Number(year) + "&month=" + Number(month);
      });
      download.title = "선택 월 전체 사용자 CSV 다운로드";
      toolbar.append(field, download);
    }
    if (tab === "mail") toolbar.append(filter("status", "전송 상태", {"":"전체 상태", ...mailStates}));
    if (tab === "users") toolbar.append(command("사용자 등록", "user-plus", createUser, "primary"));
    toolbar.append(iconButton("refresh-cw", "관리 목록 새로고침", () => load()));
    icons();
  }
  async function directory() {
    const [profiles, accounts] = await Promise.all([read("/auth/users"), read("/identity/users")]);
    if (!Array.isArray(profiles) || !Array.isArray(accounts)) throw new Error("사용자 응답 형식을 확인할 수 없습니다.");
    const byId = new Map(accounts.map(user => [user.id, user]));
    return profiles.map(user => {
      if (!byId.has(user.id)) throw new Error("사용자 상태가 변경되었습니다. 다시 조회해 주세요.");
      return {...user, enabled:byId.get(user.id).enabled};
    });
  }
  async function load() {
    const version = ++epoch, selected = tab, period = preferences[tab].period;
    ready = false; closeDetail(); data = []; rows.replaceChildren(); rows.removeAttribute("role");
    summary.replaceChildren(); pager.replaceChildren(); panel.setAttribute("aria-busy", "true");
    const loading = node("p", "불러오는 중입니다.", "admin-empty");
    loading.setAttribute("role", "status"); rows.append(loading);
    try {
      let result, directoryUsers = [];
      if (selected === "users") result = directoryUsers = await directory();
      if (selected === "pending") {
        const response = await read("/admin/pending-registrations");
        if (!Array.isArray(response.users)) throw new Error("가입 신청 응답 형식이 올바르지 않습니다.");
        result = response.users.map(user => ({...user, approval_status:"PENDING", role:"MEMBER", enabled:false}));
      }
      if (selected === "usage") {
        const [year, month] = period.split("-");
        const [metrics, accounts] = await Promise.all([
          read("/admin/users?year=" + year + "&month=" + Number(month)), read("/identity/users"),
        ]);
        if (!Array.isArray(metrics) || !Array.isArray(accounts)) throw new Error("통계 응답 형식이 올바르지 않습니다.");
        const byId = new Map(accounts.map(user => [user.id, user]));
        result = directoryUsers = metrics.map(user => {
          if (!byId.has(user.id) || !user.monthly_metrics) throw new Error("통계가 누락되었습니다. 다시 조회해 주세요.");
          return {...user, enabled:byId.get(user.id).enabled};
        });
      }
      let configuration = null;
      if (selected === "mail") {
        const [response, profiles] = await Promise.all([read("/admin/notifications"), read("/auth/users")]);
        if (!Array.isArray(response.items) || !Array.isArray(profiles) || !response.smtp) throw new Error("메일 응답 형식이 올바르지 않습니다.");
        result = response.items; directoryUsers = profiles; configuration = response.smtp;
      }
      // Ignore responses for a tab, period, or identity that is no longer current.
      if (version !== epoch || !active) return;
      data = result; smtp = configuration;
      usersById = new Map(directoryUsers.map(user => [user.id, user]));
      ready = true; renderRows();
    } catch (error) {
      if (version !== epoch || !active) return;
      rows.replaceChildren(node("p", error.message, "error"),
        command("다시 불러오기", "refresh-cw", () => load()));
      rows.setAttribute("role", "alert");
    } finally {
      if (version === epoch) {panel.setAttribute("aria-busy", "false"); icons();}
    }
  }
  function matching() {
    const pref = preferences[tab], query = pref.query.trim().toLocaleLowerCase();
    return data.filter(item => {
      const user = tab === "mail" ? usersById.get(item.user_id) || {id:item.user_id} : item;
      return (!query || [user.display_name, user.email, user.affiliation, user.id].filter(Boolean).join(" ").toLocaleLowerCase().includes(query))
        && (!pref.status || (tab === "mail" ? item.status : statusOf(item)) === pref.status)
        && (!pref.role || user.role === pref.role);
    });
  }
  function userCell(user) {
    const cell = node("div", null, "admin-user");
    const title = button(user.display_name || user.email || user.id, () => showUser(user), "admin-name");
    title.setAttribute("aria-label", "사용자 상세: " + (user.display_name || user.email || user.id));
    cell.append(title, node("small", user.email || user.id), node("small", user.affiliation || "소속 미입력", "admin-secondary"));
    return cell;
  }
  function renderRows() {
    if (!ready) return;
    rows.removeAttribute("role");
    const pref = preferences[tab], found = matching();
    const pages = Math.max(1, Math.ceil(found.length / pref.size));
    pref.page = Math.min(pref.page, pages);
    summary.replaceChildren();
    const total = node("p", "전체 " + data.length + "명 · 검색 " + found.length + "명", "muted");
    if (tab === "mail") {
      total.textContent = "최근 100건 범위 · 조회 " + data.length + "건 · 검색 " + found.length + "건";
      summary.append(badge(smtp.configured ? "SMTP 설정 있음" : "SMTP 설정 확인 필요", smtp.configured ? "ACTIVE" : "FAILED"),
        node("span", smtp.configured ? smtp.security + " · 포트 " + smtp.port : smtp.error_code, "muted"));
    }
    summary.append(total);
    rows.replaceChildren();
    if (!found.length) {
      rows.append(node("p", data.length ? "검색 결과가 없습니다." : tab === "pending" ? "승인 대기 중인 신청이 없습니다."
        : tab === "mail" ? "발송 기록이 없습니다." : "등록된 사용자가 없습니다.", "admin-empty"));
      if (pref.query || pref.status || pref.role) rows.append(command("필터 초기화", "filter-x", () => {
        pref.query = pref.status = pref.role = ""; pref.page = 1; buildToolbar(); renderRows();
      }));
    } else {
      const table = node("table", null, "admin-table"), head = node("thead"), tr = node("tr"), body = node("tbody");
      const headers = tab === "usage" ? ["사용자", "로그인", "분석", "원본·휴지통 / 한도 (MiB)", "처리 경과시간 (분)", "상세"]
        : tab === "mail" ? ["수신자", "전송 상태", "종류", "시도", "최근 처리", "상세"]
        : tab === "pending" ? ["신청자", "상태", "신청일", "상세"] : ["사용자", "상태", "역할", "연락처", "상세"];
      const secondary = tab === "usage" ? [2, 3, 4] : tab === "mail" ? [2, 3, 4] : tab === "pending" ? [2] : [2, 3];
      headers.forEach((title, index) => {const th = node("th", title); th.scope = "col"; if (secondary.includes(index)) th.className = "admin-secondary"; tr.append(th);});
      head.append(tr);
      for (const item of found.slice((pref.page - 1) * pref.size, pref.page * pref.size)) {
        const row = node("tr"), user = tab === "mail" ? usersById.get(item.user_id) || {id:item.user_id} : item;
        const name = tab === "mail" ? node("div", user.display_name || user.email || user.id, "admin-user") : userCell(user);
        if (tab === "mail") name.append(node("small", user.email || ""));
        const more = iconButton("chevron-right", (tab === "mail" ? "메일 상세: " : "상세 보기: ") + (user.display_name || user.email || user.id),
          () => tab === "mail" ? showMail(item) : showUser(user));
        const metric = user.monthly_metrics || {};
        const cells = tab === "usage" ? [name, number(metric.login_count), number(metric.verification_count),
          number(metric.storage_used_mb) + " / " + (metric.storage_unlimited === true ? "제한 없음" : number(metric.storage_quota_mb)), number(metric.compute_minutes), more]
          : tab === "mail" ? [name, badge(mailStates[item.status], item.status), item.kind === "APPROVAL" ? "가입 승인" : "용량 경고",
            item.attempts + "/3", stamp(item.finished_at || item.attempted_at || item.created_at), more]
          : tab === "pending" ? [name, badge(accountStates.PENDING, "PENDING"), stamp(item.created_at), more]
          : [name, badge(accountStates[statusOf(user)], statusOf(user)), roles[user.role], user.phone_number || "-", more];
        cells.forEach((cell, index) => {
          const td = node("td"); if (secondary.includes(index)) td.className = "admin-secondary";
          td.append(cell instanceof Node ? cell : node("span", cell)); row.append(td);
        });
        body.append(row);
      }
      table.append(head, body); rows.append(table);
    }
    pager.replaceChildren();
    const size = workflowUI.field("size", "페이지당", pref.size, "text", {20:"20개", 50:"50개", 100:"100개"});
    size.querySelector("select").onchange = event => {pref.size = Number(event.target.value); pref.page = 1; renderRows(); pager.querySelector("select").focus();};
    const move = delta => {pref.page += delta; renderRows(); pager.querySelector('[role="status"]').focus();};
    const prev = iconButton("chevron-left", "이전 페이지", () => move(-1));
    const next = iconButton("chevron-right", "다음 페이지", () => move(1));
    prev.disabled = pref.page <= 1; next.disabled = pref.page >= pages;
    const position = node("span", pref.page + " / " + pages + " 페이지"); position.setAttribute("role", "status"); position.tabIndex = -1;
    pager.append(size, prev, position, next); icons();
  }
  function drawer(title) {
    closeDetail();
    const trigger = document.activeElement, dialog = node("dialog", null, "admin-detail");
    detail = dialog; dialog.setAttribute("aria-label", title);
    const header = node("div", null, "dialog-heading");
    header.append(node("h2", title), iconButton("x", "상세 패널 닫기", () => dialog.close()));
    const content = node("div", null, "admin-detail-body"), footer = node("div", null, "admin-detail-footer");
    footer.append(button("닫기", () => dialog.close()));
    dialog.append(header, content, footer);
    dialog.addEventListener("close", () => {
      dialog.remove(); if (detail === dialog) detail = null;
      if (trigger?.isConnected) trigger.focus();
      else if (active) $("admin-tab-" + tab).focus();
    }, {once:true});
    document.body.append(dialog); dialog.showModal();
    return {dialog, content, footer};
  }
  function facts(root, entries) {
    const list = node("dl", null, "admin-facts");
    for (const [label, value] of entries) list.append(node("dt", label), node("dd", value || "-"));
    root.append(list);
  }
  function form(view, fields, label, save) {
    const element = node("form", null, "admin-form"), error = node("p", "", "error");
    error.setAttribute("role", "alert");
    const submit = node("button", label, "primary"); submit.type = "submit";
    element.append(...fields, error, submit); view.content.append(element);
    let busy = false;
    view.dialog.addEventListener("cancel", event => {if (busy) event.preventDefault();});
    element.onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      busy = true; error.textContent = ""; submit.disabled = true;
      const version = epoch;
      const closes = view.dialog.querySelectorAll('button[type="button"]'); closes.forEach(control => control.disabled = true);
      try {
        const message = await save(Object.fromEntries(new FormData(element)), element);
        if (version !== epoch || !active) return;
        view.dialog.close(); announce(message); await load();
      } catch (failure) {error.textContent = failure.message;}
      finally {busy = false; submit.disabled = false; closes.forEach(control => control.disabled = false);}
    };
    icons();
  }
  function createUser() {
    const view = drawer("사용자 등록");
    const email = workflowUI.field("email", "이메일", "", "email");
    const name = workflowUI.field("display_name", "이름");
    const password = workflowUI.field("password", "초기 비밀번호 (선택, 10자 이상)", "", "password");
    email.querySelector("input").required = name.querySelector("input").required = true;
    password.querySelector("input").minLength = 10; password.querySelector("input").autocomplete = "new-password";
    view.dialog.addEventListener("close", () => {password.querySelector("input").value = "";}, {once:true});
    form(view, [name, email, workflowUI.field("role", "역할", "MEMBER", "text", roles), password], "등록", async values => {
      const {password:secret, ...user} = values;
      await api(secret ? "/auth/users" : "/identity/users", {method:"POST", interactiveAuth:false, body:secret ? {...user, password:secret} : user});
      password.querySelector("input").value = "";
      return "사용자 등록 완료";
    });
  }
  function showUser(user) {
    const view = drawer(user.display_name || user.email || user.id);
    view.content.append(badge(accountStates[statusOf(user)], statusOf(user)));
    facts(view.content, [["이메일", user.email], ["소속", user.affiliation], ["연락처", user.phone_number],
      ["역할", roles[user.role]], ["등록 사유", user.registration_reason], ["승인일", stamp(user.approved_at)]]);
    if (user.monthly_metrics) {
      const m = user.monthly_metrics;
      facts(view.content, [["집계월 (UTC)", preferences.usage.period], ["로그인 성공", number(m.login_count) + "회"],
        ["검증 분석", number(m.verification_count) + "건"], ["현재 원본 (휴지통 포함)", number(m.storage_used_mb) + " MiB"],
        ["저장 한도", m.storage_unlimited === true ? "제한 없음" : number(m.storage_quota_mb) + " MiB"], ["월별 업로드", number(m.monthly_upload_mb) + " MiB"],
        ["처리 경과시간 (대기 포함)", number(m.compute_minutes) + "분"]]);
      view.footer.append(command("월별 추이", "history", () => history(user)));
    }
    if (user.approval_status === "PENDING") {
      view.footer.append(command("승인", "check", () => approve(user), "primary"),
        command("반려", "x", () => reject(user)));
    } else if (user.approval_status === "APPROVED" && user.id !== identity.user_id) {
      view.footer.append(
        command("권한 수정", "pencil", () => editUser(user)),
        command("비밀번호 초기화", "lock-keyhole", () => resetUserPassword(user))
      );
    }
    if (user.approval_status === "APPROVED") view.footer.append(command("접속 토큰", "key-round", () => {
      view.dialog.close(); return operationsUI.manageTokens(user.id);
    }));
    icons();
  }
  function approve(user) {
    const view = drawer("가입 승인");
    facts(view.content, [["신청자", user.display_name], ["이메일", user.email], ["처리", "계정 승인 · 승인 안내 메일 발송"]]);
    form(view, [], "승인 확정", async () => {
      const result = await api("/admin/users/" + user.id + "/approve", {method:"POST", interactiveAuth:false});
      return (user.display_name || user.email) + " 승인 완료 · 메일: " + (mailStates[result.notification?.status] || "상태 확인 필요");
    });
  }
  function reject(user) {
    const view = drawer("가입 신청 반려");
    facts(view.content, [["신청자", user.display_name], ["안내 경로", "본인 로그인 화면 · 메일 발송 없음"]]);
    const reason = workflowUI.field("reason", "반려 사유", "", "textarea");
    reason.querySelector("textarea").required = true; reason.querySelector("textarea").maxLength = 1000;
    form(view, [reason], "반려 확정", async values => {
      if (!values.reason.trim()) throw new Error("반려 사유를 입력하세요.");
      await api("/admin/users/" + user.id + "/reject", {method:"POST", interactiveAuth:false, body:{reason:values.reason.trim()}});
      return (user.display_name || user.email) + " 반려 완료 · 로그인 화면 안내";
    });
  }
  function editUser(user) {
    const view = drawer("사용자 권한");
    facts(view.content, [["사용자", user.display_name], ["이메일", user.email]]);
    form(view, [workflowUI.field("role", "역할", user.role, "text", roles),
      workflowUI.field("enabled", "계정 활성", user.enabled, "checkbox")], "저장", async (values, element) => {
      await api("/identity/users/" + user.id, {method:"PATCH", interactiveAuth:false,
        body:{role:values.role, enabled:element.elements.enabled.checked}});
      return "계정 권한 변경 완료";
    });
  }
  function resetUserPassword(user) {
    // 관리자에 의한 사용자 비밀번호 초기화
    const view = drawer("비밀번호 초기화");
    facts(view.content, [["대상 사용자", user.display_name || user.email], ["이메일", user.email]]);
    const password = workflowUI.field("new_password", "새 비밀번호 (10자 이상, 문자·숫자·특수문자)", "", "password");
    const confirm = workflowUI.field("new_password_confirm", "새 비밀번호 확인", "", "password");
    password.querySelector("input").required = confirm.querySelector("input").required = true;
    password.querySelector("input").minLength = confirm.querySelector("input").minLength = 10;
    view.dialog.addEventListener("close", () => {
      password.querySelector("input").value = confirm.querySelector("input").value = "";
    }, {once:true});
    form(view, [password, confirm], "비밀번호 초기화 실행", async values => {
      if (values.new_password !== values.new_password_confirm) throw new Error("새 비밀번호가 서로 일치하지 않습니다.");
      const result = await api("/admin/users/" + user.id + "/reset-password", {
        method: "POST",
        interactiveAuth: false,
        body: {new_password: values.new_password}
      });
      password.querySelector("input").value = confirm.querySelector("input").value = "";
      return result.message || "비밀번호가 초기화되었습니다.";
    });
  }
  async function history(user) {
    const view = drawer("월별 이용 추이");
    view.content.append(node("p", "불러오는 중입니다.", "muted"));
    try {
      const result = await read("/admin/users/" + user.id + "/monthly-stats?months=12");
      if (!view.dialog.open) return;
      if (!Array.isArray(result)) throw new Error("통계 응답 형식이 올바르지 않습니다.");
      view.content.replaceChildren(node("h3", user.display_name || user.email));
      for (const month of result) {
        const section = node("section", null, "admin-month");
        section.append(node("h3", month.year + "-" + String(month.month).padStart(2, "0") + " (UTC)"));
        facts(section, [["로그인 / 분석", number(month.login_count) + "회 / " + number(month.verification_count) + "건"],
          ["업로드", number(month.monthly_upload_mb) + " MiB"], ["처리 경과시간", number(month.compute_minutes) + "분"]]);
        view.content.append(section);
      }
    } catch (error) {
      if (view.dialog.open) view.content.replaceChildren(node("p", error.message, "error"),
        command("다시 불러오기", "refresh-cw", () => history(user)));
    }
  }
  function showMail(item) {
    const view = drawer("메일 상세"), user = usersById.get(item.user_id);
    view.content.append(badge(mailStates[item.status], item.status));
    facts(view.content, [["수신자", user?.email || item.user_id], ["종류", item.kind === "APPROVAL" ? "가입 승인" : "용량 경고"],
      ["전송 시도", item.attempts + " / 3"], ["등록", stamp(item.created_at)], ["최근 시도", stamp(item.attempted_at)],
      ["처리 완료", stamp(item.finished_at)], ["오류 코드", item.error_code],
      ["수신함 도착", "확인되지 않음"]]);
    if (["FAILED", "UNAVAILABLE"].includes(item.status) && item.attempts < 3) {
      form(view, [], "메일 발송 재시도", async () => {
        const result = await api("/admin/notifications/" + item.id + "/retry", {method:"POST", interactiveAuth:false});
        return "메일 재시도 요청 · " + (mailStates[result.status] || "상태 확인 필요");
      });
    }
    icons();
  }
  function init() {
    if (initialized) return;
    initialized = true;
    navigation = command("사용자 관리", "users-round", () => open());
    navigation.id = "adminNavigation"; navigation.hidden = true; navigation.setAttribute("aria-pressed", "false");
    navigation.title = "사용자 관리"; navigation.setAttribute("aria-label", "사용자 관리");
    $("accountButton").before(navigation);
    root = node("section"); root.id = "adminView"; root.hidden = true;
    root.setAttribute("aria-label", "사용자 관리");
    const heading = node("div", null, "admin-heading");
    heading.append(command("작업 공간", "arrow-left", leave), node("h1", "사용자 관리"));
    const nav = node("nav", null, "admin-tabs"); nav.setAttribute("role", "tablist"); nav.setAttribute("aria-label", "사용자 관리 메뉴");
    Object.entries(tabs).forEach(([key, title], index) => {
      const control = button(title, () => open(key));
      control.id = "admin-tab-" + key; control.dataset.adminTab = key;
      control.setAttribute("role", "tab"); control.setAttribute("aria-controls", "adminPanel");
      control.setAttribute("aria-selected", "false"); control.tabIndex = -1;
      control.onkeydown = event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const keys = Object.keys(tabs), target = event.key === "Home" ? 0 : event.key === "End" ? 3
          : (index + (event.key === "ArrowRight" ? 1 : 3)) % 4;
        open(keys[target]); $("admin-tab-" + keys[target]).focus();
      };
      nav.append(control);
    });
    feedback = node("div", null, "admin-feedback"); feedback.hidden = true; feedback.setAttribute("role", "status");
    panel = node("section"); panel.id = "adminPanel"; panel.setAttribute("role", "tabpanel");
    toolbar = node("div", null, "admin-toolbar"); summary = node("div", null, "admin-summary");
    rows = node("div", null, "admin-rows"); pager = node("nav", null, "admin-pagination"); pager.setAttribute("aria-label", "목록 페이지");
    panel.append(toolbar, summary, rows, pager); root.append(heading, nav, feedback, panel);
    document.querySelector("main").prepend(root);
    window.addEventListener("hashchange", route);
  }
  return {init, setIdentity, open};
})();
