"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  projects: [],
  project: null,
  documents: [],
  run: null,
  result: {},
  findings: [],
  selected: new Set(),
  generation: 0,
  timer: null,
  editing: null,
  creationKey: null,
  viewing: null,
  page: 1,
  pages: []
};
const labels = {
  LOCAL_ONLY: "외부 AI 전송 안 함",
  MASKED: "개인정보 가림 후 전송",
  ORIGINAL: "원문 전송 허용",
  UNSPECIFIED: "미지정",
  OWN: "우리 측",
  OPPONENT: "상대방",
  COURT: "법원",
  THIRD_PARTY: "제3자",
  CRITICAL: "매우 높음",
  HIGH: "높음",
  MEDIUM: "보통",
  LOW: "낮음",
  INFO: "참고",
  NEEDS_REVIEW: "확인 전",
  ACCEPTED: "지적 수용",
  FALSE_POSITIVE: "오탐",
  RESOLVED: "조치 완료",
  VERIFIED: "확인됨",
  PARTIALLY_VERIFIED: "일부 확인",
  UNVERIFIED: "확인 불가",
  CONTRADICTED: "불일치",
  PENDING: "미실행",
  SKIPPED: "미실행",
  COMPLETED: "검증 완료",
  PARTIAL_COMPLETED: "일부 미확인",
  FAILED: "실행 실패",
  QUEUED: "대기 중",
  RUNNING: "검증 중",
  CANCELLED: "취소됨"
};
const label = (value) => labels[value] || value || "미지정";
Object.assign(labels, {PARSING:"문서 읽는 중",ADVERSARIAL_SCANNING:"검증 방해 문구 검사",EXTRACTING:"본문 추출 중",PII_PROCESSING:"개인정보 처리 중",VERIFYING:"인용 확인 중",CROSS_CHECKING:"자료 대조 중",AGGREGATING:"결과 정리 중",NOT_FOUND:"출처에서 미확인",SUSPICIOUS:"확인 필요",ERROR:"처리 오류"});
function friendlyText(value) {
  let text = String(value || "");
  text = text.replaceAll("Creator와 Producer가", "작성 프로그램과 PDF 생성 프로그램이")
    .replaceAll("UNVERIFIED로", "미확인 상태로");
  for (const [technical, simple] of [["UNVERIFIED","확인하지 못함"],["Source","출처"],["Creator","작성 프로그램"],["Producer","PDF 생성 프로그램"],["Author","작성자"],["QUARANTINED","안전 검토 필요"],["Python 계산엔진으로 검산한 결정론적 결과이다.","계산식에 따라 자동 검산한 결과입니다."]]) text = text.replaceAll(technical, simple);
  return text;
}
const terminal = (run) => run && ["COMPLETED", "PARTIAL_COMPLETED", "FAILED", "CANCELLED"].includes(run.state);
const icons = () => window.lucide?.createIcons();

function node(tag, text, cls) {
  const el = document.createElement(tag);
  if (text != null) el.textContent = String(text);
  if (cls) el.className = cls;
  return el;
}

function empty(parent, message) {
  parent.replaceChildren(node("p", message, "empty-small"));
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").hidden = true, 6500);
}
async function api(path, options = {}) {
  const headers = {
    ...options.headers
  };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const requestOptions = {
    ...options,
    headers,
    credentials: "same-origin"
  };
  let response = await fetch(`/api${path}`, requestOptions);
  if (response.status === 401) {
    await operationsUI.authenticate();
    response = await fetch(`/api${path}`, requestOptions);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : data?.detail?.message || `요청 실패 (${response.status})`);
  return data;
}

function action(fn) {
  return async (event) => {
    try {
      await fn(event);
    } catch (error) {
      toast(error.message);
    }
  };
}

function button(text, click, cls) {
  const el = node("button", text, cls);
  el.type = "button";
  el.addEventListener("click", action(click));
  return el;
}

function iconButton(icon, title, click) {
  const el = button(null, click, "icon");
  el.title = title;
  el.setAttribute("aria-label", title);
  const image = node("i");
  image.dataset.lucide = icon;
  el.append(image);
  return el;
}

