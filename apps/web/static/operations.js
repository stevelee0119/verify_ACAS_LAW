"use strict";

const operationsUI = (() => {
  let loginPromise = null, identity = null, authVersion = 0;
  const roles = {ADMIN:"관리자", MEMBER:"검토자", VIEWER:"열람자"};
  async function authRequest(path, options = {}) {
    const response = await fetch(`/api${path}`, {...options, credentials:"same-origin"});
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof result?.detail === "string" ? result.detail : result?.detail?.message ||
      (Array.isArray(result?.detail) ? result.detail.map(item => item.msg).join(" · ") : `인증 요청 실패 (${response.status})`));
    return result;
  }
  function authenticate() {
    if (loginPromise) return loginPromise;
    loginPromise = new Promise((resolve, reject) => {
      const dialog = node("dialog", null, "workflow-dialog login-dialog");
      dialog.setAttribute("aria-label", "작업 공간 로그인");
      const form = node("form"), error = node("p", "", "error");
      error.setAttribute("role", "alert");
      const emailField = workflowUI.field("email", "이메일", "", "email");
      const passwordField = workflowUI.field("password", "비밀번호", "", "password");
      const credential = workflowUI.field("token", "개인 접속 토큰 또는 SSO ID 토큰", "", "password");
      const email = emailField.querySelector("input"), password = passwordField.querySelector("input"), token = credential.querySelector("input");
      email.required = password.required = token.required = true;
      email.autocomplete = "username"; password.autocomplete = "current-password"; token.autocomplete = "off";
      email.maxLength = 200;
      const modes = node("div", null, "login-modes"); modes.setAttribute("role", "tablist"); modes.setAttribute("aria-label", "로그인 방식");
      const passwordPanel = node("div", null, "login-fields"), tokenPanel = node("div", null, "login-fields");
      passwordPanel.append(emailField, passwordField); tokenPanel.append(credential);
      let mode = "password";
      const modeButtons = [];
      function selectMode(next, focus = true) {
        mode = next; error.textContent = ""; password.value = token.value = "";
        passwordPanel.hidden = mode !== "password"; tokenPanel.hidden = mode !== "token";
        email.disabled = password.disabled = mode !== "password"; token.disabled = mode !== "token";
        modeButtons.forEach(tab => {
          const selected = tab.dataset.mode === mode;
          tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1;
        });
        if (focus) (mode === "password" ? email : token).focus();
      }
      for (const [key, title, panel] of [["password", "이메일 로그인", passwordPanel], ["token", "토큰·SSO", tokenPanel]]) {
        const tab = button(title, () => selectMode(key)); tab.dataset.mode = key; tab.id = `login-tab-${key}`;
        tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", `login-panel-${key}`);
        panel.id = `login-panel-${key}`; panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", tab.id);
        tab.addEventListener("keydown", event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? "password" : event.key === "End" ? "token" : mode === "password" ? "token" : "password";
          selectMode(next, false); modeButtons.find(item => item.dataset.mode === next).focus();
        });
        modeButtons.push(tab); modes.append(tab);
      }
      const submit = node("button", "로그인", "primary"); submit.type = "submit";
      const registerBtn = node("button", "신규 사용자 등록 신청", "button link register-btn");
      registerBtn.type = "button";
      registerBtn.onclick = () => registerUserModal();
      const emblem = node("div", null, "brand-emblem"), emblemImage = node("img");
      emblemImage.src = "/static/acas-law-emblem.jpg"; emblemImage.alt = "ACASia LAW";
      emblemImage.width = 1280; emblemImage.height = 640; emblem.append(emblemImage);
      const heading = node("div", null, "login-heading");
      heading.append(emblem, node("h2", "법률문서 검증시스템"));
      form.append(heading, modes, passwordPanel, tokenPanel, error, submit, registerBtn);
      dialog.append(form); document.body.append(dialog);
      let authenticated = false;
      dialog.addEventListener("cancel", event => {if (submit.disabled) event.preventDefault();});
      dialog.addEventListener("close", () => {
        password.value = token.value = ""; dialog.remove();
        if (!authenticated) reject(new Error("로그인이 필요합니다."));
      }, {once:true});
      form.onsubmit = async event => {
        event.preventDefault(); if (submit.disabled) return; submit.disabled = true; error.textContent = "";
        modeButtons.forEach(tab => tab.disabled = true);
        try {
          if (mode === "password") await authRequest("/auth/login", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:email.value.trim(), password:password.value})});
          else await authRequest("/identity/session", {method:"POST", headers:{Authorization:`Bearer ${token.value.trim()}`}});
          const nextIdentity = await authRequest("/identity/me");
          const changedUser = identity && identity.user_id !== nextIdentity.user_id;
          identity = nextIdentity; authenticated = true; dialog.close();
          if (typeof adminUI !== "undefined") adminUI.setIdentity(nextIdentity);
          if (changedUser) { location.reload(); reject(new Error("다른 계정으로 로그인하여 작업 공간을 새로 불러옵니다.")); }
          else {
            authVersion += 1;
            resolve();
            if (typeof resumeAuthenticatedRun === "function") resumeAuthenticatedRun();
            if (typeof projectTools !== "undefined") projectTools.start();
          }
        } catch (e) { error.textContent = e.message; }
        finally { password.value = token.value = ""; submit.disabled = false; modeButtons.forEach(tab => tab.disabled = false); }
      };
      selectMode("password", false); dialog.showModal(); email.focus();
    }).finally(() => {loginPromise = null;});
    return loginPromise;
  }
  async function refreshIdentity() {
    try {identity = await api("/identity/me");}
    catch (error) {
      if (typeof adminUI !== "undefined") adminUI.setIdentity(null);
      throw error;
    }
    if (typeof adminUI !== "undefined") adminUI.setIdentity(identity);
    const multi = identity.authentication !== "local";
    $("accountButton").title = multi ? `내 계정 · ${roles[identity.role] || identity.role}` : "로컬 작업 공간";
    $("accountButton").setAttribute("aria-label", $("accountButton").title);
    return identity;
  }
  async function account() {
    const me = await refreshIdentity();
    const content = node("div", null, "full");
    content.append(node("p", me.authentication === "local" ? "로컬 단일 사용자" : `${me.user_id} · ${roles[me.role] || me.role}`));
    if (me.organization_id) {
      content.append(button("내 접속 토큰", () => {view.dialog.close(); return tokens(me.user_id);}));
      if (me.role === "ADMIN") content.append(button("사용자 관리", () => {view.dialog.close(); adminUI.open();}));
    }
    if (me.authentication !== "local") {
      if (me.authentication === "password") content.append(button("비밀번호 변경", () => {view.dialog.close(); changePassword();}));
      content.append(button("로그아웃", async () => {await authRequest("/identity/session", {method:"DELETE"}); location.reload();}));
    }
    const view = workflowUI.modal("계정·접근 권한", [content], async()=>{}); view.readOnly();
  }
  function changePassword() {
    const current = workflowUI.field("current_password", "현재 비밀번호", "", "password");
    const next = workflowUI.field("new_password", "새 비밀번호 (10자 이상)", "", "password");
    const confirmation = workflowUI.field("confirmation", "새 비밀번호 확인", "", "password");
    current.querySelector("input").autocomplete = "current-password";
    for (const field of [next, confirmation]) {field.querySelector("input").autocomplete = "new-password"; field.querySelector("input").minLength = 10;}
    for (const field of [current, next, confirmation]) field.querySelector("input").required = true;
    const view = workflowUI.modal("비밀번호 변경", [current, next, confirmation], async values => {
      if (values.new_password !== values.confirmation) throw new Error("새 비밀번호가 서로 다릅니다.");
      await authRequest("/auth/password", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({current_password:values.current_password, new_password:values.new_password})});
      location.reload();
    });
    view.submit.textContent = "변경 후 다시 로그인";
    view.dialog.addEventListener("close", () => {for (const field of [current, next, confirmation]) field.querySelector("input").value = "";}, {once:true});
  }
  function registerUserModal() {
    const email = workflowUI.field("email", "이메일", "", "email");
    const password = workflowUI.field("password", "비밀번호 (10자 이상, 문자·숫자·특수문자)", "", "password");
    const passwordConfirm = workflowUI.field("password_confirm", "비밀번호 확인", "", "password");
    const name = workflowUI.field("display_name", "성명");
    const phone = workflowUI.field("phone_number", "연락처", "", "tel");
    const affil = workflowUI.field("affiliation", "소속", "종합행정학교 법무교육단");
    const reason = workflowUI.field("registration_reason", "등록 사유", "법률문서 검증 업무");

    email.querySelector("input").required = true;
    password.querySelector("input").required = true;
    password.querySelector("input").minLength = 10;
    passwordConfirm.querySelector("input").required = true;
    passwordConfirm.querySelector("input").minLength = 10;
    name.querySelector("input").required = true;

    const view = workflowUI.modal("신규 사용자 등록 신청", [email, password, passwordConfirm, name, phone, affil, reason], async values => {
      if (values.password !== values.password_confirm) {
        throw new Error("비밀번호가 서로 일치하지 않습니다.");
      }
      const result = await authRequest("/auth/register", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          email: values.email.trim(),
          password: values.password,
          display_name: values.display_name.trim(),
          phone_number: (values.phone_number || "").trim(),
          affiliation: (values.affiliation || "").trim(),
          registration_reason: (values.registration_reason || "").trim()
        })
      });
      toast(result.message);
    });
    view.submit.textContent = "신청서 제출";
    view.dialog.addEventListener("close", () => {
      password.querySelector("input").value = passwordConfirm.querySelector("input").value = "";
    }, {once:true});
  }

  async function tokens(userId) {
    const content = node("div",null,"full");
    const view = workflowUI.modal("접속 토큰",[content],async()=>{},true); view.readOnly();
    async function draw() {
      const list = await api(`/identity/users/${userId}/tokens`);content.replaceChildren();
      if (identity?.user_id === userId) content.append(button("새 토큰 발급",()=>workflowUI.modal("개인 접속 토큰 발급",[workflowUI.field("label","용도"),workflowUI.field("days","유효기간 (일)",30,"number")],async values=>{
        const token = await api(`/identity/users/${userId}/tokens`,{method:"POST",body:{...values,days:Number(values.days)}});await draw();
        const field=workflowUI.field("secret","발급된 접속 토큰 (이 화면에서만 표시)",token.token,"textarea");field.querySelector("textarea").readOnly=true;
        const shown=workflowUI.modal("접속 토큰",[field],async()=>{});shown.readOnly();
      })));
      content.append(workflowUI.table(["용도","만료","상태","관리"],list.map(token=>[token.label,dateText(token.expires_at),token.revoked_at?"해지":"유효",token.revoked_at?"":button("해지",async()=>{
        if(await ask("접속 토큰 해지","이 토큰과 연결된 접속 권한을 종료합니다.")===null)return;
        await api(`/identity/tokens/${token.id}`,{method:"DELETE"});await draw();
      })])));
    }
    await draw();
  }
  async function selectRun(run) {
    if (run.project_id !== state.project?.id) return;
    clearTimeout(state.timer); const generation=++state.generation;
    state.pollError=null;state.pollFailures=0;
    state.run=run;state.findings=[];state.result={};renderProject();
    renderFindings();renderAIVerification();
    if(terminal(run))await loadResults(generation);
    else pollRun(generation,0);
  }
  async function jobDetails(run) {
    const job=await api(`/verification-runs/${run.id}/job`), content=node("div",null,"full");
    content.append(node("p",`${label(job.state)} · 시도 ${job.attempts}/${job.max_attempts}`));
    if(job.next_dispatch_at && !terminal(job))content.append(node("p",`다음 실행 확인 ${dateText(job.next_dispatch_at)}`,"muted"));
    if(job.last_error)content.append(node("p",job.last_error,"error"));
    if(job.last_error==="EXECUTION_SETTINGS_CHANGED")content.append(node("p",
      "이전 실행 이후 분석 엔진 설정이 변경되었습니다. 같은 입력으로 재시도하면 원래 자료와 사건 조건을 현재 엔진으로 다시 분석합니다.","muted"));
    // 임차가 만료됐을 때 마지막 갱신이 언제였는지가 원인을 가른다.
    // 시작 직후까지만 갱신됐다면 갱신이 끊긴 것이고, 만료 직전까지 갱신됐다면
    // 작업 프로세스가 갑자기 죽은 것이다. 원인도 조치도 서로 다르다.
    if(job.last_error==="WORKER_LEASE_EXPIRED" && job.heartbeat_at){
      const last=job.history?.[job.history.length-1], started=last?.started_at;
      const alive=started?Math.round((new Date(job.heartbeat_at)-new Date(started))/1000):null;
      content.append(node("p",`마지막 임차 갱신 ${dateText(job.heartbeat_at)}`
        +(alive!==null?` (시도 시작 ${alive}초 후)`:""),"muted"));
    }
    content.append(workflowUI.table(["시도","상태","시작","종료","기록"],job.history.map(attempt=>[
      String(attempt.fence),label(attempt.state),dateText(attempt.started_at),dateText(attempt.finished_at),
      `${attempt.error || ""} · 보존 자료 ${(attempt.partial_result?.documents || []).length}개`
    ])));
    const view=workflowUI.modal("검증 작업 기록",[content],async()=>{},true);view.readOnly();
  }
  async function runHistory() {
    const pid=state.project.id, runs=await api(`/projects/${pid}/runs?limit=100`),content=node("div",null,"full");
    if(pid!==state.project?.id)return;
    const view=workflowUI.modal("검증 실행 이력",[content],async()=>{},true);view.readOnly();
    content.append(workflowUI.table(["시작","진행 상태","자료","열기"],runs.map(run=>[
      dateText(run.started_at),label(run.state),`${run.document_ids.length}개`,button("결과 열기",async()=>{view.dialog.close();await selectRun(run);})
    ])));
    if(!runs.length)content.append(node("p","검증 실행 이력이 없습니다."));
  }
  function renderJobControls() {
    const root=$("jobControls"); if(!root)return;
    root.replaceChildren(button("검증 이력",runHistory));
    const run=state.run;if(!run)return;
    root.append(button("작업 기록",()=>jobDetails(run)));
    if(!terminal(run))root.append(button("검증 취소",async()=>{
      if(await ask("검증 취소","진행 중인 검증을 취소합니다. 이미 전송된 외부 요청은 요금이 발생할 수 있습니다.")===null)return;
      const cancelled=await api(`/verification-runs/${run.id}/cancel`,{method:"POST"});await selectRun(cancelled);
    }));
    if(["FAILED","CANCELLED","PARTIAL_COMPLETED"].includes(run.state))root.append(button("같은 입력으로 재시도",async()=>{
      if(await ask("검증 재시도","당시 자료와 사건 조건을 현재 분석 엔진으로 다시 검증합니다. 기존 보안 정책과 누적 비용 한도는 유지하며, 외부 AI 요청이 다시 발생할 수 있습니다.")===null)return;
      const retry=await api(`/verification-runs/${run.id}/retry`,{method:"POST"});await selectRun(retry);
    }));
  }
  function init() {
    const accountButton=iconButton("user-round","내 계정",account);accountButton.id="accountButton";
    $("settingsButton").before(accountButton);
    if (typeof adminUI !== "undefined") adminUI.init();
    const jobs=node("div",null,"toolbar job-controls");jobs.id="jobControls";$("progress").after(jobs);
  }
  return {init,authenticate,refreshIdentity,renderJobControls,selectRun,manageTokens:tokens,authVersion:()=>authVersion};
})();
