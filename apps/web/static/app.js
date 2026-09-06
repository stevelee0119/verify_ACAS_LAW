/* 법률문서 검증 플랫폼 프런트엔드.
   문서 내용은 항상 텍스트로만 렌더링한다(innerHTML 미사용, XSS 방어). */
"use strict";

const API = "/api";
const state = {
  projects: [],
  projectId: null,
  documents: [],
  findings: [],
  run: null,
  filters: new Set(),
  viewerDocId: null,
};

/* 제19.3장 필터 */
const FILTER_GROUPS = [
  { key: "CASE", label: "판례 오류", types: ["CASE_NOT_FOUND", "CASE_METADATA_MISMATCH", "CASE_QUOTE_MISMATCH", "CASE_HOLDING_DISTORTION", "CASE_CITATION_ERROR"] },
  { key: "LAW", label: "법령 오류", types: ["LAW_CITATION_ERROR", "TEMPORAL_LAW_MISMATCH"] },
  { key: "ACADEMIC", label: "학술자료", types: ["ACADEMIC_CITATION_ERROR"] },
  { key: "LOGIC", label: "사실관계·논리모순", types: ["FACT_CONTRADICTION", "CROSS_DOCUMENT_CONTRADICTION", "TIMELINE_CONTRADICTION", "ARITHMETIC_MISMATCH"] },
  { key: "AI", label: "AI 작성 의심", types: ["AI_AUTHORSHIP_LIKELY", "STYLE_SHIFT", "MODEL_ATTRIBUTION_SIGNAL"] },
  { key: "FORGERY", label: "문서 위·변조", types: ["METADATA_ANOMALY", "SIGNATURE_INVALID", "MODIFIED_AFTER_SIGNATURE", "PAGE_STRUCTURE_OUTLIER", "PRIOR_VERSION_RECOVERABLE", "CROPPED_IMAGE_RESIDUE"] },
  { key: "HIDDEN", label: "숨은 텍스트", types: ["HIDDEN_TEXT_MISMATCH", "OCR_LAYER_MISMATCH", "HIDDEN_INSTRUCTION", "HIDDEN_SHEET_OR_ROW", "REDACTION_FAILURE", "DELETED_TEXT_RECOVERABLE"] },
  { key: "INJECTION", label: "Prompt Injection·메타 지시어", types: ["PROMPT_INJECTION_SUSPECTED", "META_INSTRUCTION", "SYSTEM_OVERRIDE_ATTEMPT", "ROLE_OVERRIDE_ATTEMPT", "VERIFICATION_SUPPRESSION", "OUTPUT_MANIPULATION_ATTEMPT", "ENCODED_INSTRUCTION", "UNICODE_SMUGGLING", "OCR_LAYER_INJECTION", "METADATA_INJECTION", "MULTIMODAL_INJECTION", "TOOL_MANIPULATION_ATTEMPT", "DATA_EXFILTRATION_INSTRUCTION"] },
  { key: "UNVERIFIED", label: "미검증 항목", statuses: ["UNVERIFIED", "SKIPPED"] },
];

const REVIEW_OPTIONS = ["NEEDS_REVIEW", "ACCEPTED", "FALSE_POSITIVE", "RESOLVED"];

/* ---------- 유틸 ---------- */
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => box.classList.add("hidden"), 4200);
}
async function api(path, options = {}) {
  const response = await fetch(API + path, options);
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response.text();
}
const jsonPost = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

/* ---------- 부팅 ---------- */
async function boot() {
  try {
    const runtime = await api("/settings/runtime");
    const providers = runtime.available_providers.length ? runtime.available_providers.join(", ") : "없음(결정론적 검증만 수행)";
    $("#runtime").textContent =
      `v${runtime.version} · rule ${runtime.rule_version} · 기본정책 ${runtime.default_external_ai_policy} · 사용가능 모델: ${providers}`;
  } catch (err) { $("#runtime").textContent = "런타임 정보를 불러오지 못했습니다."; }
  await loadProjects();
  bindEvents();
}