function safeLink(url, text) {
  try {
    const target = new URL(url, location.origin);
    if (!["http:", "https:"].includes(target.protocol)) return node("span", text);
    const a = node("a", text);
    a.href = target.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch {
    return node("span", text);
  }
}

function dateText(value) {
  return value ? new Date(value.endsWith?.("Z") ? value : `${value}Z`).toLocaleString("ko-KR") : "";
}

function switchTab(tab) {
  document.querySelectorAll("[data-tab]").forEach(el => {
    el.classList.toggle("active", el.dataset.tab === tab);
    el.setAttribute("aria-current", el.dataset.tab === tab ? "page" : "false");
  });
  document.querySelectorAll("[data-panel]").forEach(el => el.hidden = el.dataset.panel !== tab);
  if (tab === "audit") loadAudit().catch(e => toast(e.message));
  workflowUI.activate(tab).catch(e => toast(e.message));
}
async function loadProjects() {
  state.projects = await api("/projects");
  renderProjects();
}

function renderProjects() {
  const query = $("projectSearch").value.toLowerCase();
  $("projectList").replaceChildren();
  for (const p of state.projects.filter(p => `${p.name} ${p.case_number||""}`.toLowerCase().includes(query))) {
    const b = button(p.name, () => openProject(p.id), p.id === state.project?.id ? "active" : "");
    b.append(node("small", `${p.case_number||"사건번호 미지정"} · 자료 ${p.document_count}개`));
    $("projectList").append(b);
  }
}
async function openProject(id) {
  clearTimeout(state.timer);
  const generation = ++state.generation;
  state.selected.clear();
  const p = await api(`/projects/${id}`);
  const docs = await api(`/projects/${id}/documents`);
  const runs = await api(`/projects/${id}/runs`);
  if (generation !== state.generation) return;
  state.project = p;
  document.dispatchEvent(new Event("acas-project-changed"));
  state.documents = docs;
  state.run = runs[0] || null;
  state.findings = [];
  state.result = {};
  $("sidebar").classList.remove("open");
  $("emptyState").hidden = true;
  $("projectView").hidden = false;
  localStorage.setItem("acas-project", id);
  renderProject();
  await loadResults(generation);
  await loadReports();
  if (state.run && !terminal(state.run)) pollRun(generation);
}

function renderProject() {
  const p = state.project;
  if (!p) return;
  $("projectTitle").textContent = p.name;
  $("projectMeta").textContent = [p.case_number || "사건번호 미지정", p.court, p.incident_date ? `적용법령 기준 ${p.incident_date}` : "적용법령 기준일 미지정"].filter(Boolean).join(" · ");
  $("policyLabel").textContent = label(p.external_ai_policy);
  $("staleNotice").hidden = !state.run || state.run.input_snapshot?.scope_revision === p.scope_revision;
  const busy = state.run && !terminal(state.run);
  $("verifyBtn").disabled = !!busy || !state.documents.some(d => d.included_in_verification);
  $("reverify").disabled = $("verifyBtn").disabled;
  $("progress").hidden = !busy;
  if (busy) {
    const percent = Math.round(state.run.progress * (state.run.progress <= 1 ? 100 : 1));
    $("progressText").textContent = state.run.stage_message || label(state.run.state);
    $("progressPercent").textContent = `${percent}%`;
    $("progressBar").value = percent;
  }
  renderProjects();
  renderDocuments();
  renderSummary();
  renderIssues();
  renderTimeline();
  operationsUI.renderJobControls();
  $("reportScope").textContent = state.run ? `${dateText(state.run.started_at)} · 자료 ${state.run.document_ids.length}개 · ${label(state.run.state)}${$("staleNotice").hidden?"":" · 변경 전 자료 기준"}` : "검증 결과가 없습니다.";
  $("createReport").disabled = !["COMPLETED","PARTIAL_COMPLETED"].includes(state.run?.state);
}

function renderSummary() {
  $("summary").replaceChildren();
  let aiStatus = "미분석";
  let fakeCaseCount = 0;
  const docs = state.result?.documents || [];
  for (const d of docs) {
    if (d.ai_detector_result?.verdict === "AI_FULL_GENERATION_LIKELY") {
      aiStatus = "AI 전체 작성 의심";
    } else if (d.ai_detector_result?.verdict === "AI_PARTIAL_GENERATION" && aiStatus !== "AI 전체 작성 의심") {
      aiStatus = "일부 AI 작성";
    } else if (d.ai_detector_result?.verdict === "HUMAN_AUTHORED_LIKELY" && aiStatus === "미분석") {
      aiStatus = "인간 작성 유력";
    }
    if (d.ai_hallucination_table) {
      fakeCaseCount += d.ai_hallucination_table.length;
    }
  }
  if (aiStatus === "미분석" && state.findings.some(f => f.type === "AI_FULL_GENERATION_SUSPECTED")) {
    aiStatus = "AI 전체 작성 의심";
  }

  const gate = state.run?.scores?.release_gate || null;
  const metrics = [
    ["검토에 포함", `${state.documents.filter(d=>d.included_in_verification).length} / ${state.documents.length}`],
    ["배포가능 상태", gate ? GATE_LABELS[gate.release_gate] || gate.release_gate : "—"],
    ["검증위험 지수", gate ? `${gate.hallucination_risk}점` : "—"],
    ["AI 작성 진단", state.run ? aiStatus : "—"],
    ["가짜 판례 의심", state.run ? `${fakeCaseCount}건` : "—"],
    ["확인 전 항목", state.findings.filter(f => f.review_status === "NEEDS_REVIEW").length],
    ["진행 상태", state.run ? label(state.run.state) : "시작 전"]
  ];
  for (const [title, value] of metrics) {
    const el = node("div", null, "metric");
    el.append(node("span", title), node("strong", value));
    if (title === "배포가능 상태" && gate) el.classList.add(`gate-${gate.release_gate.toLowerCase()}`);
    $("summary").append(el);
  }
  if (gate) renderGateReasons(gate);
}

// 제9.2장. 차단 사유와 사람 검토 사유를 상태값과 함께 보여준다.
// 상태값만 있으면 무엇을 고쳐야 하는지 알 수 없다.
const GATE_LABELS = {
  PASS: "배포 가능",
  PASS_WITH_WARNINGS: "경고 포함 배포 가능",
  HUMAN_REVIEW_REQUIRED: "사람 검토 필요",
  BLOCK: "배포 차단"
};

function renderGateReasons(gate) {
  const reasons = [...(gate.hard_block_reasons || []), ...(gate.review_reasons || [])];
  if (!reasons.length) return;
  const details = node("details", null, "gate-reasons");
  details.append(node("summary", `${GATE_LABELS[gate.release_gate] || gate.release_gate} 사유 ${reasons.length}건`));
  const list = node("ul");
  for (const reason of reasons) list.append(node("li", friendlyText(reason)));
  details.append(list);
  details.append(node("p", gate.risk_index_note || "", "muted"));
  $("summary").append(details);
}

function filteredDocuments() {
  return state.documents.filter(d => $("scopeFilter").value === "all" || d.included_in_verification === ($("scopeFilter").value === "included"));
}

function renderDocuments() {
  const docs = filteredDocuments();
  $("documentRows").replaceChildren();
  $("scopeCount").textContent = `${state.documents.filter(d=>d.included_in_verification).length}개 포함 · ${state.documents.filter(d=>!d.included_in_verification).length}개 제외`;
  $("documentEmpty").hidden = docs.length > 0;
  $("documentEmpty").textContent = state.documents.length ? "조건에 맞는 자료가 없습니다." : "등록된 자료가 없습니다.";
  for (const d of docs) {
    const tr = node("tr");
    const check = node("input");
    check.type = "checkbox";
    check.checked = state.selected.has(d.id);
    check.setAttribute("aria-label", `${d.filename} 선택`);
    check.onchange = () => {
      if (check.checked) state.selected.add(d.id);
      else state.selected.delete(d.id);
      renderSelection();
    };
    const td = node("td");
    td.append(check);
    const file = node("td");
    file.append(button(d.filename, () => openDocument(d), "file-name"), node("small", `${Math.max(1,Math.ceil(d.size_bytes/1024))} KB · ${d.document_kind||"문서"}${d.quarantined?" · 안전 검토 필요":""}`, "file-sub"));
    const evidence = node("td");
    evidence.append(node("div", d.evidence_number || "증거번호 미지정"), node("small", label(d.submitted_by), "file-sub"));
    const scope = node("td");
    scope.append(node("span", d.included_in_verification ? "검토에 포함" : "검토에서 제외", `badge ${d.included_in_verification?"":"excluded"}`));
    if (d.exclusion_reason) {
      const reason = node("small", d.exclusion_reason, "file-sub");
      scope.append(reason);
    }
    const controls = node("td");
    const group = node("div", null, "actions");
    group.append(iconButton("pencil", "자료 정보 편집", () => editDocument(d)), iconButton(d.included_in_verification ? "circle-minus" : "circle-plus", d.included_in_verification ? "검토에서 제외" : "검토에 다시 포함", () => setScope([d.id], !d.included_in_verification)));
    controls.append(group);
    tr.append(td, file, evidence, scope, controls);
    $("documentRows").append(tr);
  }
  renderSelection();
  icons();
}

function renderSelection() {
  $("bulkActions").hidden = !state.selected.size;
  $("selectedCount").textContent = `${state.selected.size}개 선택`;
  const docs = filteredDocuments();
  $("selectAll").checked = docs.length > 0 && docs.every(d => state.selected.has(d.id));
  $("selectAll").indeterminate = docs.some(d => state.selected.has(d.id)) && !$("selectAll").checked;
}
async function refreshScope() {
  const id = state.project.id;
  const p = await api(`/projects/${id}`);
  const docs = await api(`/projects/${id}/documents`);
  if (state.project?.id !== id) return;
  state.project = p;
  state.documents = docs;
  await loadProjects();
  renderProject();
}
async function setScope(ids, included) {
  const projectId = state.project.id;
  let reason = "";
  if (!included) {
    reason = await ask("검토에서 제외", "원본은 보존되며 언제든 다시 포함할 수 있습니다.", true);
    if (reason === null) return;
  }
  await api(`/projects/${projectId}/document-scope`, {
    method: "PATCH",
    body: {
      document_ids: ids,
      included_in_verification: included,
      exclusion_reason: reason
    }
  });
  state.selected.clear();
  await refreshScope();
  toast(included ? "자료를 검토에 다시 포함했습니다." : "자료를 검토에서 제외했습니다. 원본은 보존됩니다.");
}
function ask(title, message, reasonInput = false) {
  return new Promise(resolve => {
    const dialog = node("dialog");
    dialog.id = "confirmationDialog";
    dialog.setAttribute("aria-label", title);
    const form = node("form");
    form.method = "dialog";
    form.append(node("h2", title), node("p", message));
    const input = node("textarea");
    if (reasonInput) {
      const field = node("label", "제외 사유 (선택)");
      input.rows = 3;
      input.maxLength = 2000;
      input.setAttribute("aria-label", "제외 사유");
      field.append(input);
      form.append(field);
    }
    const footer = node("div", null, "dialog-footer");
    footer.append(button("취소", () => dialog.close("cancel")));
    const submit = node("button", "확인", "primary");
    submit.type = "submit";
    footer.append(submit);
    form.append(footer);
    form.addEventListener("submit", event => { event.preventDefault(); dialog.close("confirm"); });
    dialog.append(form);
    dialog.addEventListener("close", () => { const result = dialog.returnValue === "confirm" ? input.value : null; dialog.remove(); resolve(result); }, {once: true});
    document.body.append(dialog);
    dialog.showModal();
  });
}

async function upload(files) {
  const id = state.project?.id;
  if (!id) return;
  let success = 0;
  const failures = [];
  for (const file of files) {
    const form = new FormData();
    form.append("file", file);
    try {
      await api(`/projects/${id}/documents`, {
        method: "POST",
        body: form
      });
      success++;
    } catch (error) {
      failures.push(`${file.name}: ${error.message}`);
    }
  }
  $("fileInput").value = "";
  if (state.project?.id === id) await refreshScope();
  toast(`${success}개 등록${failures.length?` · ${failures.join(" / ")}`:""}`);
}
async function editProject(isNew = false) {
  state.editing = isNew ? null : state.project.id;
  const data = isNew ? await api("/project-defaults") : state.project;
  state.creationKey = data.creation_key || null;
  const form = $("projectForm");
  form.reset();
  for (const field of ["name", "case_number", "court", "incident_date", "verification_profile", "external_ai_policy", "memo"]) form.elements[field].value = data[field] || "";
  for (const field of ["parties", "requested_issues"]) form.elements[field].value = (data[field] || []).join("\n");
  $("projectDialogTitle").textContent = isNew ? "새 프로젝트" : "프로젝트 편집";
  $("projectSubmit").textContent = isNew ? "생성" : "저장";
  $("projectError").textContent = "";
  $("projectDialog").showModal();
}
async function saveProject(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  for (const key of ["case_number", "court", "incident_date"]) data[key] = data[key] || null;
  for (const key of ["parties", "requested_issues"]) data[key] = data[key].split("\n").map(s => s.trim()).filter(Boolean);
  if (data.external_ai_policy === "ORIGINAL" && (state.editing ? state.project?.external_ai_policy : null) !== "ORIGINAL") {
    if (await ask("원문 전송 허용", "개인정보와 비밀정보를 포함한 원문이 설정된 외부 AI로 전송될 수 있습니다.") === null) return;
  }
  if (!state.editing) data.creation_key = state.creationKey;
  $("projectSubmit").disabled = true;
  try {
    const p = await api(state.editing ? `/projects/${state.editing}` : "/projects", {
      method: state.editing ? "PATCH" : "POST",
      body: data
    });
    $("projectDialog").close();
    await loadProjects();
    await openProject(p.id);
  } catch (error) {
    $("projectError").textContent = error.message;
  } finally {
    $("projectSubmit").disabled = false;
  }
}

function editDocument(d) {
  state.editDocumentId = d.id;
  for (const field of ["evidence_number", "submitted_by", "document_kind", "submitted_on"]) $("documentForm").elements[field].value = d[field] || "";
  $("documentDialog").showModal();
}
async function verify() {
  const id = state.project.id;
  $("verifyBtn").disabled = true;
  try {
    state.run = await api(`/projects/${id}/verify`, {
      method: "POST",
      body: {}
    });
    state.findings = [];
    state.result = {};
    renderProject();
    renderFindings();
    if (terminal(state.run)) await loadResults(state.generation);
    else pollRun(state.generation);
  } catch (error) {
    renderProject();
    throw error;
  }
}

function pollRun(generation) {
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    if (generation !== state.generation) return;
    try {
      const run = await api(`/verification-runs/${state.run.id}`);
      if (generation !== state.generation) return;
      state.run = run;
      renderProject();
      if (terminal(run)) {
        await loadResults(generation);
        toast(label(run.state));
      } else pollRun(generation);
    } catch (error) {
      toast(error.message);
      pollRun(generation);
    }
  }, 1500);
}
async function loadResults(generation) {
  if (!state.run) {
    renderFindings();
    await workflowUI.refresh();
    return;
  }
  const result = await api(`/verification-runs/${state.run.id}/result`);
  const findings = await api(`/projects/${state.project.id}/findings?run_id=${state.run.id}`);
  if (generation !== state.generation) return;
  state.result = result;
  state.findings = findings;
  await workflowUI.refresh();
  if (generation !== state.generation) return;
  renderProject();
  renderFindings();
  renderAIVerification();
}

