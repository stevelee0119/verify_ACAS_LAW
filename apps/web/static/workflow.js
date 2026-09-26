"use strict";

const workflowUI = (() => {
  let projectId = null, matrix = null, issues = [], workflows = new Map(), generation = 0;
  const selected = new Set();
  const states = {NOT_STARTED:"미검토", IN_PROGRESS:"검토 중", ACTION_REQUIRED:"조치 필요", COMPLETED:"검토 완료", DEFERRED:"판단 보류"};
  const decisions = {UNDECIDED:"판단 전", AGREED:"동의", FALSE_POSITIVE:"오탐", PARTLY_AGREED:"일부 동의"};
  const positions = {UNASSESSED:"검토 전", ASSERTED:"주장", ADMITTED:"인정", DENIED:"부인", UNKNOWN:"불지", CONDITIONAL:"가정적 주장", ALTERNATIVE:"예비적 주장"};
  const supports = {UNASSESSED:"미확인", SUPPORTED:"지지", PARTIAL:"일부 지지", CONFLICTING:"상충", INSUFFICIENT:"자료 부족", REVIEWED:"검토 완료", EVIDENCE_EXCLUDED:"근거자료 제외"};
  function field(name, title, value = "", type = "text", options = null) {
    const labelEl = node("label", title);
    const input = node(options ? "select" : type === "textarea" ? "textarea" : "input");
    input.name = name;
    input.setAttribute("aria-label", title);
    if (options) for (const [key, title] of Object.entries(options)) {
      const option = node("option", title); option.value = key; input.append(option);
    }
    else if (type === "textarea") input.rows = 3;
    else input.type = type;
    input.value = value ?? "";
    if (type === "checkbox") input.checked = !!value;
    labelEl.append(input);
    return labelEl;
  }
  function modal(title, fields, save, wide = false) {
    const dialog = node("dialog", null, wide ? "wide workflow-dialog" : "workflow-dialog");
    dialog.setAttribute("aria-label", title);
    const form = node("form");
    const header = node("div", null, "dialog-heading");
    header.append(node("h2", title), iconButton("x", "닫기", () => dialog.close()));
    const grid = node("div", null, "form-grid"); grid.append(...fields);
    const error = node("p", "", "error"); error.setAttribute("role", "alert");
    const footer = node("div", null, "dialog-footer");
    const submit = node("button", "저장", "primary"); submit.type = "submit";
    footer.append(button("취소", () => dialog.close()), submit);
    form.append(header, grid, error, footer);
    form.onsubmit = async event => {
      event.preventDefault(); submit.disabled = true; error.textContent = "";
      try { await save(Object.fromEntries(new FormData(form)), form); dialog.close(); }
      catch (e) { error.textContent = e.message; }
      finally { submit.disabled = false; }
    };
    dialog.append(form); dialog.addEventListener("close", () => dialog.remove(), {once:true});
    document.body.append(dialog); dialog.showModal(); icons(); return {dialog, form, grid, submit};
  }
  function table(headers, rows) {
    const wrap = node("div", null, "table-wrap workflow-table");
    const t = node("table"), head = node("thead"), hr = node("tr"), body = node("tbody");
    for (const h of headers) hr.append(node("th", h));
    head.append(hr);
    for (const cells of rows) {
      const tr = node("tr");
      for (const cell of cells) { const td = node("td"); td.append(cell instanceof Node ? cell : node("span", cell)); tr.append(td); }
      body.append(tr);
    }
    t.append(head, body); wrap.append(t); return wrap;
  }
  function addTab(key, title) {
    const b = button(title, () => switchTab(key)); b.dataset.tab = key;
    document.querySelector(".tabs").append(b);
    const panel = node("section"); panel.dataset.panel = key; panel.hidden = true;
    $("projectView").append(panel); return panel;
  }
  async function located(id, page, runId) {
    const doc = state.documents.find(d => d.id === id);
    if (!doc) return;
    await openDocument(doc, null, runId); state.page = page || 1; await renderPage();
  }
  async function refresh(options = {}) {
    const id = state.project?.id, run = state.run;
    if (!id) return;
    const version = ++generation;
    if (projectId !== id) { selected.clear(); workflows = new Map(); matrix = null; projectId = id; }
    const issueData = await api(`/projects/${id}/issues`, options);
    let nextMatrix = null, nextWorkflows = [];
    if (run && ["COMPLETED", "PARTIAL_COMPLETED"].includes(run.state)) {
      [nextMatrix, nextWorkflows] = await Promise.all([
        api(`/projects/${id}/case-matrix?run_id=${run.id}`, options), api(`/projects/${id}/review-workflows?run_id=${run.id}`, options)]);
    }
    if (generation !== version || state.project?.id !== id) return;
    issues = issueData; matrix = nextMatrix; workflows = new Map(nextWorkflows.map(w => [w.finding_id, w]));
    selected.forEach(id => { if (!state.findings.some(f => f.id === id)) selected.delete(id); });
    renderMatrix(); renderReviewCount();
  }
  function issueEditor(issue = {}) {
    const pid = state.project.id;
    modal(issue.id ? "쟁점 수정" : "쟁점 추가", [
      field("title", "쟁점", issue.title), field("reference_date", "쟁점별 법령 기준일", issue.reference_date, "date"),
      field("elements", "검토할 요건사실 (한 줄에 하나)", (issue.elements || []).join("\n"), "textarea"),
      field("legal_basis", "법적 근거와 적용 전제", issue.legal_basis, "textarea"),
      field("priority", "변호사 지정 우선순위", issue.priority || 2, "text", {1:"우선 검토",2:"보통",3:"후순위"}),
      field("note", "검토 메모", issue.note, "textarea")
    ], async values => {
      await api(`/projects/${pid}/issues${issue.id ? `/${issue.id}` : ""}`, {method:issue.id ? "PUT" : "POST", body:{
        ...values, reference_date:values.reference_date || null, elements:values.elements.split("\n").map(s => s.trim()).filter(Boolean),
        priority:Number(values.priority), revision:issue.revision || 0}});
      await refreshScope(); await refresh(); toast("쟁점을 저장했습니다.");
    });
  }
  async function profileEditor() {
    const pid = state.project.id, profile = await api(`/projects/${pid}/case-profile`);
    modal("담당자·대리 당사자", [field("lead_reviewer", "담당 변호사", profile.lead_reviewer), field("represented_party", "대리하는 당사자", profile.represented_party)], async values => {
      await api(`/projects/${pid}/case-profile`, {method:"PUT",body:{...values,revision:profile.revision || 0}});
      toast("사건 담당 정보를 저장했습니다.");
    });
  }
  function renderMatrix() {
    const root = $("issueWorkbench"); if (!root) return;
    root.replaceChildren();
    const issueList = node("div", null, "issue-list");
    for (const issue of issues) {
      const row = node("div", null, "row-item");
      row.append(button(issue.title, () => issueEditor(issue), "row-title"), node("p", issue.elements.join(" · ") || "요건사실 미입력"),
        node("small", `${issue.reference_date || "기준일 미지정"} · ${issue.legal_basis || "법적 근거 미입력"}`, "muted"));
      issueList.append(row);
    }
    root.append(issueList);
    $("claims").hidden = !!matrix;
    if (!matrix) return;
    const filters = node("div", null, "toolbar");
    const issueFilter = field("issue", "쟁점", "", "text", {"":"모든 쟁점",...Object.fromEntries(issues.map(i=>[i.id,i.title]))});
    const positionFilter = field("position", "주장 구분", "", "text", {"":"모든 주장",...positions});
    filters.append(issueFilter,positionFilter);
    const result = node("div", null, "case-matrix");
    const draw = () => {
      const issueId = issueFilter.querySelector("select").value, pos = positionFilter.querySelector("select").value;
      const rows = matrix.claims.filter(c => (!issueId || c.assessment.issue_id === issueId) && (!pos || (c.assessment.position || "UNASSESSED") === pos)).map(item => {
        const a = item.assessment, c = item.claim, issue = issues.find(i=>i.id === a.issue_id);
        const left = node("div"); left.append(node("strong", issue?.title || "미연결"), node("p", issue?.elements.join(" · ") || ""));
        const claim = node("div");
        claim.append(button(c.text || c.claim_text || c.statement || "주장 원문", () => located(item.document_id,c.page,matrix.run_id), "row-title"),
          node("small", `${positions[a.position || "UNASSESSED"]} · ${c.claimant || c.speaker || "주장자 미확인"}`, "muted"));
        const evidence = node("div");
        for (const link of a.evidence_links || []) {
          const doc = state.documents.find(d=>d.id === link.document_id);
          evidence.append(button(`${doc?.evidence_number || doc?.filename || link.document_id}${link.page ? ` · ${link.page}쪽` : ""}`, () => located(link.document_id,link.page,matrix.run_id)), node("p", link.excerpt));
        }
        evidence.append(node("p", a.missing_material || ((a.evidence_links || []).length ? "" : "연결된 검토 근거 없음"), "muted"));
        const review = node("div");
        review.append(node("span", supports[item.review_status] || item.review_status, `badge ${item.excluded_evidence.length ? "HIGH" : "INFO"}`), button("검토 기록", () => assessmentEditor(item)));
        return [left,claim,evidence,review];
      });
      result.replaceChildren(rows.length ? table(["쟁점·요건사실","당사자 주장","지지·반박 근거 / 부족 자료","변호사 판단"],rows) : node("p","표시할 주장이 없습니다.","empty-small"));
    };
    filters.addEventListener("change",draw); root.append(filters,result); draw();
  }
  function assessmentEditor(item) {
    const pid = state.project.id, runId = matrix.run_id, a = item.assessment, c = item.claim;
    const links = node("div", null, "full evidence-link-editor"), rows = [];
    const docOptions = Object.fromEntries(state.documents.filter(d=>d.included_in_verification && state.run.document_ids.includes(d.id)).map(d=>[d.id,`${d.evidence_number || ""} ${d.filename}`]));
    const addLink = (link = {}) => {
      const row = node("div", null, "evidence-link-row");
      row.append(field("linkDoc", "근거 자료", link.document_id, "text", docOptions), field("linkPage", "근거 쪽수", link.page, "number"),
        field("linkRelation", "근거 관계", link.relation || "UNASSESSED", "text", {UNASSESSED:"판단 전",SUPPORTS:"지지",REFUTES:"반박",CONTEXT:"문맥"}),
        field("linkExcerpt", "근거 발췌 / 위치 메모", link.excerpt, "textarea"), iconButton("x", "근거 연결 취소", () => row.remove()));
      rows.push(row); links.append(row);
    };
    for (const link of a.evidence_links || []) addLink(link);
    const add = button("근거 연결", () => addLink());
    const editor = modal("주장·증거 검토", [node("p", c.text || c.claim_text || c.statement || "", "full"),
      field("issue_id", "쟁점", a.issue_id || "", "text", {"":"미연결",...Object.fromEntries(issues.map(i=>[i.id,i.title]))}),
      field("position", "주장에 대한 입장", a.position || "UNASSESSED", "text", positions),
      field("support_status", "근거에 대한 검토 결과", a.support_status || "UNASSESSED", "text", supports),
      field("missing_material", "부족 자료", a.missing_material, "textarea"),
      field("note", "변호사 의견", a.note, "textarea"), links, add], async values => {
      const evidence_links = rows.filter(row=>row.isConnected).map(row=>({
        document_id:row.querySelector('[name="linkDoc"]').value,
        page:Number(row.querySelector('[name="linkPage"]').value) || null,
        relation:row.querySelector('[name="linkRelation"]').value, excerpt:row.querySelector('[name="linkExcerpt"]').value}));
      await api(`/projects/${pid}/claim-assessments`, {method:"PUT", body:{run_id:runId,claim_id:c.claim_id,
        issue_id:values.issue_id || null,position:values.position,support_status:values.support_status,
        missing_material:values.missing_material,note:values.note,evidence_links,revision:a.revision || 0}});
      await refresh(); toast("주장·증거 검토를 저장했습니다.");
    }, true);
    editor.grid.querySelector('[name="support_status"] option[value="EVIDENCE_EXCLUDED"]')?.remove();
  }
  function priority(f) { return workflows.get(f.id)?.priority || 2; }
  function matches(f) {
    const w = workflows.get(f.id), stage = $("workflowFilter")?.value, person = $("assigneeFilter")?.value.trim().toLowerCase();
    return (!stage || (w?.workflow_state || "NOT_STARTED") === stage) && (!person || (w?.assignee || "").toLowerCase().includes(person));
  }
  function renderReviewCount() { if ($("batchReview")) $("batchReview").textContent = `선택 항목 검토 (${selected.size})`; }
  function decorateFinding(f, row) {
    const check = node("input"); check.type="checkbox"; check.checked=selected.has(f.id);
    check.setAttribute("aria-label", `${f.title} 선택`);
    check.onchange=()=>{check.checked?selected.add(f.id):selected.delete(f.id); renderReviewCount();};
    const info = node("div", null, "review-selection"), w = workflows.get(f.id);
    info.append(check,node("span",`${states[w?.workflow_state || "NOT_STARTED"]}${w?.assignee ? ` · ${w.assignee}` : ""}`,"muted")); row.append(info);
  }
  async function bulkEditor() {
    if (!selected.size) return toast("검토할 항목을 선택하세요.");
    const pid = state.project.id, ids = [...selected];
    modal("선택 항목 검토", [field("workflow_state","검토 상태","COMPLETED","text",states),field("decision","판단 내용","UNDECIDED","text",decisions),
      field("priority","변호사 지정 우선순위",2,"text",{1:"우선 검토",2:"보통",3:"후순위"}),field("assignee","담당자"),field("note","공통 검토 의견","","textarea")],async values=>{
      await api(`/projects/${pid}/reviews`,{method:"POST",body:{finding_ids:ids,expected_revisions:Object.fromEntries(ids.map(id=>[id,workflows.get(id)?.revision || 0])),values:{...values,priority:Number(values.priority)}}});
      selected.clear(); await loadResults(state.generation); toast("선택 항목을 저장했습니다.");
    });
  }
  async function enhanceFinding(f, legacyForm, area) {
    const w = await api(`/findings/${f.id}/workflow`);
    if (!legacyForm.isConnected) return;
    const form = node("form",null,"detail-section form-grid");
    const heading = node("h3","담당 변호사 검토","full");
    form.append(heading,field("workflow_state","검토 상태",w.workflow_state,"text",states),field("decision","판단 내용",w.decision,"text",decisions),
      field("priority","변호사 지정 우선순위",w.priority,"text",{1:"우선 검토",2:"보통",3:"후순위"}),field("assignee","담당자",w.assignee));
    const note = field("note","검토 의견",w.draft?.note ?? w.note,"textarea"); note.classList.add("full"); form.append(note);
    const draftStatus=node("small",w.draft?.updated_at?"임시 저장된 의견 복원됨":"","muted full");
    let timer, pendingDraft = Promise.resolve();
    note.querySelector("textarea").oninput=()=>{clearTimeout(timer);timer=setTimeout(async()=>{
      try {pendingDraft = api(`/findings/${f.id}/review-draft`,{method:"PUT",body:{note:note.querySelector("textarea").value, revision:w.revision}}); await pendingDraft; draftStatus.textContent="임시 저장됨";}
      catch {draftStatus.textContent="임시 저장 실패";}
    },700);};
    const save=node("button","검토 저장","primary"); save.type="submit";
    form.append(draftStatus,save);
    form.onsubmit=action(async e=>{
      e.preventDefault(); clearTimeout(timer); save.disabled=true;
      try {await pendingDraft.catch(()=>{}); const values=Object.fromEntries(new FormData(form)); await api(`/findings/${f.id}/workflow`,{method:"PUT",body:{...values,priority:Number(values.priority),revision:w.revision}});
        await loadResults(state.generation); $("detailDialog").close(); toast("검토 기록을 저장했습니다.");}
      finally {save.disabled=false;}
    });
    legacyForm.replaceWith(form);
    const nav=node("div",null,"toolbar");
    const pending=state.findings.filter(item=>(workflows.get(item.id)?.workflow_state || "NOT_STARTED")!=="COMPLETED");
    const index=pending.findIndex(item=>item.id===f.id);
    for (const [direction,icon,title] of [[-1,"arrow-left","이전 미검토 항목"],[1,"arrow-right","다음 미검토 항목"]]) {
      const target=pending[(index+direction+pending.length)%pending.length];
      const b=iconButton(icon,title,()=>openFinding(target)); b.disabled=!target || target.id===f.id; nav.append(b);
    }
    nav.append(button("검토 이력",()=>showHistory(f.id))); area.prepend(nav);
    const doc=(state.result.documents || []).find(d=>d.document_id===f.document_id);
    const citationIds=new Set((doc?.citations || []).filter(c=>f.block_id ? c.block_id===f.block_id : f.page && c.page===f.page).map(c=>c.citation_id));
    for (const verdict of doc?.engine_data?.legal_verdicts || []) {
      if(!citationIds.has(verdict.citation_id))continue;
      if(verdict.components?.length)area.append(citationComponents(verdict,(doc.citations || []).find(c=>c.citation_id===verdict.citation_id)));
      const inline=verdict.official_record;
      const record=state.result?.source_objects?.[inline?.source_object_ref] || inline;
      if (!record) continue;
      const detail=node("details",null,"detail-section");
      detail.append(node("summary",`공식 출처 대조 · ${verdict.reference_date || record.effective_date || "기준일 미확인"}`));
      for(const note of verdict.notes || [])detail.append(node("p",note));
      detail.append(node("pre",record.full_text || record.text || JSON.stringify(record,null,2),"technical source-text"));
      area.append(detail);
    }
    icons();
  }
  // 인용 하나의 상태는 가장 약한 단계를 따른다. 법령·조문이 확인됐어도 기준일이 없으면
  // '일부 확인'이 되므로, 무엇을 확인했고 무엇이 남았는지를 단계별로 따로 보인다.
  const COMPONENT_STATUS={CONFIRMED:"확인",TEXT_AVAILABLE:"본문 확보",PARTIAL:"일부 확인",MISMATCH:"불일치",
    NOT_FOUND_IN_SEARCHED_SCOPE:"조회 범위 내 미발견",NOT_FOUND_IN_SELECTED_VERSION:"조회한 버전에 없음",
    DELETED:"삭제된 조문",INVALID_FORMAT:"성립 불가 형식",UNVERIFIED:"미확인",NOT_RUN:"검토 전",
    REVIEW_NEEDED:"사람 검토 필요",NOT_APPLICABLE:"해당 없음"};
  function citationComponents(verdict,citation) {
    const box=node("section",null,"detail-section citation-components");
    box.append(node("h3",`인용 검증 단계 · ${citation?.raw_text || verdict.citation_id}`));
    box.append(table(["확인 항목","결과","설명"],(verdict.components || []).map(c=>{
      const status=node("span",COMPONENT_STATUS[c.status] || c.status,`component-status status-${c.status.toLowerCase()}`);
      return [c.label,status,c.meaning || ""];
    })));
    const dates=verdict.reference_date_candidates || [];
    if(dates.length)box.append(node("p",`문서의 기준일 후보(자동 적용하지 않음): ${dates.map(d=>`${d.label} ${d.date}`).join(", ")}`,"muted"));
    return box;
  }
  async function showHistory(subjectId) {
    const entries=await api(`/projects/${state.project.id}/review-history${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:""}`);
    const content=node("div",null,"full");
    for (const item of entries) { const row=node("div",null,"row-item"); row.append(node("strong",`${item.actor} · ${dateText(item.created_at)}`),node("pre",JSON.stringify({before:item.before,after:item.after},null,2),"technical"));content.append(row); }
    if (!entries.length) content.append(node("p","변경 이력이 없습니다."));
    const view=modal("검토 변경 이력",[content],async()=>{}); view.submit.hidden=true;
  }
  async function activate(tab) {
    if (tab === "issues" || tab === "review") {await refresh(); if(tab === "review") renderFindings();}
    if (tab === "compare") renderCompare();
    if (tab === "search") renderSearch();
  }
  function renderCompare() {
    const root=$("comparePanel"), pid=state.project.id;
    root.replaceChildren(node("h2","문서 버전 비교"));
    const options={"":"자료 선택",...Object.fromEntries(state.documents.map(d=>[d.id,`${d.evidence_number || ""} ${d.filename}`]))};
    const form=node("form",null,"toolbar comparison-controls");
    form.append(field("left_id","이전 문서","","text",options),field("right_id","수정·제출 문서","","text",options));
    const compare=node("button","비교","primary");compare.type="submit";form.append(compare);
    const output=node("div"), lineage=node("div",null,"detail-section");
    async function drawRelations() {
      const result=await api(`/projects/${pid}/document-relations`);
      if(pid!==state.project?.id)return;
      lineage.replaceChildren(node("h3","연결된 버전"));
      for(const rel of result) {
        const parent=state.documents.find(d=>d.id===rel.parent_id),child=state.documents.find(d=>d.id===rel.child_id);
        lineage.append(node("p",`${parent?.filename || rel.parent_id} → ${child?.filename || rel.child_id} · ${rel.note || "버전 연결"}`));
      }
      if(!result.length)lineage.append(node("p","연결된 버전이 없습니다.","muted"));
    }
    form.append(button("이전 버전으로 연결",()=>{
      const values=Object.fromEntries(new FormData(form));
      if(!values.left_id || !values.right_id)return toast("연결할 두 문서를 선택하세요.");
      modal("문서 버전 연결",[field("kind","수정본 구분","REVISION","text",{DRAFT:"초안",REVISION:"수정본",FILED:"제출본",DERIVATIVE:"파생본"}),field("note","변경 메모","","textarea")],async data=>{
        await api(`/projects/${pid}/document-relations`,{method:"POST",body:{parent_id:values.left_id,child_id:values.right_id,...data}});
        toast("문서 버전 관계를 기록했습니다.");await drawRelations();
      });
    }));
    form.onsubmit=action(async e=>{
      e.preventDefault();const values=Object.fromEntries(new FormData(form));
      if(!values.left_id || !values.right_id)return toast("비교할 두 문서를 선택하세요.");
      compare.disabled=true;
      try {
        const result=await api(`/projects/${pid}/compare?${new URLSearchParams(values)}`);
        if(pid!==state.project?.id)return;
        output.replaceChildren(node("p",result.notice,"notice"));
        if(result.unchanged)output.append(node("p","추출된 본문의 변경이 없습니다."));
        for(const change of result.changes) {
          const row=node("section",null,"comparison-change");
          row.append(node("h3",`${{insert:"추가",delete:"삭제",replace:"변경"}[change.kind] || change.kind}${change.numeric_change?" · 숫자 포함":""}${change.citation_change?" · 인용 포함":""}`));
          const cols=node("div",null,"comparison-columns");
          for(const [key,title,id,run] of [["before","이전 문서",values.left_id,result.left_run_id],["after","수정·제출 문서",values.right_id,result.right_run_id]]) {
            const side=node("div",null,key);side.append(node("strong",title));
            if(!change[key].length)side.append(node("p","해당 본문 없음","muted"));
            for(const block of change[key])side.append(button(`${block.page}쪽 원문`,()=>located(id,block.page,run)),node("pre",block.text,"source-text"));
            cols.append(side);
          }
          row.append(cols);output.append(row);
        }
      }finally{compare.disabled=false;}
    });
    root.append(form,output,lineage);drawRelations().catch(e=>toast(e.message));
  }
  function renderSearch() {
    const root=$("searchPanel"),pid=state.project.id,runId=state.run?.id;
    root.replaceChildren(node("h2","사건 내 근거 찾기"));
    const form=node("form",null,"toolbar search-controls"),query=field("q","사실관계·증거 검색","","search");
    const input=query.querySelector("input");input.required=true;input.minLength=2;input.maxLength=200;
    const search=node("button","검색","primary");search.type="submit";
    form.append(query,search);const results=node("div");root.append(form,results);
    form.onsubmit=action(async e=>{
      e.preventDefault();if(!runId)return toast("자료를 검증한 뒤 검색하세요.");search.disabled=true;
      try{
        const result=await api(`/projects/${pid}/search?${new URLSearchParams({q:input.value,run_id:runId})}`);
        if(pid!==state.project?.id)return;
        results.replaceChildren(node("p",result.notice,"muted"));
        for(const item of result.results){
          const doc=state.documents.find(d=>d.id===item.document_id),row=node("article",null,"row-item");
          row.append(button(`${doc?.evidence_number || doc?.filename} · ${item.page}쪽`,()=>located(item.document_id,item.page,runId),"row-title"),node("p",item.text));results.append(row);
        }
        if(!result.results.length)results.append(node("p","일치하는 가시 본문이 없습니다.","empty-small"));
      }finally{search.disabled=false;}
    });
  }
  function init() {
    const toolbar=document.querySelector('[data-panel="issues"] .toolbar');
    const issueActions=node("div",null,"actions");
    $("editIssues").textContent="검토 범위";
    issueActions.append($("editIssues"),button("쟁점 추가",()=>issueEditor()),iconButton("contact","담당자·대리 당사자",profileEditor));
    toolbar.append(issueActions);
    const workbench=node("div");workbench.id="issueWorkbench";$("claims").before(workbench);
    const reviewToolbar=document.querySelector('[data-panel="review"] .toolbar');
    const filter=field("workflowFilter","진행 상태","","text",{"":"모든 진행 상태",...states});filter.querySelector("select").id="workflowFilter";
    const assignee=field("assigneeFilter","담당자 검색");assignee.querySelector("input").id="assigneeFilter";
    filter.onchange=renderFindings;assignee.oninput=renderFindings;
    const bulk=button("선택 항목 검토 (0)",bulkEditor);bulk.id="batchReview";
    const controls=node("div",null,"toolbar workflow-filters");controls.append(filter,assignee,bulk,iconButton("history","검토 이력",()=>showHistory()));reviewToolbar.after(controls);
    addTab("compare","버전 비교").id="comparePanel";addTab("search","근거 찾기").id="searchPanel";
    const submitted=field("submitted_on","제출일","","date");$("documentForm").querySelector(".form-grid").append(submitted);
  }
  return {init,refresh,activate,matches,priority,decorateFinding,enhanceFinding,field,modal,table,located};
})();
