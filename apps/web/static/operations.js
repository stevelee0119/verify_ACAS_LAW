"use strict";

const operationsUI = (() => {
  let loginPromise = null, identity = null;
  const roles = {ADMIN:"관리자", MEMBER:"검토자", VIEWER:"열람자"};
  function authenticate() {
    if (loginPromise) return loginPromise;
    loginPromise = new Promise((resolve, reject) => {
      const dialog = node("dialog", null, "workflow-dialog");
      dialog.setAttribute("aria-label", "작업 공간 로그인");
      const form = node("form"), error = node("p", "", "error");
      error.setAttribute("role", "alert");
      const credential = workflowUI.field("token", "개인 접속 토큰 또는 SSO ID 토큰", "", "password");
      const input = credential.querySelector("input"); input.required = true; input.autocomplete = "off";
      const submit = node("button", "로그인", "primary"); submit.type = "submit";
      form.append(node("h2", "작업 공간 로그인"), credential, error, submit);
      dialog.append(form); document.body.append(dialog);
      let authenticated = false;
      dialog.addEventListener("close", () => {dialog.remove(); if (!authenticated) reject(new Error("로그인이 필요합니다."));}, {once:true});
      form.onsubmit = async event => {
        event.preventDefault(); submit.disabled = true; error.textContent = "";
        try {
          const response = await fetch("/api/identity/session", {method:"POST", credentials:"same-origin", headers:{Authorization:`Bearer ${input.value.trim()}`}});
          const result = await response.json().catch(()=>({}));
          if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "접속 정보를 확인하세요.");
          input.value = ""; identity = result; authenticated = true; dialog.close(); resolve();
        } catch (e) { error.textContent = e.message; }
        finally { submit.disabled = false; }
      };
      dialog.showModal(); input.focus();
    }).finally(() => {loginPromise = null;});
    return loginPromise;
  }
  async function refreshIdentity() {
    identity = await api("/identity/me");
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
      content.append(button("내 접속 토큰", () => tokens(me.user_id)));
      if (me.role === "ADMIN") content.append(button("조직 사용자", users));
      if (state.project) content.append(button("이 프로젝트 접근 권한", members));
      content.append(button("로그아웃", async () => {await api("/identity/session", {method:"DELETE"}); location.reload();}));
    }
    const view = workflowUI.modal("계정·접근 권한", [content], async()=>{}); view.submit.hidden = true;
  }
  async function users() {
    const content = node("div", null, "full");
    const view = workflowUI.modal("조직 사용자", [content], async()=>{}, true); view.submit.hidden = true;
    async function draw() {
      const list = await api("/identity/users"); content.replaceChildren();
      content.append(button("사용자 등록", () => workflowUI.modal("사용자 등록", [workflowUI.field("email","이메일","","email"), workflowUI.field("display_name","이름"), workflowUI.field("role","역할","MEMBER","text",roles)], async values=>{
        await api("/identity/users",{method:"POST",body:values}); await draw();
      })));
      content.append(workflowUI.table(["사용자","역할","상태","관리"],list.map(user=>{
        const actions = node("div",null,"actions");
        actions.append(button("수정",()=>workflowUI.modal("사용자 권한", [workflowUI.field("role","역할",user.role,"text",roles),workflowUI.field("enabled","계정 활성",user.enabled,"checkbox")], async (values,form)=>{
          await api(`/identity/users/${user.id}`,{method:"PATCH",body:{role:values.role,enabled:form.elements.enabled.checked}});await draw();
        })),button("접속 토큰",()=>tokens(user.id)),button("SSO 연결",()=>workflowUI.modal("SSO 사용자 연결",[workflowUI.field("subject","인증 제공자의 사용자 식별자 (sub)")],async values=>{
          await api(`/identity/users/${user.id}/oidc`,{method:"POST",body:values});toast("SSO 사용자를 연결했습니다.");
        })));
        return [user.display_name || user.email, roles[user.role],user.enabled?"사용 중":"중지",actions];
      })));
    }
    await draw();
  }
  async function tokens(userId) {
    const content = node("div",null,"full");
    const view = workflowUI.modal("접속 토큰",[content],async()=>{},true); view.submit.hidden = true;
    async function draw() {
      const list = await api(`/identity/users/${userId}/tokens`);content.replaceChildren();
      content.append(button("새 토큰 발급",()=>workflowUI.modal("개인 접속 토큰 발급",[workflowUI.field("label","용도"),workflowUI.field("days","유효기간 (일)",30,"number")],async values=>{
        const token = await api(`/identity/users/${userId}/tokens`,{method:"POST",body:{...values,days:Number(values.days)}});await draw();
        const field=workflowUI.field("secret","발급된 접속 토큰 (이 화면에서만 표시)",token.token,"textarea");field.querySelector("textarea").readOnly=true;
        const shown=workflowUI.modal("접속 토큰",[field],async()=>{});shown.submit.hidden=true;
      })));
      content.append(workflowUI.table(["용도","만료","상태","관리"],list.map(token=>[token.label,dateText(token.expires_at),token.revoked_at?"해지":"유효",token.revoked_at?"":button("해지",async()=>{
        if(await ask("접속 토큰 해지","이 토큰과 연결된 접속 권한을 종료합니다.")===null)return;
        await api(`/identity/tokens/${token.id}`,{method:"DELETE"});await draw();
      })])));
    }
    await draw();
  }
  async function members() {
    const pid=state.project.id, content=node("div",null,"full");
    const list=await api(`/projects/${pid}/members`);
    const view=workflowUI.modal("프로젝트 접근 권한",[content],async()=>{},true);view.submit.hidden=true;
    content.append(button("권한 부여",()=>workflowUI.modal("프로젝트 검토자",[workflowUI.field("user_id","사용자 ID"),workflowUI.field("role","프로젝트 역할","MEMBER","text",roles)],async values=>{
      await api(`/projects/${pid}/members/${encodeURIComponent(values.user_id)}`,{method:"PUT",body:{role:values.role}});view.dialog.close();await members();
    })));
    content.append(workflowUI.table(["사용자","역할","관리"],list.map(member=>[member.user_id,roles[member.role],button("제외",async()=>{
      if(await ask("프로젝트 접근 권한 제외",member.user_id)===null)return;
      await api(`/projects/${pid}/members/${member.user_id}`,{method:"DELETE"});view.dialog.close();await members();
    })])));
  }
  async function selectRun(run) {
    if (run.project_id !== state.project?.id) return;
    clearTimeout(state.timer); const generation=++state.generation;
    state.run=run;state.findings=[];state.result={};renderProject();
    await loadResults(generation);
    if(!terminal(run))pollRun(generation);
  }
  async function jobDetails(run) {
    const job=await api(`/verification-runs/${run.id}/job`), content=node("div",null,"full");
    content.append(node("p",`${label(job.state)} · 시도 ${job.attempts}/${job.max_attempts}`));
    if(job.last_error)content.append(node("p",job.last_error,"error"));
    content.append(workflowUI.table(["시도","상태","시작","종료","기록"],job.history.map(attempt=>[
      String(attempt.fence),label(attempt.state),dateText(attempt.started_at),dateText(attempt.finished_at),
      `${attempt.error || ""} · 보존 자료 ${(attempt.partial_result?.documents || []).length}개`
    ])));
    const view=workflowUI.modal("검증 작업 기록",[content],async()=>{},true);view.submit.hidden=true;
  }
  async function runHistory() {
    const pid=state.project.id, runs=await api(`/projects/${pid}/runs?limit=100`),content=node("div",null,"full");
    if(pid!==state.project?.id)return;
    const view=workflowUI.modal("검증 실행 이력",[content],async()=>{},true);view.submit.hidden=true;
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
      if(await ask("검증 재시도","당시 자료와 설정으로 새 검증을 실행합니다. 외부 AI 요청이 다시 발생할 수 있습니다.")===null)return;
      const retry=await api(`/verification-runs/${run.id}/retry`,{method:"POST"});await selectRun(retry);
    }));
  }
  function init() {
    const accountButton=iconButton("user-round","내 계정",account);accountButton.id="accountButton";
    $("settingsButton").before(accountButton);
    const jobs=node("div",null,"toolbar job-controls");jobs.id="jobControls";$("progress").after(jobs);
  }
  return {init,authenticate,refreshIdentity,renderJobControls};
})();