function renderFindings() {
  const query = $("findingSearch").value.toLowerCase();
  const findings = state.findings.filter(f => workflowUI.matches(f) && (!$("reviewFilter").value || f.review_status === $("reviewFilter").value) && (!$("severityFilter").value || f.severity === $("severityFilter").value) && `${f.title} ${f.detail}`.toLowerCase().includes(query)).sort((a,b) => workflowUI.priority(a) - workflowUI.priority(b));
  $("findings").replaceChildren();
  if (!findings.length) empty($("findings"), state.run ? "표시할 확인 항목이 없습니다. 미확인 범위는 보고서에서 별도로 확인할 수 있습니다." : "검증 결과가 없습니다.");
  for (const f of findings) {
    const row = node("article", null, "row-item");
    const title = button(null, () => openFinding(f), "row-title");
    workflowUI.decorateFinding(f, row);
    title.append(node("span", label(f.severity), `badge ${f.severity}`), node("strong", friendlyText(f.title)));
    row.append(title, node("p", friendlyText(f.detail)), node("div", `${state.documents.find(d=>d.id===f.document_id)?.filename||"프로젝트 전체"}${f.page?` · ${f.page}쪽`:""} · ${label(f.status)} · ${label(f.review_status)}${f.advisory_only?" · 참고 의견":""}`, "row-meta"));
    $("findings").append(row);
  }
  if (state.run?.unverified_items.length) {
    const details = node("details", null, "detail-section");
    details.append(node("summary", `미확인 범위 ${state.run.unverified_items.length}건`));
    for (const item of state.run.unverified_items) details.append(node("p", friendlyText(`${item.raw_text || item.document_id || ""} ${item.page ? `· ${item.page}쪽` : ""}: ${item.reason || "확인하지 못함"}`)));
    $("findings").append(details);
  }
}

