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
  pollError: null,
  progressSeen: null,
  editing: null,
  creationKey: null,
  viewing: null,
  page: 1,
  pages: [],
  uploadBatch: null
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
  const authVersion = operationsUI.authVersion?.() || 0;
  const {interactiveAuth = true, ...request} = options;
  const headers = {
    ...options.headers
  };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const requestOptions = {
    ...request,
    body: options.body,
    headers,
    credentials: "same-origin"
  };
  let {response, data} = await send(path, requestOptions);
  if (response.status === 401) {
    if ((operationsUI.authVersion?.() || 0) !== authVersion) {
      ({response, data} = await send(path, requestOptions));
    } else if (interactiveAuth) {
      await operationsUI.authenticate();
      ({response, data} = await send(path, requestOptions));
    }
  }
  if (!response.ok) throw requestError(
    typeof data?.detail === "string" ? data.detail : data?.detail?.message || `서버가 요청을 처리하지 못했습니다 (HTTP ${response.status}).`,
    response.status === 401 ? "AUTH_REQUIRED" : data?.detail?.code || "HTTP_ERROR", {
      status: response.status,
      requestId: response.headers.get("X-Request-ID") || data?.detail?.request_id,
      uncertain: response.status >= 500 || response.status === 408
    });
  return data;
}

function requestError(message, code, details = {}) {
  return Object.assign(new Error(message), {code, ...details});
}

// 서버가 응답하지 못한 경우와 서버가 오류를 돌려준 경우를 구분한다.
// 브라우저는 전자를 "Failed to fetch" 한 줄로만 알려 주므로, 그대로 보여 주면
// 무엇을 확인해야 하는지 알 수 없다.
const API_TIMEOUT_MS = 180000;

async function send(path, requestOptions) {
  const {timeoutMs = API_TIMEOUT_MS, ...fetchOptions} = requestOptions;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`/api${path}`, {...fetchOptions, signal: controller.signal});
    const data = response.status === 204 ? null : await response.json().catch(error => {
      if (controller.signal.aborted) throw error;
      if (response.ok) throw requestError("서버의 응답 내용을 확인하지 못했습니다. 등록 내역을 다시 확인하세요.", "INVALID_RESPONSE", {
        status: response.status, requestId: response.headers.get("X-Request-ID"), uncertain: true
      });
      return null;
    });
    return {response, data};
  } catch (error) {
    if (typeof error.code === "string") throw error;
    if (error?.name === "AbortError") {
      throw requestError(`서버가 ${Math.round(timeoutMs / 1000)}초 안에 응답하지 않았습니다. 처리 여부를 다시 확인하세요.`, "TIMEOUT", {uncertain: true});
    }
    throw requestError(navigator.onLine === false
      ? "기기가 인터넷에 연결되어 있지 않습니다. 연결 후 등록 내역을 확인하세요."
      : "서버와 연결되지 않았거나 응답이 끊겼습니다. 잠시 후 처리 여부를 확인하세요.", "NETWORK_ERROR", {uncertain: true});
  } finally {
    clearTimeout(timer);
  }
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
    b.dataset.projectId = p.id;
    if (p.id === state.opening) b.setAttribute("aria-busy", "true");
    b.append(node("small", `${p.case_number||"사건번호 미지정"} · 자료 ${p.document_count}개`));
    $("projectList").append(b);
  }
}
// 누른 즉시 어느 프로젝트를 여는 중인지 보여 준다. 서버 응답을 기다리는 동안
// 화면이 그대로면 클릭이 먹지 않은 것처럼 보인다.
function markOpening(id) {
  state.opening = id;
  for (const b of $("projectList").querySelectorAll("button[data-project-id]")) {
    if (b.dataset.projectId === id) b.setAttribute("aria-busy", "true");
    else b.removeAttribute("aria-busy");
  }
}

