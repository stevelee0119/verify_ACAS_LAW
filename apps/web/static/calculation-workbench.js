"use strict";

const calculationWorkbench = (() => {
  const dayBases = {"": "선택", "ACT/365F": "실제 일수 / 365일", "ACT/360": "실제 일수 / 360일", "ACT/ACT": "실제 일수 / 해당 연도 일수"};
  const roundingModes = {"": "선택", ROUND_HALF_UP: "사사오입", ROUND_HALF_EVEN: "동률이면 짝수로 반올림", ROUND_DOWN: "절사", ROUND_UP: "올림"};
  const roundingStages = {"": "선택", SEGMENT: "각 구간에서 반올림", FINAL: "총 발생이자에서 최종 반올림"};
  const paymentTimings = {"": "선택", START_OF_DAY: "변제일 시작: 당일 이자 발생 전", END_OF_DAY: "변제일 종료: 당일 이자 발생 후"};
  const endpoints = {"": "선택", true: "포함", false: "불포함"};
  const allocationPolicies = {"": "선택", EXPLICIT: "입력한 원금·이자 충당액 적용"};
  const projectKey = () => typeof state !== "undefined" ? state.project?.id ?? null : null;
  let syncProject = null;
  function onProjectChange() { return syncProject ? syncProject() : false; }
  const money = value => {
    const [whole, fraction] = String(value).split(".");
    return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (fraction === undefined ? "" : `.${fraction}`);
  };

  function init() {
    const panel = document.querySelector('[data-panel="calculations"]');
    if (!panel) return;
    if (panel.querySelector(".calculation-workbench")) { onProjectChange(); return; }
    if (!document.getElementById("calculationWorkbenchStyle")) {
      const style = node("style"); style.id = "calculationWorkbenchStyle";
      style.textContent = `
        .calculation-workbench{margin-top:24px;padding-top:20px;border-top:1px solid #cbd2d9;min-width:0;max-width:100%;letter-spacing:0}
        .calculation-workbench h2{font-size:20px;margin:0 0 16px}
        .calculation-workbench h3{font-size:16px;margin:0}
        .calculation-workbench h4{font-size:14px;margin:0}
        .calculation-workbench .calc-band{padding:18px 0;border-bottom:1px solid #e0e4e8;min-width:0}
        .calculation-workbench .calc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px;margin-top:12px;min-width:0}
        .calculation-workbench .calc-convention-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr))}
        .calculation-workbench label{display:flex;flex-direction:column;gap:6px;min-width:0;font-size:13px;overflow-wrap:anywhere}
        .calculation-workbench input,.calculation-workbench select{box-sizing:border-box;width:100%;min-width:0;max-width:100%;font-size:14px}
        .calculation-workbench .calc-source{grid-column:1/-1}
        .calculation-workbench .calc-heading,.calculation-workbench .calc-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
        .calculation-workbench .calc-entry{padding:16px 0;border-bottom:1px solid #e5e8eb;min-width:0}
        .calculation-workbench .calc-entry:last-child{border-bottom:0}
        .calculation-workbench .calc-actions{justify-content:flex-start;padding-top:16px}
        .calculation-workbench .calc-actions button{min-height:40px;white-space:normal;overflow-wrap:anywhere}
        .calculation-workbench .calc-confirm{flex-direction:row;align-items:flex-start;gap:10px;margin-top:16px;line-height:1.6}
        .calculation-workbench .calc-confirm input{width:18px;height:18px;flex:0 0 18px;margin-top:2px}
        .calculation-workbench .calc-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:16px;margin:16px 0}
        .calculation-workbench .calc-summary dt{font-size:13px;color:#525d68}
        .calculation-workbench .calc-summary dd{margin:6px 0 0;font-size:19px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
        .calculation-workbench .table-wrap{max-width:100%;overflow:auto}
        .calculation-workbench table{min-width:1080px;font-variant-numeric:tabular-nums}
        .calculation-workbench th:first-child,.calculation-workbench td:first-child{min-width:90px;white-space:nowrap}
        .calculation-workbench td{vertical-align:top;overflow-wrap:anywhere;max-width:340px}
        .calculation-workbench .calc-formula{font-size:12px;white-space:normal;overflow-wrap:anywhere;max-width:440px}
        .calculation-workbench .calc-status{min-height:24px;margin:12px 0;overflow-wrap:anywhere}
        .calculation-workbench .calc-error{color:#a52d35}
        .calculation-workbench .calc-stale{color:#815413}
        .calculation-workbench details{margin:16px 0}
        .calculation-workbench summary{cursor:pointer;font-weight:600}
        .calculation-workbench .calc-assumptions{display:grid;grid-template-columns:minmax(110px,1fr) minmax(0,3fr);gap:8px 16px;font-size:13px}
        .calculation-workbench .calc-assumptions dt,.calculation-workbench .calc-assumptions dd{margin:0;overflow-wrap:anywhere}
        @media(max-width:600px){.calculation-workbench .calc-grid{grid-template-columns:1fr}.calculation-workbench .calc-assumptions{grid-template-columns:1fr}.calculation-workbench .calc-heading{align-items:flex-start}}
      `;
      document.head.append(style);
    }
    const root = node("section", null, "calculation-workbench");
    root.setAttribute("aria-label", "기간별 이자 계산");
    const form = node("form"), controls = {}, rates = [], payments = [];
    let serial = 0, revision = 0, result = null, busy = false, ownerProject = projectKey();
    let requestSerial = 0, pendingController = null;
    const status = node("p", "", "calc-status"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const output = node("div"); output.dataset.calculationOutput = "true";
    const submit = node("button", "계산", "primary"); submit.type = "submit";
    const download = iconButton("download", "계산 감사표 JSON 내려받기", () => {
      if (!result || download.disabled) return;
      const blob = new Blob([JSON.stringify(result, null, 2)], {type:"application/json;charset=utf-8"});
      const url = URL.createObjectURL(blob), link = node("a");
      link.href = url; link.download = "interest-schedule.json";
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    download.disabled = true;

    function refreshIcons() { if (typeof icons === "function") icons(); }
    function dirty() {
      revision += 1;
      if (controls.user_confirmed) controls.user_confirmed.checked = false;
      download.disabled = true;
      if (result) { status.textContent = "입력이 변경되었습니다. 표시된 감사표는 이전 계산입니다."; status.className = "calc-status calc-stale"; }
    }
    function field(target, name, title, type = "text", options = null, required = true, value = "") {
      const wrapper = workflowUI.field(name, title, value, type, options);
      const input = wrapper.querySelector("input,select,textarea");
      input.required = required;
      if (type === "text" && !options) input.maxLength = name.includes("source") ? 2000 : 200;
      target[name] = input;
      return wrapper;
    }
    function decimalField(target, name, title) {
      const wrapper = field(target, name, title);
      target[name].inputMode = "decimal";
      target[name].pattern = "[0-9]+([.][0-9]+)?";
      target[name].maxLength = 42;
      return wrapper;
    }
    function band(title) {
      const section = node("section", null, "calc-band"), heading = node("div", null, "calc-heading");
      heading.append(node("h3", title)); section.append(heading); form.append(section);
      return {section, heading};
    }
    function sourceField(target, name, title) {
      const wrapper = field(target, name, title); wrapper.classList.add("calc-source"); return wrapper;
    }
    form.append(node("h2", "기간별 이자 계산"));
    const basis = band("원금·기간"), basisGrid = node("div", null, "calc-grid");
    basisGrid.append(decimalField(controls, "principal", "원금"), field(controls, "start_date", "계산 시작일", "date"),
      field(controls, "end_date", "계산 종료일", "date"), field(controls, "include_start", "시작일 이자 일수", "text", endpoints),
      field(controls, "include_end", "종료일 이자 일수", "text", endpoints),
      sourceField(controls, "principal_source", "원금 근거: 문서·쪽수·확인 내용"),
      sourceField(controls, "period_source", "기간 근거: 문서·쪽수·확인 내용"));
    basis.section.append(basisGrid);
    const rateBand = band("이율 구간"), rateRows = node("div"); rateBand.section.append(rateRows);
    const paymentBand = band("원금·이자 변제"), paymentRows = node("div"); paymentBand.section.append(paymentRows);
    const emptyPayments = node("p", "변제 내역 없음", "muted"); paymentRows.append(emptyPayments);

    function renumber(rows, title) { rows.forEach((row, index) => { row.heading.textContent = `${title} ${index + 1}`; }); }
    function addRow(kind, markDirty = true) {
      const isRate = kind === "rate", list = isRate ? rates : payments;
      const target = isRate ? rateRows : paymentRows;
      const row = {inputs:{}, id:++serial}, container = node("div", null, "calc-entry"); row.container = container;
      container.dataset.rowKind = kind;
      row.heading = node("h4", `${isRate ? "이율 구간" : "변제"} ${list.length + 1}`);
      const heading = node("div", null, "calc-heading"), grid = node("div", null, "calc-grid");
      heading.append(row.heading, iconButton("trash-2", isRate ? "이율 구간 삭제" : "변제 삭제", () => {
        list.splice(list.indexOf(row), 1); container.remove(); renumber(list, isRate ? "이율 구간" : "변제");
        emptyPayments.hidden = payments.length > 0; dirty();
      }));
      if (isRate) {
        grid.append(field(row.inputs, "start_date", "구간 시작일 (포함)", "date"), field(row.inputs, "end_date", "구간 종료일 (불포함)", "date"),
          decimalField(row.inputs, "annual_rate_percent", "연 이율 (%)"), sourceField(row.inputs, "source", "이율 근거: 문서·쪽수·적용 전제"));
      } else {
        grid.append(field(row.inputs, "payment_id", "변제 식별자"), field(row.inputs, "paid_on", "변제일", "date"),
          decimalField(row.inputs, "amount", "변제 총액"), decimalField(row.inputs, "principal", "원금 충당액"),
          decimalField(row.inputs, "interest", "이자 충당액"), sourceField(row.inputs, "source", "변제·충당 근거: 문서·쪽수·확인 내용"));
      }
      for (const [name, input] of Object.entries(row.inputs)) input.name = `${kind}_${row.id}_${name}`;
      container.append(heading, grid); target.append(container); list.push(row);
      emptyPayments.hidden = payments.length > 0;
      if (markDirty) dirty();
      refreshIcons();
    }
    rateBand.heading.append(button("이율 구간 추가", () => addRow("rate")));
    paymentBand.heading.append(button("변제 추가", () => addRow("payment")));
    addRow("rate", false);

    const conventions = band("계산 기준 확인"), conventionGrid = node("div", null, "calc-grid");
    conventionGrid.classList.add("calc-convention-grid");
    conventionGrid.append(field(controls, "day_count_convention", "연 일수 기준", "text", dayBases),
      field(controls, "rounding", "단수 처리", "text", roundingModes), decimalField(controls, "rounding_quantum", "단수 처리 단위"),
      field(controls, "rounding_stage", "단수 처리 시점", "text", roundingStages),
      field(controls, "payment_timing", "변제 반영 시점", "text", paymentTimings),
      field(controls, "allocation_policy", "변제 충당 기준", "text", allocationPolicies),
      sourceField(controls, "convention_source", "일수·단수·변제 반영 기준의 근거와 전제"),
      field(controls, "confirmed_by", "입력·계산 기준 확인자"));
    const confirmation = field(controls, "user_confirmed", "원금·기간·이율·변제 충당액·계산 기준과 출처를 확인했습니다.", "checkbox", null, true, false);
    confirmation.classList.add("calc-confirm");
    confirmation.prepend(controls.user_confirmed);
    conventions.section.append(conventionGrid, confirmation);
    const actions = node("div", null, "calc-actions");
    actions.append(submit, download, iconButton("rotate-ccw", "계산 입력 초기화", () => reset()));
    form.append(actions, status); root.append(form, output); panel.append(root);

    function reset() {
      requestSerial += 1;
      pendingController?.abort(); pendingController = null;
      busy = false; submit.disabled = false;
      form.reset(); rates.splice(0); payments.splice(0); rateRows.replaceChildren(); paymentRows.replaceChildren(emptyPayments);
      result = null; revision += 1; output.replaceChildren(); status.textContent = "";
      status.className = "calc-status";
      download.disabled = true; ownerProject = projectKey(); addRow("rate", false);
    }
    form.addEventListener("input", event => { if (event.target !== controls.user_confirmed) dirty(); });
    form.addEventListener("change", event => {
      if (event.target !== controls.user_confirmed) dirty();
      else { revision += 1; if (!controls.user_confirmed.checked) download.disabled = true; }
    });

    function values(row) { return Object.fromEntries(Object.entries(row.inputs).map(([name, input]) => [name, input.value.trim()])); }
    function payload() {
      const choice = name => controls[name].value;
      return {
        principal: choice("principal").trim(), start_date: choice("start_date"), end_date: choice("end_date"),
        rate_periods: rates.map(values), payments: payments.map(values),
        assumptions: {
          day_count_convention: choice("day_count_convention"), include_start: choice("include_start") === "true",
          include_end: choice("include_end") === "true", rounding: choice("rounding"), rounding_quantum: choice("rounding_quantum").trim(),
          rounding_stage: choice("rounding_stage"), payment_timing: choice("payment_timing"), allocation_policy: choice("allocation_policy"),
          principal_source: choice("principal_source").trim(), period_source: choice("period_source").trim(),
          convention_source: choice("convention_source").trim(), confirmed_by: choice("confirmed_by").trim(),
          user_confirmed: controls.user_confirmed.checked,
        },
      };
    }
    function renderResult(data) {
      output.replaceChildren(node("h3", "계산 감사표"));
      const summary = node("dl", null, "calc-summary");
      for (const [title, value] of [["발생이자", data.accrued_interest], ["잔여 원금", data.remaining_principal],
        ["미지급 이자", data.remaining_interest], ["원금·이자 잔액 합계", data.total_due]]) {
        const item = node("div"); item.append(node("dt", title), node("dd", money(value))); summary.append(item);
      }
      output.append(summary, node("p", `${data.days}일 · 이자 발생일 ${data.accrual_start} (포함) ~ ${data.accrual_end_exclusive} (불포함)`));
      const rows = data.schedule.map(row => {
        const accrual = row.kind === "ACCRUAL", rounding = row.kind === "ROUNDING", formula = node("div");
        formula.append(node("p", accrual ? `${money(row.principal_before)} × ${row.annual_rate_percent}% × ${row.days} / ${row.year_denominator}`
          : rounding ? "총 발생이자에 최종 단수 처리" : `원금 충당 ${money(row.principal_paid)} / 이자 충당 ${money(row.interest_paid)}`, "calc-formula"));
        if (accrual) formula.append(node("small", `처리 전 이자 ${row.raw_interest}`, "calc-formula"));
        return [accrual ? "이자" : rounding ? "단수 처리" : `변제 ${row.payment_id}`, accrual ? `${row.start_date} ≤ 일자 < ${row.end_date}` : row.start_date,
          String(row.days), money(row.principal_after), accrual || rounding ? money(row.posted_interest) : "-", money(row.interest_balance), formula, row.source];
      });
      output.append(workflowUI.table(["항목", "발생 구간 / 반영일", "일수", "구간 후 원금", "발생이자", "미지급 이자", "산식 / 충당", "근거"], rows));
      const details = node("details"), assumptionsList = node("dl", null, "calc-assumptions"), a = data.assumptions;
      details.append(node("summary", "확인된 계산 기준·출처"));
      const pairs = [
        ["계산 범위", "단리 산술 계산 · 입력과 적용법의 타당성은 별도 검토"],
        ["계산 시작일", `${data.start_date} (${a.include_start ? "포함" : "불포함"})`],
        ["계산 종료일", `${data.end_date} (${a.include_end ? "포함" : "불포함"})`],
        ["연 일수 기준", dayBases[a.day_count_convention]], ["단수 처리", `${roundingModes[a.rounding]} / ${a.rounding_quantum} 단위 / ${roundingStages[a.rounding_stage]}`],
        ["변제 반영", paymentTimings[a.payment_timing]], ["충당 기준", allocationPolicies[a.allocation_policy]],
        ["단수 처리 조정액", data.rounding_adjustment], ["원금 근거", a.principal_source], ["기간 근거", a.period_source],
        ["계산 기준 근거", a.convention_source], ["확인자", a.confirmed_by],
      ];
      for (const [title, value] of pairs) assumptionsList.append(node("dt", title), node("dd", value));
      details.append(assumptionsList); output.append(details);
    }
    form.onsubmit = action(async event => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      if (ownerProject !== projectKey()) { reset(); status.textContent = "사건이 변경되어 계산 입력을 초기화했습니다."; return; }
      const requestedRevision = revision, requestedProject = ownerProject;
      const requestId = ++requestSerial, controller = new AbortController();
      pendingController = controller;
      busy = true; submit.disabled = true; download.disabled = true;
      status.textContent = "계산 중"; status.className = "calc-status";
      try {
        const data = await api("/calculations/interest/segmented", {method:"POST", body:payload(), signal:controller.signal});
        if (requestId !== requestSerial) return;
        if (requestedRevision !== revision || requestedProject !== projectKey()) {
          status.textContent = "계산 중 입력 또는 사건이 변경되었습니다. 다시 확인 후 계산하세요."; status.className = "calc-status calc-stale"; return;
        }
        result = data; renderResult(data); download.disabled = false; status.textContent = "계산 완료";
      } catch (error) {
        if (requestId !== requestSerial) return;
        status.textContent = error.message; status.className = "calc-status calc-error";
      } finally {
        if (requestId === requestSerial) { busy = false; submit.disabled = false; pendingController = null; }
      }
    });
    syncProject = () => {
      if (ownerProject === projectKey()) return false;
      reset();
      return true;
    };
    document.addEventListener("acas-project-changed", onProjectChange);
    window.addEventListener("acas-project-changed", onProjectChange);
    new MutationObserver(() => { if (!panel.hidden) onProjectChange(); }).observe(panel, {attributes:true, attributeFilter:["hidden"]});
    refreshIcons();
  }
  return {init, onProjectChange, sync:onProjectChange};
})();
