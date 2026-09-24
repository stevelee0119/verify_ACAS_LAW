"""AI 작성 판별에서 모델마다 결론과 설명이 모두 보여야 한다."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
GATE = {"release_gate": "BLOCK", "hallucination_risk": 72,
        "hard_block_reasons": ["성립할 수 없는 사건번호 인용 1건", "은닉 텍스트 2건 발견", "Source 미확인 판례가 핵심 주장의 근거"],
        "review_reasons": ["공식 DB 미확인 인용 4건", "AI 작성 정황(일부)", "계산 결과 불일치 1건"],
        "risk_index_note": "검증위험 지수는 확률이 아니라 규칙 기반 점수입니다."}


DETECTOR = {
    "verdict": "AI_PARTIAL_GENERATION", "score": 0.72, "used_llm": True,
    "reasons": ["모델 간 판단 불일치: anthropic=UNCERTAIN, openai=AI_PARTIAL_GENERATION, gemini=AI_FULL_GENERATION_LIKELY. 과반이 지지하는 판단을 택함",
                "[anthropic] 표준 임대차계약서 양식임", "[anthropic] 챗봇 상투구 없음",
                "[openai] 띄어쓰기가 부자연스러움", "[gemini] 면책 문구가 전형적임", "[gemini] 예시 목적의 합성 텍스트"],
    "signals": {"llm_agreement": "DISAGREE", "llm_failures": {},
                "llm_opinions": [
                    {"provider": "anthropic", "model": "claude-opus-5-5", "verdict": "UNCERTAIN", "score": 0.4,
                     "reasons": ["표준 임대차계약서 양식임", "챗봇 상투구 없음"]},
                    {"provider": "openai", "model": "gpt-4.1", "verdict": "AI_PARTIAL_GENERATION", "score": 0.72,
                     "reasons": ["띄어쓰기가 부자연스러움"]},
                    {"provider": "gemini", "model": "gemini-3.8-flash", "verdict": "AI_FULL_GENERATION_LIKELY", "score": 0.95,
                     "reasons": ["면책 문구가 전형적임", "예시 목적의 합성 텍스트"]}]},
}
SINGLE = {"verdict": "UNCERTAIN", "score": 0.3, "used_llm": True, "reasons": ["[gemini] 면책 문구"],
          "signals": {"llm_opinions": [{"provider": "gemini", "model": "m", "verdict": "AI_FULL_GENERATION_LIKELY",
                                        "score": 0.95, "reasons": ["면책 문구"]}],
                      "llm_failures": {"openai": "응답이 출력 보안 검사에서 격리됨(주민등록번호 형식의 숫자 포함)"},
                      "llm_failure_models": {"openai": "gpt-6-luna"}}}


@pytest.mark.parametrize("width,height", [(1440, 1400), (390, 2400)])
def test_each_model_verdict_and_explanation_is_shown(width, height):
    static = ROOT / "apps/web/static"
    files = {f"/static/{p.relative_to(static).as_posix()}": p for p in static.rglob("*") if p.is_file()}
    files["/"] = ROOT / "apps/web/index.html"
    run = {"id": "r1", "project_id": "p1", "state": "COMPLETED", "progress": 1, "stage_message": "",
           "document_ids": ["d"], "scores": {}, "unverified_items": [],
           "input_snapshot": {"scope_revision": 0}, "started_at": "2026-09-23T00:00:00"}
    project = {"id": "p1", "name": "시험 사건", "can_delete": True, "document_count": 2,
               "external_ai_policy": "MASKED", "scope_revision": 0}
    result = {"documents": [{"filename": "first.png", "ai_detector_result": DETECTOR},
                            {"filename": "second.png", "ai_detector_result": SINGLE}]}

    def respond(route):
        path = urlsplit(route.request.url).path
        if path in files:
            return route.fulfill(path=str(files[path]))
        replies = {"/api/health": {"status": "ok", "version": "0.5.0"},
                   "/api/identity/me": {"user_id": "u", "role": "ADMIN", "authentication": "password"},
                   "/api/verification-runs": {"active_count": 0, "runs": []},
                   "/api/projects": [project], "/api/projects/p1": project, "/api/projects/p1/runs": [run]}
        if path in replies:
            return route.fulfill(json=replies[path])
        if path.endswith("/result"):
            return route.fulfill(json=result)
        if path.endswith("/case-matrix"):
            return route.fulfill(body="null", content_type="application/json")
        return route.fulfill(json=[])

    with sync_playwright() as playwright:
        options = {"headless": True}
        if os.getenv("LV_TEST_BROWSER_CHANNEL"):
            options["channel"] = os.environ["LV_TEST_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.route("**/*", respond)
            page.goto("http://models.test/")
            page.wait_for_function("state.result && state.result.documents && state.result.documents.length === 2")
            page.evaluate("switchTab('ai-verification')")
            cards = page.locator("#aiSummaryCards")
            first = cards.locator(".card-item").nth(0)
            expect(first.locator(".model-opinion")).to_have_count(3)
            for provider, reasons in (("Anthropic", ["표준 임대차계약서 양식임", "챗봇 상투구 없음"]),
                                      ("OpenAI", ["띄어쓰기가 부자연스러움"]),
                                      ("Gemini", ["면책 문구가 전형적임", "예시 목적의 합성 텍스트"])):
                block = first.locator(".model-opinion", has_text=provider)
                expect(block).to_be_visible()
                for reason in reasons:
                    expect(block.get_by_text(reason, exact=True)).to_be_visible()
            expect(first.locator(".model-opinion", has_text="Gemini")).to_contain_text("AI 임의 전체 작성 유력")
            expect(first.locator(".model-opinion", has_text="OpenAI")).to_contain_text("일부 AI 작성")
            # 모델별 판정에 공급자와 모델명을 함께 적는다.
            expect(first.locator(".model-opinion-head strong")).to_have_text(
                ["Anthropic · Claude Opus 5.5", "OpenAI · GPT-4.1", "Gemini · Gemini 3.8 Flash"])
            # 모델 설명은 모델 블록에만 한 번 나온다(요약 목록에 중복하지 않는다).
            expect(first.get_by_text("띄어쓰기가 부자연스러움")).to_have_count(1)
            expect(first).to_contain_text("과반이 지지하는 판단을 택함")
            second = cards.locator(".card-item").nth(1)
            expect(second.locator(".model-opinion", has_text="Gemini")).to_contain_text("면책 문구")
            expect(second.locator(".model-opinion-failed")).to_contain_text("주민등록번호 형식의 숫자 포함")
            expect(second.locator(".model-opinion-failed strong")).to_have_text("OpenAI · GPT-6 Luna")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.close()
        finally:
            browser.close()