function renderAIVerification() {
  const container = $("aiVerificationRows");
  const emptyMsg = $("aiVerificationEmpty");
  const cardsContainer = $("aiSummaryCards");
  if (!container || !cardsContainer) return;

  container.replaceChildren();
  cardsContainer.replaceChildren();

  const docs = state.result?.documents || [];
  let allRows = [];
  let detectorResults = [];
  let hasQuarantine = false;

  for (const d of docs) {
    if (d.quarantined) hasQuarantine = true;
    if (d.ai_detector_result && d.ai_detector_result.verdict) {
      detectorResults.push({ filename: d.filename, ...d.ai_detector_result });
    }
    if (d.ai_hallucination_table && Array.isArray(d.ai_hallucination_table)) {
      for (const row of d.ai_hallucination_table) {
        allRows.push({ filename: d.filename, ...row });
      }
    }
  }

  // AI 종합 요약 카드 렌더링
  const card1 = node("div", null, "summary-card");
  card1.append(node("h3", "문서 AI 생성 여부 진단"));
  if (detectorResults.length > 0) {
    for (const res of detectorResults) {
      let verdictLabel = "판단 보류";
      let badgeClass = "badge INFO";
      if (res.verdict === "AI_FULL_GENERATION_LIKELY") {
        verdictLabel = "AI 임의 전체 작성 유력";
        badgeClass = "badge CRITICAL";
      } else if (res.verdict === "AI_PARTIAL_GENERATION") {
        verdictLabel = "일부 AI 작성·인용 내용 확인";
        badgeClass = "badge HIGH";
      } else if (res.verdict === "HUMAN_AUTHORED_LIKELY") {
        verdictLabel = "인간(변호사/당사자) 작성 유력";
        badgeClass = "badge VERIFIED";
      }
      const item = node("div", null, "card-item");
      item.append(
        node("div", `${res.filename}: `),
        node("span", verdictLabel, badgeClass),
        node("small", ` (신뢰도: ${Math.round((res.score || 0) * 100)}%)`, "muted")
      );
      if (res.reasons && res.reasons.length > 0) {
        const reasonList = node("ul", null, "reason-list");
        for (const r of res.reasons.slice(0, 3)) {
          reasonList.append(node("li", r));
        }
        item.append(reasonList);
      }
      card1.append(item);
    }
  } else {
    card1.append(node("p", state.run ? "검증 완료 후 분석 결과를 표시합니다." : "검증을 시작하면 AI 작성 여부를 진단합니다.", "muted"));
  }

  const card2 = node("div", null, "summary-card");
  card2.append(node("h3", "허위 판례(할루시네이션) 발견"));
  if (allRows.length > 0) {
    card2.append(
      node("p", `공식 법원 DB에서 확인되지 않는 판례 및 이를 전제로 한 주장이 총 ${allRows.length}건 발견되었습니다.`, "warning-text")
    );
  } else {
    card2.append(node("p", state.run ? "공식 소스에서 확인되지 않는 허위 판례가 발견되지 않았습니다." : "미실행", "safe-text"));
  }

  const card3 = node("div", null, "summary-card");
  card3.append(node("h3", "프롬프트 인젝션 속임수 검증"));
  if (hasQuarantine) {
    card3.append(node("p", "경고: 프롬프트 인젝션 등 AI 판단 왜곡 시도가 탐지되어 격리(QUARANTINED)되었습니다.", "danger-text"));
  } else {
    card3.append(node("p", state.run ? "정상: 문서를 왜곡하려는 악의적 프롬프트 인젝션이 발견되지 않았습니다." : "미실행", "safe-text"));
  }

  cardsContainer.append(card1, card2, card3);

  // 테이블 렌더링
  if (allRows.length === 0) {
    if (emptyMsg) emptyMsg.hidden = false;
    return;
  }
  if (emptyMsg) emptyMsg.hidden = true;

  for (const r of allRows) {
    const tr = node("tr");
    const tdLoc = node("td", `${r.filename}\n${r.location || ""}`);
    const tdClaim = node("td");
    tdClaim.append(
      node("strong", r.cited_authority || "인용 판례"),
      node("p", r.claim_text || "", "claim-text")
    );
    const tdBasis = node("td", r.ai_generation_basis || "공식 소스 미존재");
    const tdReason = node("td");
    tdReason.append(
      node("p", r.legal_reasoning || "", "legal-reasoning"),
      node("div", `대응 방안: ${r.recommended_counteraction || ""}`, "counteraction-box")
    );
    const tdVerdict = node("td");
    let verdictCls = "badge HIGH";
    if (String(r.validity_verdict).includes("부당") || String(r.validity_verdict).includes("결여")) {
      verdictCls = "badge CRITICAL";
    }
    tdVerdict.append(node("span", r.validity_verdict || "확인 필요", verdictCls));

    tr.append(tdLoc, tdClaim, tdBasis, tdReason, tdVerdict);
    container.append(tr);
  }
}

