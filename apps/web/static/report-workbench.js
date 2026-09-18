"use strict";

const reportWorkbench = (() => {
  const formats = {pdf:"PDF",docx:"Word (DOCX)",xlsx:"Excel (XLSX)",csv:"CSV",json:"검증 상세 (JSON)",manifest:"무결성 기록"};
  function create() {
    const run=state.run, pid=state.project.id;
    if(!run || !["COMPLETED","PARTIAL_COMPLETED"].includes(run.state))return toast("완료된 검증을 선택하세요.");
    const choices=node("fieldset",null,"full report-formats");choices.append(node("legend","보고서 형식"));
    for(const [key,title] of Object.entries(formats))choices.append(workflowUI.field(key,title,true,"checkbox"));
    const editor=workflowUI.modal("검토 보고서 초안",[
      workflowUI.field("audience","보고서 용도","INTERNAL","text",{INTERNAL:"내부 검토용",SHAREABLE:"공유용 (내부 메모 제외)"}), choices
    ],async(values,form)=>{
      const selected=Object.keys(formats).filter(key=>form.elements[key].checked);
      if(!selected.length)throw new Error("보고서 형식을 하나 이상 선택하세요.");
      await api(`/projects/${pid}/reports`,{method:"POST",body:{run_id:run.id,formats:selected,audience:values.audience,include_sealed:false}});
      if(state.project?.id===pid)await loadReports();toast("보고서 초안을 생성했습니다.");
    });
    editor.submit.textContent="초안 생성";
  }
  async function finalize(report) {
    const checks=await api(`/reports/${report.report_id}/preflight`), content=node("div",null,"full");
    content.append(workflowUI.table(["확인 사항","상태"],[
      ["변호사 검토 미완료",`${checks.incomplete_reviews.length}건`],
      ["주장·증거 검토 미완료",`${checks.incomplete_claim_reviews.length}건`],
      ["시스템 미확인·주의 항목",`${checks.unresolved_findings.length}건`],
      ["조회하지 못한 출처",`${checks.unavailable_sources.length}건`],
      ["자료·설정 변경",checks.stale_scope?"변경 전 결과":"변경 없음"],
      ["개인정보·비밀정보 주의",`${checks.sensitive_concerns.length}건`]
    ]));
    const details=node("details");details.append(node("summary","미확인 항목·공유 범위 상세"));
    for(const item of checks.sensitive_concerns)details.append(node("p",item.title || item.type));
    for(const item of checks.unverified_items)details.append(node("p",item.reason || JSON.stringify(item)));
    for(const source of checks.unavailable_sources)details.append(node("p",typeof source === "string"?source:JSON.stringify(source)));
    content.append(details,node("p",checks.privacy_notice,"notice"));
    const acknowledgments={acknowledge_unresolved:"잔여 미확인 항목과 검토 상태를 확인했습니다",acknowledge_stale_scope:"자료·설정 변경 전 결과임을 확인했습니다",acknowledge_privacy:"개인정보·비밀정보와 보고서 공유 범위를 확인했습니다"};
    const fields=[content,workflowUI.field("note","확정 의견·유보 사항","","textarea")];
    for(const [key,title] of Object.entries(acknowledgments))if(checks.required_acknowledgments[key])fields.push(workflowUI.field(key,title,false,"checkbox"));
    const editor=workflowUI.modal("보고서 확정 전 점검",fields,async(values,form)=>{
      const payload={note:values.note,expected_preflight_hash:checks.preflight_hash};
      for(const key of Object.keys(acknowledgments))payload[key]=form.elements[key]?.checked || false;
      await api(`/reports/${report.report_id}/finalize`,{method:"POST",body:payload});
      if(state.project?.id===report.project_id)await loadReports();toast("새 확정본을 생성했습니다. 기존 초안은 보존됩니다.");
    },true);
    editor.form.elements.note.required=true;
    for(const key of Object.keys(acknowledgments))if(editor.form.elements[key])editor.form.elements[key].required=true;
    editor.submit.textContent="확정본 생성";
  }
  function decorate(report,row) {
    row.prepend(node("strong",report.label || `${report.state === "FINAL"?"확정본":"초안"} · ${report.audience === "SHAREABLE"?"공유용":"내부 검토용"}`));
    if(report.state === "FINAL")row.append(node("p",`${report.finalized_by} · ${dateText(report.finalized_at)} · ${report.note || ""}`,"muted"));
    else if(report.snapshot_hash)row.append(button("점검 후 확정",()=>finalize(report)));
    if(report.snapshot_hash){const details=node("details");details.append(node("summary","고정본 무결성"),node("code",`SHA-256: ${report.snapshot_hash}`));row.append(details);}
  }
  return {create,decorate};
})();
