"use strict";

const projectTools = (() => {
  let timer = null, busy = false, authRequired = false, jobs = [], activeCount = 0;
  let jobsRoot = null, jobButton = null;
  const baseTitle = "ACASia_LAW 법률문서 검증시스템";

  function renderControls() {
    const control = $("deleteProject");
    if (!control) return;
    control.hidden = !state.project?.can_delete;
    control.disabled = !!state.uploadBatch?.busy || !!(state.run && !terminal(state.run));
    control.title = control.disabled ? "검증 또는 파일 등록 완료 후 삭제" : "프로젝트 삭제";
  }

  function clearProject() {
    clearTimeout(state.timer);
    state.generation++;
    state.project = state.run = state.viewing = state.pollError = state.progressSeen = null;
    if (!state.uploadBatch?.busy) state.uploadBatch = null;
    state.editing = null;
    state.documents = []; state.findings = []; state.pages = []; state.result = {};
    state.selected.clear();
    localStorage.removeItem("acas-project");
    $("projectView").hidden = true; $("emptyState").hidden = false;
    document.dispatchEvent(new Event("acas-project-changed"));
    renderProjects(); renderControls();
  }

  async function removeProject() {
    const project = state.project;
    if (!project?.can_delete || state.uploadBatch?.busy) return;
    if (await ask("프로젝트 삭제", `‘${project.name}’ 프로젝트를 휴지통으로 이동합니다. 자료·검증 결과·활동 기록은 보존되며 휴지통에서 복원할 수 있습니다.`) === null) return;
    $("deleteProject").disabled = true;
    try {
      await api(`/projects/${project.id}`, {method:"DELETE"});
      if (state.project?.id === project.id) clearProject();
      await loadProjects();
      if (!state.project && state.projects.length) await openProject(state.projects[0].id);
      await refresh();
      toast("프로젝트를 휴지통으로 이동했습니다.");
    } finally { renderControls(); }
  }

  async function trash() {
    const root = node("div", null, "full project-trash");
    const view = workflowUI.modal("프로젝트 휴지통", [root], async () => {}, true);
    view.submit.hidden = true;
    async function draw() {
      const projects = await api("/projects?deleted=true");
      if (!root.isConnected) return;
      root.replaceChildren();
      if (!projects.length) return empty(root, "삭제된 프로젝트가 없습니다.");
      for (const project of projects) {
        const row = node("div", null, "row-item project-trash-item");
        const info = node("div");
        info.append(node("h3", project.name), node("p", `자료 ${project.document_count}개 · 삭제 ${dateText(project.deleted_at)}`, "muted"));
        const restore = button("복원", async () => {
          restore.disabled = true;
          try {
            await api(`/projects/${project.id}/restore`, {method:"POST"});
            await loadProjects(); await draw();
            if (!state.project) await openProject(project.id);
            toast("프로젝트를 복원했습니다.");
          } finally { restore.disabled = false; }
        });
        const icon = node("i"); icon.dataset.lucide = "rotate-ccw"; restore.prepend(icon);
        row.append(info, restore); root.append(row);
      }
      icons();
    }
    try { await draw(); } catch (error) { root.replaceChildren(node("p", error.message, "error")); }
  }

  function drawJobs() {
    if (jobButton) {
      jobButton.querySelector("span").textContent = authRequired ? "작업 조회 로그인" : `진행 작업 ${activeCount}`;
      jobButton.title = authRequired ? "로그인 후 작업 조회" : `서버에서 진행 중인 검증 ${activeCount}건`;
    }
    document.title = activeCount ? `검증 ${activeCount}건 진행 중 · ${baseTitle}` : baseTitle;
    if (!jobsRoot?.isConnected) return;
    jobsRoot.replaceChildren();
    if (authRequired) {
      jobsRoot.append(button("다시 로그인", () => operationsUI.authenticate()));
      return;
    }
    if (!jobs.length) return empty(jobsRoot, "진행 중인 검증이나 최근 24시간 내 완료된 검증이 없습니다.");
    for (const run of jobs) {
      const row = node("article", null, "row-item background-job");
      const heading = button(run.project_name, async () => {
        const dialog = jobsRoot?.closest("dialog");
        dialog?.close();
        await openProject(run.project_id);
        const fullRun = await api(`/verification-runs/${run.id}`);
        await operationsUI.selectRun(fullRun);
      }, "row-title");
      row.append(heading, node("span", label(run.state), "badge"), node("p", run.stage_message || label(run.state), "muted"));
      if (!terminal(run)) {
        const progress = node("progress"); progress.max = 100;
        progress.value = Math.min(100, Math.max(0, run.progress <= 1 ? run.progress * 100 : run.progress));
        progress.setAttribute("aria-label", `${run.project_name} 진행률`); row.append(progress);
      }
      jobsRoot.append(row);
    }
  }

  async function refresh() {
    clearTimeout(timer);
    if (busy || authRequired) return;
    busy = true;
    let retry = false;
    try {
      const data = await api("/verification-runs", {interactiveAuth:false, timeoutMs:15000});
      if (!Array.isArray(data?.runs) || !Number.isInteger(data.active_count)) throw new Error("작업 목록을 읽지 못했습니다.");
      const previous = new Set(jobs.filter(run => !terminal(run)).map(run => run.id));
      jobs = data.runs; activeCount = data.active_count;
      const finished = jobs.filter(run => previous.has(run.id) && terminal(run) && run.id !== state.run?.id);
      if (finished.length && !document.hidden) toast(`다른 프로젝트의 검증 ${finished.length}건이 종료되었습니다.`);
      drawJobs();
      retry = activeCount > 0;
    } catch (error) {
      if (error.status === 401) {
        authRequired = true; jobs = []; activeCount = 0; drawJobs();
      } else {
        retry = true;
        if (jobButton) jobButton.title = "작업 목록 연결 확인 필요";
      }
    } finally {
      busy = false;
      if (retry) timer = setTimeout(refresh, document.hidden ? 30000 : 10000);
    }
  }

  function start() { authRequired = false; return refresh(); }

  async function showJobs() {
    if (authRequired) await operationsUI.authenticate();
    const root = node("div", null, "full background-jobs");
    const view = workflowUI.modal("검증 작업", [root], async () => {}, true);
    view.submit.hidden = true; jobsRoot = root;
    drawJobs(); await refresh();
  }

  function init() {
    const remove = iconButton("trash-2", "프로젝트 삭제", removeProject);
    remove.id = "deleteProject"; remove.hidden = true; $("editProject").after(remove);
    const bar = node("div", null, "sidebar-tools");
    jobButton = button(null, showJobs); jobButton.id = "backgroundJobsButton";
    const jobIcon = node("i"); jobIcon.dataset.lucide = "list-checks";
    jobButton.append(jobIcon, node("span", "진행 작업 0"));
    const trashButton = button("휴지통", trash); trashButton.id = "projectTrashButton";
    const trashIcon = node("i"); trashIcon.dataset.lucide = "trash-2"; trashButton.prepend(trashIcon);
    bar.append(jobButton, trashButton); $("projectSearch").before(bar);
    let wakeTimer;
    function wake() {
      if (document.hidden) return;
      clearTimeout(wakeTimer);
      wakeTimer = setTimeout(() => {
        if (!authRequired) refresh();
        if (state.run && !state.pollError?.authRequired && !state.pollError?.unavailable && (!terminal(state.run) || state.pollError)) pollRun(state.generation, 0);
      }, 100);
    }
    document.addEventListener("visibilitychange", wake);
    for (const event of ["pageshow", "online", "focus"]) window.addEventListener(event, wake);
    // Browser suspension can delay UI polling, never the durable server job.
    window.addEventListener("pagehide", () => {clearTimeout(timer); clearTimeout(state.timer);});
  }

  return {init, start, refresh, renderControls, clearProject};
})();