function renderIssues() {
  $("issueTags").replaceChildren(...(state.project.requested_issues || []).map(t => node("span", t, "issue-tag")));
  const claims = (state.result.documents || []).flatMap(d => (d.claims || []).map(c => ({
    ...c,
    filename: d.filename
  })));
  $("claims").replaceChildren();
  if (!claims.length) empty($("claims"), "추출된 주장이 없습니다.");
  for (const c of claims) {
    const row = node("article", null, "row-item");
    row.append(node("p", c.text || c.claim_text || c.statement || JSON.stringify(c)), node("div", `${c.filename} · ${c.page||"?"}쪽 · 자동 추출 · 입증 여부 미판단`, "row-meta"));
    for (const link of c.evidence_links || []) {
      if (!link.document_ids.length) row.append(node("p", `${link.reference}: 등록 자료 없음`, "muted"));
      for (const id of link.document_ids) {
        const document = state.documents.find(d => d.id === id);
        if (document) row.append(button(`${link.reference} · ${document.filename}`, () => openDocument(document)));
      }
    }
    $("claims").append(row);
  }
}

function renderTimeline() {
  $("timeline").replaceChildren();
  const events = state.run?.timeline || [];
  if (!events.length) empty($("timeline"), "추출된 사건 일지가 없습니다.");
  for (const e of events) {
    const row = node("article", null, "row-item");
    row.append(node("strong", e.date || e.event_date || "날짜 미확인"), node("p", e.description || e.text || JSON.stringify(e)), node("div", `${state.documents.find(d=>d.id===e.document_id)?.filename||""} · 문서 기재 내용 기준`, "row-meta"));
    $("timeline").append(row);
  }
}
async function openDocument(d, finding = null, runId = state.run?.id) {
  state.viewing = {
    document: d,
    finding
  };
  state.page = finding?.page || 1;
  $("detailTitle").textContent = friendlyText(finding?.title) || "자료 원문";
  $("viewerFilename").textContent = d.filename;
  $("originalDownload").href = `/api/documents/${d.id}/original`;
  $("originalDownload").hidden = false;
  $("detailContent").replaceChildren();
  if (finding) renderDetail(finding);
  else $("detailContent").append(node("p", `${d.evidence_number||"증거번호 미지정"} · ${label(d.submitted_by)}`), node("p", `SHA-256: ${d.sha256}`, "technical"));
  if (!$("detailDialog").open) $("detailDialog").showModal();
  const blocks = await api(`/documents/${d.id}/blocks?include_hidden=false${runId?`&run_id=${runId}`:""}`);
  if (state.viewing?.document?.id !== d.id) return;
  state.pages = blocks.pages;
  state.blocks = blocks.blocks;
  await renderPage();
}
async function openFinding(f) {
  const d = state.documents.find(d => d.id === f.document_id);
  if (d) return openDocument(d, f);
  state.viewing = null;
  $("detailTitle").textContent = friendlyText(f.title);
  $("viewerFilename").textContent = "프로젝트 전체";
  $("originalDownload").hidden = true;
  $("prevPage").disabled = true;
  $("nextPage").disabled = true;
  $("pageNumber").textContent = "";
  $("pageArea").replaceChildren();
  $("detailContent").replaceChildren();
  renderDetail(f);
  $("detailDialog").showModal();
}
async function renderPage() {
  const {
    document: d,
    finding: f
  } = state.viewing;
  $("pageNumber").textContent = `${state.page} / ${Math.max(state.pages.length,state.page)}`;
  $("prevPage").disabled = state.page <= 1;
  $("nextPage").disabled = state.page >= state.pages.length;
  $("pageArea").replaceChildren();
  if (d.filename.toLowerCase().endsWith(".pdf")) {
    const img = node("img");
    img.alt = `${d.filename} ${state.page}쪽 원문`;
    img.src = `/api/documents/${d.id}/pages/${state.page}.png`;
    img.onerror = () => empty($("pageArea"), "이 페이지의 원문 이미지를 표시할 수 없습니다.");
    $("pageArea").append(img);
    const page = state.pages.find(p => p.page_number === state.page);
    if (f?.bbox && f.page === state.page && page?.width && page?.height) {
      const [x0, y0, x1, y1] = f.bbox;
      const box = node("div", null, "highlight-box");
      Object.assign(box.style, {
        left: `${x0/page.width*100}%`,
        top: `${y0/page.height*100}%`,
        width: `${(x1-x0)/page.width*100}%`,
        height: `${(y1-y0)/page.height*100}%`
      });
      $("pageArea").append(box);
    }
  } else {
    $("pageArea").append(node("p", "추출된 본문", "muted"), node("pre", (state.blocks || []).filter(b => b.page === state.page).map(b => b.text).join("\n\n") || "본문 추출 결과가 없습니다."));
  }
}

