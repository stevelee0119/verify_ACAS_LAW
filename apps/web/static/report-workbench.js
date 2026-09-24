"use strict";

const reportWorkbench = (() => {
  const formats = {pdf:"PDF",docx:"Word (DOCX)",xlsx:"Excel (XLSX)",csv:"CSV",json:"검증 상세 (JSON)",manifest:"무결성 기록"};
  // 보고서는 서버 뒤편에서 만들고, 화면은 1초마다 단계·진행률만 받아 온다.
  // 요청 하나가 수십 초 붙잡혀 있다 끊기던 문제를 없애고, 기다리는 동안 무엇을 하는지 보인다.
  const POLL_MS=1000, MAX_POLL_FAILURES=30, watching=new Set();
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function progressView() {
    const box=node("div",null,"full report-progress");box.hidden=true;
    box.setAttribute("role","status");box.setAttribute("aria-live","polite");
    const head=node("div",null,"report-progress-head"), stage=node("strong","",""), value=node("span","","report-progress-value");
    head.append(stage,value);
    const track=node("div",null,"report-progress-track"), fill=node("div",null,"report-progress-fill");
    track.setAttribute("role","progressbar");track.setAttribute("aria-valuemin","0");track.setAttribute("aria-valuemax","100");
    track.append(fill);
    const time=node("p","","muted report-progress-time");
    box.append(head,track,time);
    return {box, update(job, note="") {
      const percent=Math.max(0,Math.min(100,Math.round(job.percent||0)));
      box.hidden=false;box.dataset.state=job.state;
      stage.textContent=job.state==="FAILED"?"생성 실패":job.stage||"보고서 생성을 기다리는 중";
      value.textContent=`${percent}%`;fill.style.width=`${percent}%`;
      track.setAttribute("aria-valuenow",String(percent));track.setAttribute("aria-valuetext",`${stage.textContent} ${percent}%`);
      const seconds=Math.round(job.elapsed_seconds||0);
      time.textContent=note || (job.state==="COMPLETED"?`완료 · ${seconds}초 걸림`:`경과 ${seconds}초 · 창을 닫아도 생성은 계속되며 보고서 목록에서 진행률을 볼 수 있습니다.`);
    }};
  }
  async function follow(job, view, alive=()=>true) {
    let failures=0, note="";
    for(;;){
      view.update(job,note);
      if(job.state==="COMPLETED")return job;
      if(job.state==="FAILED")throw new Error(job.error || "보고서를 만들지 못했습니다.");
      await wait(failures?Math.min(5000,POLL_MS*failures):POLL_MS);
      if(!alive())return null;
      try{
        job=await api(`/projects/${job.project_id}/report-jobs/${job.job_id}`,{timeoutMs:15000});failures=0;note="";
      }catch(error){
        // 서버가 요청을 거절한 경우(권한·없는 작업)는 기다려도 바뀌지 않는다.
        if(error.status && error.status<500 && error.status!==408)throw error;
        failures+=1;
        if(failures>=MAX_POLL_FAILURES)throw new Error("서버와 연결이 계속 끊깁니다. 생성은 서버에서 계속될 수 있으니 잠시 후 보고서 목록을 확인하세요.");
        note=`연결이 잠시 끊겨 다시 확인하는 중입니다 (${failures}회). 생성은 서버에서 계속됩니다.`;
      }
    }
  }
  async function finished(pid, job) {
    if(state.project?.id===pid)await loadReports();
    const failed=Object.entries(job.artifacts || {}).filter(([,artifact])=>artifact.error).map(([fmt])=>fmt.toUpperCase());
    toast(failed.length?`보고서 초안을 만들었지만 ${failed.join(", ")} 형식은 생성하지 못했습니다.`:"보고서 초안을 생성했습니다.");
  }
  function create() {
    const run=state.run, pid=state.project.id;
    if(!run || !["COMPLETED","PARTIAL_COMPLETED"].includes(run.state))return toast("완료된 검증을 선택하세요.");
    const choices=node("fieldset",null,"full report-formats");choices.append(node("legend","보고서 형식"));
    for(const [key,title] of Object.entries(formats))choices.append(workflowUI.field(key,title,true,"checkbox"));
    const view=progressView();
    // 요약본은 판단에 필요한 내용만 싣는다. 전체 기술 기록을 PDF에 실으면 인용이 많은 사건에서
    // 수천 쪽이 되므로, 그 기록은 검증 상세(JSON)로 함께 만들어 보존한다.
    const depth=workflowUI.field("detail_level","보고서 분량","SUMMARY","text",
      {SUMMARY:"요약본 (권장) — 전체 기술 기록은 검증 상세(JSON)로 함께 생성",FULL:"전체 기술 기록 포함 — 매우 길어질 수 있음"});
    const editor=workflowUI.modal("검토 보고서 초안",[
      workflowUI.field("audience","보고서 용도","INTERNAL","text",{INTERNAL:"내부 검토용",SHAREABLE:"공유용 (내부 메모 제외)"}), depth, choices, view.box
    ],async(values,form)=>{
      const selected=Object.keys(formats).filter(key=>form.elements[key].checked);
      if(!selected.length)throw new Error("보고서 형식을 하나 이상 선택하세요.");
      const inputs=[...form.querySelectorAll("select, input")];
      inputs.forEach(input=>{input.disabled=true;});
      try{
        const job=await api(`/projects/${pid}/report-jobs`,{method:"POST",body:{run_id:run.id,formats:selected,audience:values.audience,detail_level:values.detail_level,include_sealed:false}});
        watching.add(job.job_id);
        try{
          const done=await follow(job,view,()=>editor.dialog.isConnected);
          if(!done){if(state.project?.id===pid)await loadReports();return;}
          const report=(await api(`/projects/${pid}/reports`)).find(item=>item.report_id===done.report_id) || {};
          await finished(pid,report);
        }finally{watching.delete(job.job_id);}
      }finally{inputs.forEach(input=>{input.disabled=false;});}
    });
    editor.submit.textContent="초안 생성";
  }
  // 창을 닫았거나 화면을 새로 연 경우에도 진행 중인 생성 작업을 목록 위에 보인다.
  async function showActive(pid, list) {
    let jobs=[];
    try{jobs=await api(`/projects/${pid}/report-jobs?active=true`);}catch{return;}
    if(state.project?.id!==pid)return;
    for(const job of jobs){
      if(watching.has(job.job_id))continue;
      const row=node("article",null,"row-item report-job-row"), view=progressView();
      row.append(node("p",`보고서 생성 중 · 실행 ${job.run_id.slice(0,8)} · ${(job.formats||[]).map(fmt=>fmt.toUpperCase()).join(", ")}`),view.box);
      list.prepend(row);
      list.querySelector(".empty-small")?.remove();
      watching.add(job.job_id);
      follow(job,view,()=>row.isConnected && state.project?.id===pid)
        .then(done=>{if(done && state.project?.id===pid)return loadReports().then(()=>toast("보고서 초안을 생성했습니다."));})
        .catch(error=>view.update({...job,state:"FAILED",percent:job.percent},error.message))
        .finally(()=>watching.delete(job.job_id));
    }
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
  return {create,decorate,showActive};
})();