function bindEvents() {
  $("#newProjectBtn").onclick = () => $("#projectForm").classList.toggle("hidden");
  $("#cancelProject").onclick = () => $("#projectForm").classList.add("hidden");
  $("#projectForm").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());
    Object.keys(payload).forEach((k) => { if (!payload[k]) delete payload[k]; });
    try {
      const project = await jsonPost("/projects", payload);
      event.target.reset();
      $("#projectForm").classList.add("hidden");
      await loadProjects();
      selectProject(project.id);
    } catch (err) { toast("생성 실패: " + err.message); }
  };
  $("#fileInput").onchange = async (event) => {
    for (const file of event.target.files) await uploadFile(file);
    event.target.value = "";
    await refreshProject();
  };
  $("#verifyBtn").onclick = runVerification;
  $("#reportBtn").onclick = createReport;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $("#tab-" + tab.dataset.tab).classList.add("active");
      if (tab.dataset.tab === "viewer") renderViewer();
      if (tab.dataset.tab === "audit") renderAudit();
    };
  });
  $("#showHidden").onchange = renderViewer;
  $("#viewerDoc").onchange = (e) => { state.viewerDocId = e.target.value; renderViewer(); };
}

/* ---------- 프로젝트 ---------- */
async function loadProjects() {
  state.projects = await api("/projects");
  const list = $("#projectList");
  list.replaceChildren();
  state.projects.forEach((project) => {
    const item = el("li", project.id === state.projectId ? "active" : "");
    item.appendChild(el("div", "name", project.name));
    item.appendChild(el("div", "sub", `${project.case_number || "사건번호 미기재"} · 문서 ${project.document_count}건`));
    item.onclick = () => selectProject(project.id);
    list.appendChild(item);
  });
}

async function selectProject(projectId) {
  state.projectId = projectId;
  state.run = null;
  state.viewerDocId = null;
  $("#emptyState").classList.add("hidden");
  $("#projectView").classList.remove("hidden");
  await loadProjects();
  await refreshProject();
}

async function refreshProject() {
  const project = state.projects.find((p) => p.id === state.projectId);
  if (!project) return;
  $("#projectTitle").textContent = project.name;
  $("#projectMeta").textContent =
    `사건번호 ${project.case_number || "-"} · ${project.court || "기관 미기재"} · 사건발생일 ${project.incident_date || "-"} · ` +
    `외부 AI 정책 ${project.external_ai_policy} · 프로파일 ${project.verification_profile}`;
  state.documents = await api(`/projects/${state.projectId}/documents`);
  renderDocuments();
  // 화면 재진입 시 최신 검증 결과를 복원한다
  try {
    const runs = await api(`/projects/${state.projectId}/runs?limit=1`);
    state.run = runs.length ? runs[0] : null;
  } catch (_) { state.run = null; }
  await loadFindings();
  await renderSources();
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  try {
    await api(`/projects/${state.projectId}/documents`, { method: "POST", body: form });
    toast(`업로드 완료: ${file.name}`);
  } catch (err) { toast(`업로드 실패(${file.name}): ${err.message}`); }
}

function renderDocuments() {
  const body = $("#docTable").querySelector("tbody");
  body.replaceChildren();
  state.documents.forEach((document_) => {
    const row = el("tr");
    row.appendChild(el("td", null, document_.filename));
    row.appendChild(el("td", "mono", document_.sha256.slice(0, 20) + "…"));
    row.appendChild(el("td", null, `${(document_.size_bytes / 1024).toFixed(1)} KB`));
    const status = el("td");
    status.appendChild(el("span", document_.quarantined ? "risk-CRITICAL" : "risk-NONE",
      document_.quarantined ? "QUARANTINED (자동 색인 제외)" : "정상"));
    row.appendChild(status);
    const actions = el("td");
    const verifyBtn = el("button", "btn small", "검증");
    verifyBtn.onclick = () => runVerification(document_.id);
    const guardBtn = el("button", "btn small", "발신 전 검사");
    guardBtn.onclick = () => outboundGuard(document_.id);
    actions.append(verifyBtn, guardBtn);
    row.appendChild(actions);
    body.appendChild(row);
  });
}

async function renderSources() {
  try {
    const data = await api("/settings/sources");
    const box = $("#sourceStatus");
    box.replaceChildren();
    box.appendChild(el("h3", null, "Source 상태"));
    const table = el("table", "table");
    const head = el("thead");
    const headRow = el("tr");
    ["Source", "구분", "상태", "비고"].forEach((h) => headRow.appendChild(el("th", null, h)));
    head.appendChild(headRow);
    table.appendChild(head);
    const body = el("tbody");
    data.adapters.forEach((adapter) => {
      const row = el("tr");
      row.appendChild(el("td", null, adapter.name));
      row.appendChild(el("td", null, adapter.kind));
      row.appendChild(el("td", adapter.status === "READY" ? "risk-NONE" : "risk-MEDIUM", adapter.status));
      row.appendChild(el("td", "sub", adapter.note || ""));
      body.appendChild(row);
    });
    table.appendChild(body);
    box.appendChild(table);
    box.appendChild(el("p", "sub", data.notice));
  } catch (_) {}
}