async function openProject(id) {
  clearTimeout(state.timer);
  const generation = ++state.generation;
  state.selected.clear();
  markOpening(id);
  let p, docs, runs;
  try {
    [p, docs, runs] = await Promise.all([
      api(`/projects/${id}`), api(`/projects/${id}/documents`), api(`/projects/${id}/runs?limit=1`)]);
  } catch (error) {
    if (generation === state.generation) markOpening(null);
    throw requestError(`프로젝트를 열지 못했습니다: ${error.message}`, error.code, {status: error.status});
  }
  if (generation !== state.generation) return;
  markOpening(null);
  state.project = p;
  document.dispatchEvent(new Event("acas-project-changed"));
  state.documents = docs;
  state.run = runs[0] || null;
  state.pollError = null;
  state.progressSeen = null;
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
  const progressIssue = state.run && state.pollError?.runId === state.run.id;
  $("verifyBtn").disabled = !!busy || !!state.uploadBatch?.busy || !state.documents.some(d => d.included_in_verification);
  $("reverify").disabled = $("verifyBtn").disabled;
  $("progress").hidden = !busy && !progressIssue;
  if (busy || progressIssue) {
    const percent = Math.round(state.run.progress * (state.run.progress <= 1 ? 100 : 1));
    $("progressText").textContent = state.run.stage_message || label(state.run.state);
    $("progressPercent").textContent = `${percent}%`;
    $("progressBar").value = percent;
    renderProgressNotice();
  }
  renderProjects();
  renderDocuments();
  renderUploadStatus();
  renderSummary();
  renderIssues();
  renderTimeline();
  operationsUI.renderJobControls();
  projectTools.renderControls();
  $("reportScope").textContent = state.run ? `${dateText(state.run.started_at)} · 자료 ${state.run.document_ids.length}개 · ${label(state.run.state)}${$("staleNotice").hidden?"":" · 변경 전 자료 기준"}` : "검증 결과가 없습니다.";
  $("createReport").disabled = !["COMPLETED","PARTIAL_COMPLETED"].includes(state.run?.state);
}