function renderDetail(f) {
  const area = $("detailContent");
  area.replaceChildren(node("span", `${label(f.severity)} · ${label(f.status)}`, `badge ${f.severity}`), node("p", friendlyText(f.detail)));
  for (const e of f.evidence || []) {
    area.append(node("blockquote", e.sealed ? "보호된 내용은 별도 열람 승인이 필요합니다." : e.excerpt || e.description || e.note || "발췌문 없음", "evidence"));
  }
  for (const source of f.sources || []) area.append(safeLink(typeof source === "string" ? source : source.url, "근거 출처"), node("br"));
  const technical = node("details", null, "detail-section");
  technical.append(node("summary", "기술적 판정 정보"), node("pre", `유형: ${f.type}\n상태: ${f.status}\n엔진: ${f.engine}\n근거 등급: ${f.evidence_grade}\n신뢰도 지표: ${f.confidence} (확률 아님)\n실행 ID: ${f.run_id}`, "technical"));
  technical.append(node("p", f.detail, "technical"));
  area.append(technical);
  const form = node("form", null, "detail-section");
  form.append(node("h3", "담당 변호사 판단"));
  const select = node("select");
  select.setAttribute("aria-label", "담당 변호사 판단");
  for (const status of ["NEEDS_REVIEW", "ACCEPTED", "FALSE_POSITIVE", "RESOLVED"]) {
    const option = node("option", label(status));
    option.value = status;
    select.append(option);
  }
  select.value = f.review_status;
  const note = node("textarea");
  note.value = f.review_note;
  note.rows = 4;
  note.placeholder = "검토 의견 및 조치 내용";
  note.setAttribute("aria-label", "검토 의견");
  const save = node("button", "판단 저장", "primary");
  save.type = "submit";
  form.append(select, note, save);
  form.onsubmit = action(async event => {
    event.preventDefault();
    save.disabled = true;
    try {
      const updated = await api(`/findings/${f.id}/review`, {
        method: "PATCH",
        body: {
          review_status: select.value,
          note: note.value
        }
      });
      state.findings = state.findings.map(item => item.id === f.id ? updated : item);
      renderSummary();
      renderFindings();
      toast("판단을 저장했습니다.");
    } finally {
      save.disabled = false;
    }
  });
  area.append(form);
  workflowUI.enhanceFinding(f, form, area).catch(e => toast(e.message));
}
async function loadReports() {
  const id = state.project.id;
  const reports = await api(`/projects/${id}/reports`);
  if (state.project?.id !== id) return;
  $("reportList").replaceChildren();
  if (!reports.length) empty($("reportList"), "생성된 보고서가 없습니다.");
  for (const report of reports) {
    const row = node("article", null, "row-item");
    row.append(node("p", `${dateText(report.created_at)} · 실행 ${report.run_id.slice(0,8)}`));
    const links = node("div", null, "report-links");
    for (const [fmt, artifact] of Object.entries(report.artifacts || {})) {
      if (artifact.download) {
        const a = node("a", fmt.toUpperCase(), "button");
        a.href = artifact.download;
        links.append(a);
      } else if (artifact.error) links.append(node("span", `${fmt}: 생성 실패`, "error"));
    }
    row.append(links);
    reportWorkbench.decorate(report, row);
    $("reportList").append(row);
  }
}
async function createReport() {
  return reportWorkbench.create();
}
async function loadAudit() {
  const id = state.project?.id;
  if (!id) return;
  const data = await api(`/projects/${id}/audit`);
  if (id !== state.project?.id) return;
  $("audit").replaceChildren();
  for (const e of data.events) {
    const row = node("article", null, "row-item");
    const title = {
      USER_OVERRIDE: "사용자 변경",
      DOCUMENT_UPLOADED: "자료 등록",
      REPORT_GENERATED: "보고서 생성",
      EXPORT: "자료 내려받기",
      VERIFICATION_STARTED: "검증 시작",
      VERIFICATION_COMPLETED: "검증 완료"
    } [e.event_type] || e.event_type;
    row.append(node("strong", title), node("div", `${dateText(e.created_at)} · ${e.actor}`, "row-meta"));
    const details = node("details");
    details.append(node("summary", "기록 상세"), node("pre", JSON.stringify(e.payload, null, 2), "technical"));
    row.append(details);
    $("audit").append(row);
  }
  if (!data.events.length) empty($("audit"), "활동 기록이 없습니다.");
}
document.querySelectorAll("[data-close]").forEach(el => el.onclick = () => el.closest("dialog").close());
document.querySelectorAll("[data-tab]").forEach(el => el.onclick = () => switchTab(el.dataset.tab));
$("menuButton").onclick = () => $("sidebar").classList.toggle("open");
$("projectSearch").oninput = renderProjects;
for (const id of ["newProjectBtn", "emptyCreate"]) $(id).onclick = action(() => editProject(true));
for (const id of ["editProject", "editIssues"]) $(id).onclick = action(() => editProject());
$("projectForm").onsubmit = saveProject;
$("scopeFilter").onchange = renderDocuments;
$("selectAll").onchange = () => {
  for (const d of filteredDocuments())
    if ($("selectAll").checked) state.selected.add(d.id);
    else state.selected.delete(d.id);
  renderDocuments();
};
$("bulkExclude").onclick = action(() => setScope([...state.selected], false));
$("bulkInclude").onclick = action(() => setScope([...state.selected], true));
$("fileInput").onchange = action(e => upload([...e.target.files]));
$("dropArea").ondragover = e => {
  e.preventDefault();
  e.currentTarget.classList.add("dragging");
};
$("dropArea").ondragleave = e => e.currentTarget.classList.remove("dragging");
$("dropArea").ondrop = action(async e => {
  e.preventDefault();
  e.currentTarget.classList.remove("dragging");
  await upload([...e.dataTransfer.files]);
});
$("documentForm").onsubmit = action(async e => {
  e.preventDefault();
  await api(`/documents/${state.editDocumentId}`, {
    method: "PATCH",
    body: {...Object.fromEntries(new FormData(e.currentTarget)), submitted_on:e.currentTarget.elements.submitted_on.value || null}
  });
  $("documentDialog").close();
  await refreshScope();
});
for (const id of ["verifyBtn", "reverify"]) $(id).onclick = action(verify);
for (const id of ["findingSearch", "reviewFilter", "severityFilter"]) $(id).addEventListener("input", renderFindings);
$("reportBtn").onclick = () => switchTab("reports");
$("createReport").onclick = action(createReport);
$("refreshAudit").onclick = action(loadAudit);
$("prevPage").onclick = action(async () => {
  state.page--;
  await renderPage();
});
$("nextPage").onclick = action(async () => {
  state.page++;
  await renderPage();
});
$("settingsButton").onclick = action(async () => {
  const data = await api("/diagnostics");
  $("settingsContent").replaceChildren(node("p", data.note));
  for (const [name, capability] of Object.entries(data.capabilities)) {
    const row = node("div", null, "row-item");
    row.append(node("strong", name), node("pre", JSON.stringify(capability, null, 2), "technical"));
    $("settingsContent").append(row);
  }
  $("settingsDialog").showModal();
});
$("calculationForm").onsubmit = action(async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(e.currentTarget));
  data.inclusive = e.currentTarget.elements.inclusive.checked;
  const result = await api("/calculations/interest", {
    method: "POST",
    body: data
  });
  $("calculationResult").replaceChildren(node("h3", `이자 ${Number(result.interest).toLocaleString("ko-KR")}원`), node("p", `${result.days}일 · 합계 ${Number(result.total).toLocaleString("ko-KR")}원`), node("p", result.formula, "technical"), node("p", "연 365일 기준 단리 계산. 적용 이율·기간 및 초일 산입 여부는 담당 변호사가 확정합니다.", "muted"));
});
async function init() {
  icons();
  try {
    const health = await api("/health");
    const identity = await operationsUI.refreshIdentity();
    $("connection").textContent = `${identity.authentication === "local" ? "로컬" : "조직"} 작업 공간 · v${health.version}`;
    await loadProjects();
    const id = localStorage.getItem("acas-project");
    if (state.projects.length) await openProject(state.projects.some(p => p.id === id) ? id : state.projects[0].id);
  } catch (error) {
    $("connection").textContent = "연결 확인 필요";
    toast(error.message);
  }
}
workflowUI.init();
operationsUI.init();
calculationWorkbench.init();
init();