/* ---------- 검증 ---------- */
async function runVerification(documentId) {
  try {
    const path = typeof documentId === "string"
      ? `/documents/${documentId}/verify`
      : `/projects/${state.projectId}/verify`;
    const run = await jsonPost(path, {});
    state.run = run;
    if (run.reused) {
      toast("동일 문서·동일 설정의 기존 검증 결과를 재사용했습니다.");
      await afterRun(run.id);
      return;
    }
    $("#progress").classList.remove("hidden");
    followProgress(run.id);
  } catch (err) { toast("검증 실행 실패: " + err.message); }
}

function followProgress(runId) {
  const source = new EventSource(`${API}/verification-runs/${runId}/events`);
  source.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    $("#progressBar").style.width = `${Math.round((data.progress || 0) * 100)}%`;
    $("#progressText").textContent = `${data.state} · ${data.message || ""}`;
    if (data.finished) {
      source.close();
      setTimeout(() => $("#progress").classList.add("hidden"), 1200);
      await afterRun(runId);
    }
  };
  source.onerror = () => source.close();
}

async function afterRun(runId) {
  state.run = await api(`/verification-runs/${runId}`);
  state.documents = await api(`/projects/${state.projectId}/documents`);
  renderDocuments();
  renderScores();
  await loadFindings();
  renderTimeline();
  toast(`검증 ${state.run.state}`);
}

async function loadFindings() {
  if (!state.projectId) return;
  state.findings = await api(`/projects/${state.projectId}/findings`);
  renderFilters();
  renderFindings();
  renderScores();
  renderTimeline();
  renderAdvisory();
}

/* ---------- 대시보드 ---------- */
function renderScores() {
  const box = $("#scoreCards");
  box.replaceChildren();
  const run = state.run;
  const axes = (run && run.scores && run.scores.axes) || null;
  const counts = (run && run.scores && run.scores.severity_counts) || {};

  const add = (label, value, note, cls) => {
    const card = el("div", "card");
    card.appendChild(el("div", "label", label));
    card.appendChild(el("div", "value " + (cls || ""), value));
    if (note) card.appendChild(el("div", "note", note));
    box.appendChild(card);
  };

  add("문서", String(state.documents.length), "프로젝트 내 등록 문서");
  add("Finding", String(state.findings.length),
      `CRITICAL ${counts.CRITICAL || 0} · HIGH ${counts.HIGH || 0} · MEDIUM ${counts.MEDIUM || 0} · LOW ${counts.LOW || 0}`);
  if (!axes) { add("검증 상태", "미실행", "검증을 실행하십시오"); return; }

  add("Adversarial Manipulation Risk", axes.adversarial_manipulation_risk.risk,
      `탐지 ${axes.adversarial_manipulation_risk.issue_count}건`, "risk-" + axes.adversarial_manipulation_risk.risk);
  add("법률 인용 정확성", `${axes.legal_citation_accuracy.verified}/${axes.legal_citation_accuracy.citation_total}`,
      `미검증 ${axes.legal_citation_accuracy.unverified} · 오류 ${axes.legal_citation_accuracy.issue_count}`,
      "risk-" + axes.legal_citation_accuracy.risk);
  add("진정성 위험", axes.authenticity_risk.risk, `${axes.authenticity_risk.issue_count}건`, "risk-" + axes.authenticity_risk.risk);
  add("위·변조 위험", axes.forgery_risk.risk, axes.forgery_risk.note, "risk-" + axes.forgery_risk.risk);
  add("사실 신뢰성", axes.factual_reliability.risk, `모순 ${axes.factual_reliability.issue_count}건`,
      "risk-" + axes.factual_reliability.risk);
  const internal = axes.internal_consistency;
  add("내부·문서간 일관성",
      String(internal.cross_document_issues + internal.timeline_issues + internal.arithmetic_issues),
      `문서간 ${internal.cross_document_issues} · 시간 ${internal.timeline_issues} · 계산 ${internal.arithmetic_issues}`);
  add("AI 작성 가능성", (axes.ai_authorship.verdicts || []).join(", ") || "-", axes.ai_authorship.note);
  add("미검증", String(axes.unverified_ratio.unverified_items),
      `사용 불가 Source: ${(axes.unverified_ratio.unavailable_sources || []).join(", ") || "없음"}`);
}