function renderSummary() {
  $("summary").replaceChildren();
  let aiStatus = "미분석";
  let fakeCaseCount = 0, unconfirmedCount = 0;
  const docs = state.result?.documents || [];
  for (const d of docs) {
    if (d.ai_detector_result?.verdict === "AI_FULL_GENERATION_LIKELY") {
      aiStatus = "AI 전체 작성 의심";
    } else if (d.ai_detector_result?.verdict === "AI_PARTIAL_GENERATION" && aiStatus !== "AI 전체 작성 의심") {
      aiStatus = "일부 AI 작성";
    } else if (d.ai_detector_result?.verdict === "HUMAN_AUTHORED_LIKELY" && aiStatus === "미분석") {
      aiStatus = "인간 작성 유력";
    }
    // 확인하지 못한 인용과 성립 불가한 인용을 한 숫자에 섞지 않는다.
    // 실재하는 판례가 "가짜"로 집계되면 그 서면을 쓴 변호사에게 실제 손해가 간다.
    for (const row of d.ai_hallucination_table || []) {
      if (row.basis === "FABRICATION_SUSPECTED") fakeCaseCount += 1;
      else unconfirmedCount += 1;
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
    ["성립 불가 인용", state.run ? `${fakeCaseCount}건` : "—"],
    ["공식 DB 미확인 인용", state.run ? `${unconfirmedCount}건` : "—"],
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

// 사유는 접어 두지 않는다. 판정만 보이고 이유가 숨어 있으면 무엇을 고쳐야
// 하는지 한 번 더 눌러야 알 수 있다. 차단 사유와 검토 사유는 대응이 달라 나눈다.
function renderGateReasons(gate) {
  const groups = [
    ["배포 차단 사유", gate.hard_block_reasons || [], "gate-group-block"],
    ["사람 검토 사유", gate.review_reasons || [], "gate-group-review"]
  ].filter(([, reasons]) => reasons.length);
  if (!groups.length) return;
  const total = groups.reduce((sum, [, reasons]) => sum + reasons.length, 0);
  const section = node("section", null, `gate-reasons gate-${String(gate.release_gate).toLowerCase()}`);
  section.setAttribute("aria-label", "배포가능 판정 사유");
  section.append(node("h2", `${GATE_LABELS[gate.release_gate] || gate.release_gate} — 사유 ${total}건`));
  for (const [title, reasons, cls] of groups) {
    const group = node("div", null, `gate-group ${cls}`);
    group.append(node("h3", `${title} ${reasons.length}건`));
    const list = node("ol");
    for (const reason of reasons) list.append(node("li", friendlyText(reason)));
    group.append(list);
    section.append(group);
  }
  if (gate.risk_index_note) section.append(node("p", gate.risk_index_note, "gate-note"));
  $("summary").append(section);
}

const PROVIDER_NAMES = {openai: "OpenAI", anthropic: "Anthropic", gemini: "Gemini"};

function authorshipVerdict(verdict) {
  return {
    AI_FULL_GENERATION_LIKELY: ["AI 임의 전체 작성 유력", "badge CRITICAL"],
    AI_PARTIAL_GENERATION: ["일부 AI 작성·인용 내용 확인", "badge HIGH"],
    HUMAN_AUTHORED_LIKELY: ["인간(변호사/당사자) 작성 유력", "badge VERIFIED"]
  }[verdict] || ["판단 보류", "badge INFO"];
}

// 교차검증에 참여한 모델마다 결론·점수·설명을 모두 보인다. 응답하지 못한 모델은 사유와 함께 둔다.
function modelOpinions(opinions, failures) {
  const box = node("div", null, "model-opinions");
  box.append(node("h4", `모델별 판정 (${opinions.length}개 응답${failures.length ? ` · ${failures.length}개 불참` : ""})`));
  for (const o of opinions) {
    const [verdictLabel, badgeClass] = authorshipVerdict(o.verdict);
    const block = node("div", null, "model-opinion");
    const head = node("div", null, "model-opinion-head");
    head.append(node("strong", PROVIDER_NAMES[o.provider] || o.provider), node("span", verdictLabel, badgeClass),
                node("small", `점수 ${Math.round((o.score || 0) * 100)}%${o.model ? ` · ${o.model}` : ""}`, "muted"));
    block.append(head);
    const list = node("ul", null, "reason-list");
    for (const r of o.reasons || []) list.append(node("li", r));
    if (!(o.reasons || []).length) list.append(node("li", "설명 없음", "muted"));
    block.append(list);
    box.append(block);
  }
  for (const [provider, why] of failures) {
    const block = node("div", null, "model-opinion model-opinion-failed");
    const head = node("div", null, "model-opinion-head");
    head.append(node("strong", PROVIDER_NAMES[provider] || provider), node("span", "응답 없음", "badge INFO"));
    block.append(head, node("p", why, "muted"));
    box.append(block);
  }
  return box;
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

function renderUploadStatus() {
  let area = $("uploadStatus");
  if (!area) {
    area = node("section", null, "upload-status");
    area.id = "uploadStatus";
    area.setAttribute("aria-label", "파일 등록 상태");
    area.setAttribute("aria-live", "polite");
    $("dropArea").before(area);
  }
  const batch = state.uploadBatch;
  $("fileInput").disabled = !!batch?.busy;
  document.querySelector('label[for="fileInput"]').setAttribute("aria-disabled", String(!!batch?.busy));
  area.hidden = !batch || batch.projectId !== state.project?.id;
  if (area.hidden) return;
  area.replaceChildren();
  const registered = batch.entries.filter(entry => entry.status === "REGISTERED").length;
  const heading = node("div", null, "upload-heading");
  heading.append(node("strong", `${batch.busy ? "파일 등록 중" : "파일 등록 결과"} · ${registered}/${batch.entries.length}개 확인`));
  if (!batch.busy && batch.entries.some(entry => entry.status === "UNCONFIRMED")) {
    heading.append(iconButton("refresh-cw", "등록 내역 다시 확인", async () => {
      await reconcileUploads(batch);
      if (state.project?.id === batch.projectId) await refreshScope();
      renderUploadStatus();
    }));
  }
  area.append(heading);
  const names = {WAITING: "대기", READING: "파일 읽는 중", SENDING: "전송 중", REGISTERED: "등록 완료", FAILED: "미등록", UNCONFIRMED: "등록 확인 필요"};
  for (const entry of batch.entries) {
    const row = node("div", null, "upload-result");
    row.append(node("span", entry.name, "upload-filename"), node("strong", names[entry.status], `upload-state ${entry.status.toLowerCase()}`));
    if (entry.error) {
      row.append(node("p", entry.error.message, "upload-message"));
      const technical = node("details", null, "upload-technical");
      const details = [entry.error.code, entry.error.status ? `HTTP ${entry.error.status}` : "", entry.error.requestId ? `문의 번호: ${entry.error.requestId}` : ""].filter(Boolean);
      technical.append(node("summary", "기술 정보"), node("p", details.join(" · ")));
      row.append(technical);
    }
    area.append(row);
  }
  if (batch.refreshError) area.append(node("p", `등록 내역 조회 실패: ${batch.refreshError}`, "error"));
  icons();
}

async function prepareUpload(file) {
  let bytes;
  try {
    bytes = await file.arrayBuffer();
    if (bytes.byteLength !== file.size) throw new Error("File changed");
  } catch (error) {
    throw requestError("기기에서 파일을 읽지 못했습니다. 파일을 기기에 내려받아 저장한 뒤 다시 선택하세요.", "FILE_READ_FAILED");
  }
  // A byte snapshot avoids re-reading a changed or unavailable cloud-backed file during fetch.
  const body = new Blob([bytes], {type: file.type || "application/octet-stream"});
  const sha256 = globalThis.crypto?.subtle
    ? Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("")
    : null;
  return {body, sha256};
}

async function reconcileUploads(batch) {
  try {
    const documents = await api(`/projects/${batch.projectId}/documents`, {timeoutMs: 15000});
    for (const entry of batch.entries) {
      if (entry.status === "UNCONFIRMED" && entry.sha256 && documents.some(document => document.sha256 === entry.sha256)) {
        entry.status = "REGISTERED";
        entry.error = null;
      }
    }
    batch.refreshError = null;
  } catch (error) {
    batch.refreshError = error.message;
  }
  renderUploadStatus();
}

async function upload(files) {
  const id = state.project?.id;
  if (!id || !files.length) return;
  if (state.uploadBatch?.busy) return toast("다른 파일의 등록이 진행 중입니다.");
  const batch = {projectId: id, busy: true, entries: files.map(file => ({name: file.name, status: "WAITING"}))};
  state.uploadBatch = batch;
  renderProject();
  try {
    for (const [index, file] of files.entries()) {
      const entry = batch.entries[index];
      try {
        entry.status = "READING";
        renderUploadStatus();
        const prepared = await prepareUpload(file);
        entry.sha256 = prepared.sha256;
        const form = new FormData();
        form.append("file", prepared.body, file.name);
        entry.status = "SENDING";
        renderUploadStatus();
        await api(`/projects/${id}/documents`, {method: "POST", body: form});
        entry.status = "REGISTERED";
      } catch (error) {
        entry.status = error.uncertain ? "UNCONFIRMED" : "FAILED";
        entry.error = error;
      }
      renderUploadStatus();
    }
    if (batch.entries.some(entry => entry.status === "UNCONFIRMED")) await reconcileUploads(batch);
    if (state.project?.id === id) {
      try { await refreshScope(); } catch (error) { batch.refreshError = error.message; }
    }
  } finally {
    batch.busy = false;
    $("fileInput").value = "";
    renderProject();
    const count = batch.entries.filter(entry => entry.status === "REGISTERED").length;
    toast(`${count}개 등록 확인${count < files.length ? " · 파일별 등록 상태를 확인하세요." : ""}`);
  }
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
    projectTools.refresh();
  } catch (error) {
    renderProject();
    throw error;
  }
}

function renderProgressNotice() {
  const run = state.run;
  if (!run) return;
  const signature = JSON.stringify([run.state, run.stage_message, run.progress]);
  if (state.progressSeen?.runId !== run.id || state.progressSeen.signature !== signature) {
    state.progressSeen = {runId: run.id, signature, at: Date.now()};
  }
  const seconds = Math.floor((Date.now() - state.progressSeen.at) / 1000);
  const error = state.pollError?.runId === run.id;
  const authRequired = error && state.pollError.authRequired;
  const unavailable = error && state.pollError.unavailable;
  const message = unavailable ? "이 검증에 접근할 수 없습니다. 프로젝트 삭제 또는 접근 권한 변경 여부를 확인하세요."
    : authRequired ? "로그인이 만료되어 결과 조회를 잠시 멈췄습니다. 다시 로그인하면 같은 검증의 진행 상태와 결과를 확인합니다."
    : error ? "서버 연결이 지연되어 진행 상태를 갱신하지 못했습니다. 자동으로 다시 연결 중입니다. 검증 작업이 중단된 것으로 확정된 것은 아닙니다."
    : seconds >= 60 ? `현재 단계의 진행 정보가 ${seconds}초 동안 변경되지 않았습니다. 서버 응답은 정상이며 작업 결과를 기다리고 있습니다. ` +
        "외부 법령·판례 조회 단계는 문서 한 건에 수 분이 걸릴 수 있습니다." : "";
  $("progressNotice").textContent = message;
  $("progressNotice").hidden = !message;
  if (unavailable) {
    $("progressNotice").append(button("프로젝트 목록", async () => {
      projectTools.clearProject(); await loadProjects();
      if (state.projects.length) await openProject(state.projects[0].id);
    }));
  }
  if (authRequired) {
    $("progress").hidden = false;
    const reason = state.pollError?.detail;
    if (reason && reason !== message) {
      $("progressNotice").append(node("span", `서버 안내: ${reason}`, "notice-reason"));
    }
    const login = button("다시 로그인", () => operationsUI.authenticate(), "resume-login");
    const icon = node("i"); icon.dataset.lucide = "log-in"; login.prepend(icon);
    $("progressNotice").append(login);
    icons();
  }
}

function resumeAuthenticatedRun() {
  if (state.pollError?.authRequired && state.pollError.runId === state.run?.id) {
    state.pollError = null;
    renderProgressNotice();
    pollRun(state.generation);
  }
}

const protectedRuns = new Map();
async function protectAnalysisSession(run) {
  if (!run || terminal(run)) return;
  const key = `${operationsUI.authVersion()}:${run.id}`;
  if (protectedRuns.has(key)) return;
  await api(`/verification-runs/${run.id}/session`, {method:"POST", timeoutMs:15000, interactiveAuth:false});
  protectedRuns.set(key, true);
}

const POLL_BASE_MS = 2000, POLL_MAX_MS = 20000;

// 연속 실패에 같은 간격으로 계속 두드리면, 서버가 느려진 바로 그 순간에
// 부하를 더한다. 실패가 이어지는 동안만 간격을 늘리고 성공하면 되돌린다.
function pollDelay() {
  const failures = state.pollFailures || 0;
  if (document.hidden) return 30000;
  return Math.min(POLL_MAX_MS, POLL_BASE_MS * 2 ** Math.min(failures, 4));
}

function pollRun(generation, delayMs = pollDelay()) {
  clearTimeout(state.timer);
  const runId = state.run?.id;
  if (!runId) return;
  state.timer = setTimeout(async () => {
    if (generation !== state.generation || state.run?.id !== runId) return;
    if (state.pollInFlight?.generation === generation && state.pollInFlight.runId === runId) return;
    const pending = {generation, runId};
    state.pollInFlight = pending;
    try {
      const run = await api(`/verification-runs/${runId}`, {timeoutMs: 15000, interactiveAuth: false});
      if (generation !== state.generation || state.run?.id !== runId) return;
      if (!run || run.id !== runId || typeof run.state !== "string") throw new Error("진행 상태 응답을 읽지 못했습니다");
      await protectAnalysisSession(run);
      if (generation !== state.generation || state.run?.id !== runId) return;
      state.pollError = null;
      state.pollFailures = 0;
      state.run = run;
      renderProject();
      if (terminal(run)) {
        await loadResults(generation, {interactiveAuth: false});
        toast(label(run.state));
      } else pollRun(generation);
    } catch (error) {
      if (generation !== state.generation || state.run?.id !== runId) return;
      const authRequired = error.status === 401 || error.code === "AUTH_REQUIRED";
      const unavailable = [403, 404].includes(error.status);
      // 서버가 알려준 사유를 함께 담는다. 화면이 고정 문구만 보여 주면 원인이
      // 쿠키 문제인지 만료인지 구분할 수 없고, 사용자도 무엇을 확인해야 할지
      // 알 수 없다. 특히 모바일에서는 개발자도구로 응답을 볼 수 없다.
      state.pollError = {runId, authRequired, unavailable, detail: error.message || ""};
      if (!authRequired && !unavailable) state.pollFailures = (state.pollFailures || 0) + 1;
      renderProject();
      if (!authRequired && !unavailable) pollRun(generation);
    } finally {
      if (state.pollInFlight === pending) state.pollInFlight = null;
    }
  }, delayMs);
}
async function loadResults(generation, options = {}) {
  if (!state.run) {
    renderFindings();
    await workflowUI.refresh(options);
    return;
  }
  const result = await api(`/verification-runs/${state.run.id}/result`, options);
  const findings = await api(`/projects/${state.project.id}/findings?run_id=${state.run.id}`, options);
  if (generation !== state.generation) return;
  state.result = result;
  state.findings = findings;
  await workflowUI.refresh(options);
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
      const [verdictLabel, badgeClass] = authorshipVerdict(res.verdict);
      const item = node("div", null, "card-item");
      item.append(
        node("div", `${res.filename}: `),
        node("span", verdictLabel, badgeClass),
        node("small", ` (신뢰도: ${Math.round((res.score || 0) * 100)}%)`, "muted")
      );
      const opinions = res.signals?.llm_opinions || [];
      const failures = Object.entries(res.signals?.llm_failures || {});
      // 모델별 설명은 모델 블록에서 모두 보이므로 요약에서는 뺀다. 예전 결과처럼
      // 모델별 기록이 없으면 근거를 자르지 않고 모두 보인다.
      const summary = (res.reasons || []).filter(r => !opinions.length || !/^\[[a-z]+\] /.test(r));
      if (summary.length) {
        const reasonList = node("ul", null, "reason-list");
        for (const r of summary) reasonList.append(node("li", r));
        item.append(reasonList);
      }
      if (opinions.length || failures.length) item.append(modelOpinions(opinions, failures));
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
function renderDiagnostics(data) {
  const capabilities = data.capabilities || {};
  const ocr = capabilities.ocr || {};
  const ready = ocr.ready === true;
  const reasons = {
    NOT_INSTALLED: "글자 인식 프로그램을 찾지 못했습니다. 서버에 Tesseract와 한국어·영어 언어팩을 설치하고 재시작해야 합니다.",
    PYTHON_DEPENDENCY_MISSING: "글자 인식에 필요한 Python 구성 요소가 없습니다. 배포 이미지의 의존성을 확인하세요.",
    ENGINE_FAILED: "글자 인식 프로그램을 실행하지 못했습니다. 실행 권한과 서버 설치 상태를 확인하세요.",
    LANGUAGES_UNAVAILABLE: "언어팩 목록을 확인하지 못했습니다. 언어팩이 정상이라는 뜻은 아닙니다.",
    LANGUAGES_MISSING: `필요한 인식 언어가 준비되지 않았습니다: ${(ocr.missing_languages || ocr.required_languages || []).join(", ")}`,
    KOREAN_TEST_FONT_MISSING: "자체 점검에 필요한 한국어 글꼴이 없습니다. 배포 이미지에 fonts-nanum을 설치하세요.",
    SCANNED_PDF_RECOGNITION_FAILED: "한국어 시험 PDF의 글자 또는 위치를 확인하지 못했습니다. OCR과 PDF 변환 구성을 점검하세요.",
    SCANNED_PDF_CHECK_FAILED: "한국어 시험 PDF 점검을 완료하지 못했습니다. 서버의 OCR·PDF 구성 요소를 확인하세요."
  };
  const content = $("settingsContent");
  content.replaceChildren(node("p", data.note, "diagnostic-summary"));
  function row(title, status, detail, tone = "LOW") {
    const section = node("section", null, "diagnostic-row");
    const heading = node("div", null, "diagnostic-heading");
    heading.append(node("h3", title), node("span", status, `badge ${tone}`));
    section.append(heading, node("p", detail));
    content.append(section);
  }
  row("스캔 문서 읽기", ready ? "준비 완료" : "점검 필요", ready
    ? "한국어 시험 PDF의 본문과 페이지 위치를 인식했습니다. 실제 문서의 인식 정확도는 별도 확인이 필요합니다."
    : reasons[ocr.self_test?.reason] || reasons[ocr.status] || "OCR 준비 상태를 확인하지 못했습니다.", ready ? "LOW" : "HIGH");
  row("PDF 이미지 변환", capabilities.rasterizer?.available ? "사용 가능" : "사용 불가",
    capabilities.rasterizer?.available ? "PDF 페이지를 이미지로 변환할 수 있습니다. 글자 인식 준비 상태와는 별개입니다."
      : "스캔 PDF를 처리하려면 서버의 pypdfium2 설치를 확인해야 합니다.", capabilities.rasterizer?.available ? "LOW" : "HIGH");
  const dialect = capabilities.database?.dialect;
  const sessionPolicy = capabilities.browser_session;
  if (sessionPolicy) row("로그인 유지", "사용 중 자동 연장",
    `일반 미사용 ${sessionPolicy.idle_hours}시간 · 일반 로그인 최대 ${sessionPolicy.absolute_hours}시간. 비밀번호 로그인은 분석 시작부터 최대 ${sessionPolicy.analysis_protection_hours || 168}시간 보호하고, 종료 후 ${sessionPolicy.result_review_hours || 24}시간 결과 확인 시간을 둡니다. 로그아웃·비밀번호 변경·계정 중지는 즉시 적용하며 토큰·SSO 원본 만료는 별도입니다.`);
  // 저장소가 재시작을 견디는지. 잘못된 배포는 화면상 정상으로 보이므로
  // 무엇이 사라지는지와 조치를 함께 적는다.
  const durability = capabilities.durability;
  const atRisk = durability?.verdict === "AT_RISK";
  const storageLabel = dialect === "postgresql" ? "PostgreSQL" : dialect === "sqlite" ? "SQLite" : "확인 필요";
  row("자료 저장소", atRisk ? `${storageLabel} · 보존되지 않음` : storageLabel,
    atRisk
      ? `재시작·재배포하면 ${(durability.at_risk || []).join(", ")}이(가) 사라집니다. `
        + `데이터베이스: ${durability.database?.reason || "확인 필요"} `
        + `업로드 원본: ${durability.storage?.reason || "확인 필요"} ${durability.remedy || ""}`
      : durability
        ? `${durability.database?.reason || ""} ${durability.storage?.reason || ""} ${durability.note || ""}`
        : "업로드 원본의 영구 저장 위치와 백업을 확인해야 합니다.",
    atRisk ? "HIGH" : "LOW");
  const crypto = capabilities.storage_encryption;
  if (crypto) row("저장 시 암호화",
    crypto.configured === false ? "키 설정 오류" : crypto.enabled ? "적용" : "미적용",
    crypto.note, crypto.enabled && crypto.configured !== false ? "LOW" : "HIGH");
  const worker = capabilities.worker || {};
  const resolved = {inprocess: "서버 내부 처리", celery: "별도 작업 서버"}[worker.mode];
  row("검증 작업 실행", {auto: "자동 선택", inprocess: "서버 내부 처리", celery: "별도 작업 서버"}[capabilities.worker_mode] || "확인 필요",
    (capabilities.worker_mode === "auto" && resolved ? `현재 ${resolved}로 동작합니다. 자동 선택 자체는 오류가 아닙니다. `
      : capabilities.worker_mode === "auto" ? "작업 서버 연결 설정에 따라 실행 방식을 선택합니다. 자동 선택 자체는 오류가 아닙니다. " : "")
    + (worker.concurrency ? `동시에 ${worker.concurrency}건까지 실행합니다. ` : "")
    + (worker.shares_api_process ? "검증이 화면 응답과 같은 서버 자원을 씁니다. 동시 실행을 늘리면 화면이 느려집니다. "
      : worker.shares_api_process === false ? "검증이 별도 서버에서 실행되어 화면 응답에 영향을 주지 않습니다. " : "")
    + "실제 작업의 진행 및 오류는 작업 기록에서 확인합니다.");
  const llm = capabilities.llm;
  if (llm) row("AI 검토 공급자",
    llm.usable_count ? `${llm.usable_count}곳 · 교차검증 ${{all: "전체", auto: "선택적", off: "안 함"}[llm.cross_check] || llm.cross_check}` : "없음",
    (llm.providers || []).map(p => `${p.name}(${p.model})${p.key_present ? "" : " 키 없음"}`).join(", ")
      + " · " + llm.note + (llm.cross_check_note ? " " + llm.cross_check_note : ""),
    llm.usable_count ? "LOW" : "HIGH");
  row("법률정보 조회", capabilities.network_allowed ? "외부 연결 허용" : "외부 연결 차단",
    capabilities.source_keys_present?.law_go_kr ? "국가법령정보센터 조회 정보가 설정되어 있습니다. 실제 조회 성공 여부는 검증 결과의 출처 기록에서 확인합니다."
      : "국가법령정보센터 조회 정보가 설정되지 않았습니다. 공식 출처를 확인하지 못한 항목은 미검증으로 남습니다.");
  const technical = node("details", null, "diagnostic-technical");
  technical.append(node("summary", "기술 진단 정보"), node("pre", JSON.stringify(capabilities, null, 2), "technical"));
  content.append(technical);
}

$("settingsButton").onclick = action(async () => {
  const data = await api("/diagnostics");
  renderDiagnostics(data);
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
// 화면 구성요소는 각각 별도 파일이다. 배포 중이거나 캐시가 어긋나면 그중
// 하나가 로드되지 않을 수 있고, 그때 남는 것은 "operationsUI is not defined"
// 같은 문구와 빈 프로젝트 목록이다. 자료가 사라진 것처럼 보이지만 실제로는
// 조회를 시작하지도 못한 상태다. 그 둘을 구분해 알린다.
// 각 구성요소는 최상위 const로 선언된다. const 바인딩은 globalThis의 속성이
// 아니므로 globalThis[name]으로 찾으면 정상일 때도 "없음"이 된다.
// 식별자에 직접 typeof를 쓴다. 선언되지 않은 식별자에도 typeof는 안전하다.
function missingModules() {
  return [
    [typeof operationsUI, "로그인·계정"],
    [typeof workflowUI, "검토 작업"],
    [typeof projectTools, "프로젝트 관리"],
    [typeof calculationWorkbench, "금액 계산"],
  ].filter(([kind]) => kind === "undefined").map(([, label]) => label);
}

function showLoadFailure(missing) {
  $("connection").textContent = "화면 구성요소 미로드";
  const panel = $("emptyState");
  if (panel) {
    panel.hidden = false;
    panel.replaceChildren(
      node("h1", "화면을 완전히 불러오지 못했습니다"),
      node("p", `${missing.join(", ")} 구성요소가 로드되지 않았습니다. 배포 직후이거나 ` +
        "브라우저 캐시가 어긋났을 때 생깁니다."),
      node("p", "저장된 프로젝트와 자료는 영향을 받지 않습니다. 조회를 시작하지 못한 상태입니다.", "muted"),
      button("새로고침", () => location.reload(), "primary")
    );
  }
  toast(`화면 구성요소를 불러오지 못했습니다(${missing.join(", ")}). 새로고침하세요.`);
}

async function init() {
  icons();
  const missing = missingModules();
  if (missing.length) return showLoadFailure(missing);
  try {
    const health = await api("/health");
    const identity = await operationsUI.refreshIdentity();
    projectTools.start();
    $("connection").textContent = `${identity.authentication === "local" ? "로컬" : "조직"} 작업 공간 · v${health.version}`;
    await loadProjects();
    const id = localStorage.getItem("acas-project");
    if (state.projects.length) await openProject(state.projects.some(p => p.id === id) ? id : state.projects[0].id);
  } catch (error) {
    $("connection").textContent = "연결 확인 필요";
    toast(error.message);
  }
}
if (!missingModules().length) {
  workflowUI.init();
  operationsUI.init();
  projectTools.init();
  calculationWorkbench.init();
}
init();