/* ---------- Findings ---------- */
function renderFilters() {
  const box = $("#filters");
  box.replaceChildren();
  FILTER_GROUPS.forEach((group) => {
    const chip = el("button", "chip" + (state.filters.has(group.key) ? " active" : ""), group.label);
    chip.onclick = () => {
      state.filters.has(group.key) ? state.filters.delete(group.key) : state.filters.add(group.key);
      renderFilters();
      renderFindings();
    };
    box.appendChild(chip);
  });
  const clear = el("button", "chip", "필터 해제");
  clear.onclick = () => { state.filters.clear(); renderFilters(); renderFindings(); };
  box.appendChild(clear);
}

function matchesFilters(finding) {
  if (state.filters.size === 0) return true;
  return FILTER_GROUPS.some((group) => {
    if (!state.filters.has(group.key)) return false;
    if (group.types && group.types.includes(finding.type)) return true;
    if (group.statuses && group.statuses.includes(finding.status)) return true;
    return false;
  });
}

function renderFindings() {
  const box = $("#findingList");
  box.replaceChildren();
  const items = state.findings.filter((f) => !f.advisory_only && matchesFilters(f));
  if (!items.length) { box.appendChild(el("p", "sub", "표시할 Finding이 없습니다.")); return; }
  items.forEach((finding) => box.appendChild(findingCard(finding)));
}

function renderAdvisory() {
  const box = $("#advisoryList");
  box.replaceChildren();
  const items = state.findings.filter((f) => f.advisory_only);
  if (!items.length) { box.appendChild(el("p", "sub", "참고 신호가 없습니다.")); return; }
  items.forEach((finding) => box.appendChild(findingCard(finding)));
}

function findingCard(finding) {
  const card = el("div", `finding sev-${finding.severity}`);
  const head = el("div", "head");
  const left = el("div");
  left.appendChild(el("div", "title", finding.title));
  const document_ = state.documents.find((d) => d.id === finding.document_id);
  left.appendChild(el("div", "sub",
    `${document_ ? document_.filename : "프로젝트 전체"}${finding.page ? ` · ${finding.page}면` : ""} · ${finding.engine || ""}`));
  head.appendChild(left);
  head.appendChild(el("span", `badge sev sev-${finding.severity}`, finding.severity));
  card.appendChild(head);

  card.appendChild(el("div", "detail", finding.detail));

  const badges = el("div", "badges");
  [`유형 ${finding.type}`, `상태 ${finding.status}`, `근거등급 ${finding.evidence_grade}`,
   `확신도 ${finding.confidence.toFixed(2)}`,
   finding.meta_message_type ? `메타메시지 ${finding.meta_message_type}` : null,
   ...(finding.tags || []).map((t) => t)]
    .filter(Boolean)
    .forEach((text) => badges.appendChild(el("span", "badge", text)));
  card.appendChild(badges);

  (finding.evidence || []).forEach((evidence) => {
    const box = el("div", "evidence");
    box.appendChild(el("div", null, `근거(${evidence.grade}) ${evidence.description || ""}`));
    if (evidence.sealed) {
      box.appendChild(el("div", "sealed", evidence.sealed_notice || "SEALED: 열람 요청 시에만 공개됩니다."));
    } else if (evidence.excerpt) {
      box.appendChild(el("div", "mono", evidence.excerpt));
    }
    card.appendChild(box);
  });

  const review = el("div", "review");
  review.appendChild(el("span", "sub", "검토상태"));
  const select = el("select");
  REVIEW_OPTIONS.forEach((option) => {
    const opt = el("option", null, option);
    opt.value = option;
    if (finding.review_status === option) opt.selected = true;
    select.appendChild(opt);
  });
  const note = el("input");
  note.placeholder = "검토 의견";
  note.value = finding.review_note || "";
  const save = el("button", "btn small", "저장");
  save.onclick = async () => {
    try {
      await api(`/findings/${finding.id}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_status: select.value, note: note.value }),
      });
      toast("검토 상태를 저장했습니다. 원래 Finding과 감사기록은 삭제되지 않습니다.");
      await loadFindings();
    } catch (err) { toast("저장 실패: " + err.message); }
  };
  review.append(select, note, save);

  if (finding.has_sealed_content) {
    const reveal = el("button", "btn small", "봉인 원문 열람");
    reveal.onclick = async () => {
      const ok = confirm(
        "이 항목은 상대방의 소송준비자료나 의뢰인 비밀에 해당할 수 있습니다.\n" +
        "본 시스템은 법적·윤리적 결론을 내리지 않으며, 열람 여부는 사용자가 결정합니다.\n" +
        "열람 사실은 감사추적에 기록됩니다. 열람하시겠습니까?");
      if (!ok) return;
      try {
        const data = await jsonPost(`/findings/${finding.id}/reveal`, { confirmed: true, reason: "사용자 열람 요청" });
        const box = el("div", "evidence");
        box.appendChild(el("div", "sealed", "봉인 해제된 원문 (열람 기록됨)"));
        box.appendChild(el("div", "mono", data.sealed_excerpt || "(내용 없음)"));
        card.appendChild(box);
        reveal.remove();
      } catch (err) { toast("열람 불가: " + err.message); }
    };
    review.appendChild(reveal);
  }
  card.appendChild(review);
  return card;
}

/* ---------- 뷰어 ---------- */
async function renderViewer() {
  const select = $("#viewerDoc");
  if (select.options.length !== state.documents.length) {
    select.replaceChildren();
    state.documents.forEach((document_) => {
      const option = el("option", null, document_.filename);
      option.value = document_.id;
      select.appendChild(option);
    });
  }
  if (!state.viewerDocId && state.documents.length) state.viewerDocId = state.documents[0].id;
  if (!state.viewerDocId) return;
  select.value = state.viewerDocId;

  const showHidden = $("#showHidden").checked;
  let data;
  try {
    data = await api(`/documents/${state.viewerDocId}/blocks?include_hidden=${showHidden}`);
  } catch (err) { toast("문서 구조를 불러오지 못했습니다: " + err.message); return; }

  const area = $("#pageArea");
  area.replaceChildren();
  const findings = state.findings.filter((f) => f.document_id === state.viewerDocId);

  (data.pages.length ? data.pages : [{ page_number: 1, width: 595, height: 842 }]).forEach((page) => {
    const wrap = el("div", "page");
    wrap.appendChild(el("div", "caption",
      `${page.page_number}면 · ${Math.round(page.width)}×${Math.round(page.height)}pt`));
    const canvas = el("div", "canvas");
    const scale = 560 / (page.width || 595);
    canvas.style.height = `${(page.height || 842) * scale}px`;
    canvas.style.width = `${(page.width || 595) * scale}px`;

    data.blocks.filter((b) => b.page === page.page_number).forEach((block) => {
      if (!block.bbox) return;
      const node = el("div", "blk " + (block.visible ? "visible" : "hiddenlayer"), block.text);
      node.style.left = `${block.bbox[0] * scale}px`;
      node.style.top = `${block.bbox[1] * scale}px`;
      node.style.width = `${Math.max(4, (block.bbox[2] - block.bbox[0]) * scale)}px`;
      node.style.height = `${Math.max(6, (block.bbox[3] - block.bbox[1]) * scale)}px`;
      node.title = block.visible ? block.source_layer
        : `숨은 레이어: ${block.source_layer} ${(block.attributes && block.attributes.hidden_reason) || ""}`;
      canvas.appendChild(node);
    });

    findings.filter((f) => f.page === page.page_number && f.bbox).forEach((finding) => {
      const hl = el("div", `hl sev-${finding.severity}`);
      hl.style.left = `${finding.bbox[0] * scale}px`;
      hl.style.top = `${finding.bbox[1] * scale}px`;
      hl.style.width = `${Math.max(4, (finding.bbox[2] - finding.bbox[0]) * scale)}px`;
      hl.style.height = `${Math.max(6, (finding.bbox[3] - finding.bbox[1]) * scale)}px`;
      canvas.appendChild(hl);
    });

    wrap.appendChild(canvas);
    area.appendChild(wrap);
  });

  const panel = $("#viewerFindings");
  panel.replaceChildren();
  panel.appendChild(el("h3", null, `이 문서의 Finding (${findings.length})`));
  findings.forEach((finding) => panel.appendChild(findingCard(finding)));
}

/* ---------- 타임라인 / 감사추적 ---------- */
function renderTimeline() {
  const box = $("#timeline");
  box.replaceChildren();
  const items = (state.run && state.run.scores && state.run.timeline) || (state.run && state.run.timeline) || [];
  if (!items.length) { box.appendChild(el("p", "sub", "추출된 사건 일자가 없습니다.")); return; }
  items.forEach((event) => {
    const node = el("div", "timeline-item");
    node.appendChild(el("div", "date", `${event.date || "일자 미상"} · ${event.event_kind}`));
    node.appendChild(el("div", null, event.description));
    box.appendChild(node);
  });
}

async function renderAudit() {
  const box = $("#auditView");
  box.replaceChildren();
  try {
    const [audit, verify] = await Promise.all([
      api(`/projects/${state.projectId}/audit`),
      api("/audit/verify"),
    ]);
    const status = el("div", "notice",
      `해시 체인 무결성: ${verify.valid ? "정상" : "손상 감지"} · 이벤트 ${verify.event_count}건 · head ${verify.head_hash.slice(0, 24)}…`);
    box.appendChild(status);
    const table = el("table", "table");
    const head = el("thead"); const headRow = el("tr");
    ["#", "이벤트", "행위자", "문서", "이전 해시", "이벤트 해시", "시각"].forEach((h) => headRow.appendChild(el("th", null, h)));
    head.appendChild(headRow); table.appendChild(head);
    const body = el("tbody");
    audit.events.forEach((event) => {
      const row = el("tr");
      row.appendChild(el("td", null, event.sequence));
      row.appendChild(el("td", null, event.event_type));
      row.appendChild(el("td", null, event.actor));
      row.appendChild(el("td", "mono", (event.document_id || "-").slice(0, 14)));
      row.appendChild(el("td", "mono", event.previous_hash.slice(0, 14) + "…"));
      row.appendChild(el("td", "mono", event.event_hash.slice(0, 14) + "…"));
      row.appendChild(el("td", "sub", event.created_at.replace("T", " ").slice(0, 19)));
      body.appendChild(row);
    });
    table.appendChild(body);
    box.appendChild(table);
  } catch (err) { box.appendChild(el("p", "sub", "감사기록을 불러오지 못했습니다: " + err.message)); }
}

/* ---------- 보고서 / Outbound ---------- */
async function createReport() {
  try {
    const report = await jsonPost(`/projects/${state.projectId}/reports`,
      { formats: ["pdf", "highlight", "xlsx", "csv", "json", "manifest"], include_sealed: false });
    const box = $("#scoreCards");
    const card = el("div", "card");
    card.appendChild(el("div", "label", "보고서 산출물"));
    Object.entries(report.artifacts).forEach(([format, info]) => {
      if (info.error) { card.appendChild(el("div", "note", `${format}: 생성 실패 (${info.error})`)); return; }
      const link = el("a", null, `${format.toUpperCase()} 내려받기 (${(info.size_bytes / 1024).toFixed(1)} KB)`);
      link.href = `${API}/reports/${report.report_id}/download/${format}`;
      link.style.display = "block";
      card.appendChild(link);
    });
    card.appendChild(el("div", "note", "봉인된 원문은 기본적으로 보고서에 포함되지 않습니다."));
    box.prepend(card);
    toast("보고서를 생성했습니다.");
  } catch (err) { toast("보고서 생성 실패: " + err.message); }
}

async function outboundGuard(documentId) {
  try {
    const result = await jsonPost(`/documents/${documentId}/outbound-guard`, { generate_sanitized: true });
    const lines = [`발신 전 점검 항목 ${result.risk_items.length}건`];
    result.risk_items.slice(0, 5).forEach((item) => lines.push(`· ${item.severity} ${item.type}`));
    if (result.sanitized) lines.push(`정제본 생성됨 (제거: ${JSON.stringify(result.sanitized.removed)})`);
    (result.manual_actions || []).forEach((action) => lines.push(`· 수동조치: ${action}`));
    alert(lines.join("\n"));
    await refreshProject();
  } catch (err) { toast("발신 전 검사 실패: " + err.message); }
}

boot();
