"""기록 보완: Drive 상태 블록 상시 기록, 모든 AI 호출의 실행 기록 집계, 교차검토 묶음 크기."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from packages.common.config import get_settings
from packages.llm_router.router import ModelExecution, RouterResult
from packages.verification_engine.pipeline import (VerificationPipeline, VerificationRunResult, execution_summary,
                                                   reference_health)


# --- Drive health: 꺼져 있어도 사유가 남는다 ---------------------------------------------------------------
@pytest.mark.parametrize("env, mode", [
    ({}, "none"),
    ({"LV_DRIVE_API_KEY": "secret-drive-key-value"}, "api_key"),
    ({"LV_DRIVE_SERVICE_ACCOUNT_FILE": "/secret/sa.json", "LV_DRIVE_API_KEY": "secret-drive-key-value"}, "service_account"),
])
def test_health_is_recorded_when_drive_is_disabled(monkeypatch, env, mode):
    for key in ("LV_DRIVE_API_KEY", "LV_DRIVE_SERVICE_ACCOUNT_FILE"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    doc = SimpleNamespace(document_id="d", filename="a.pdf", engine_data={})
    health = reference_health({"status": "DISABLED", "folder_id": ""}, [doc], replace(get_settings(), allow_network=True))
    assert health["enabled"] is False and health["disabled_reason"] == "LV_RAG_DRIVE_FOLDER_ID_NOT_SET"
    assert health["credential_mode"] == mode and health["network_allowed"] is True
    assert health["documents"][0]["status"] == "DISABLED" and health["documents"][0]["drive_used"] is False
    assert "secret-drive-key-value" not in str(health) and "/secret" not in str(health)


def test_pipeline_manifest_always_has_health(tmp_path, registry):
    from helpers import make_docx
    from packages.common.enums import VerificationProfile
    from packages.common.storage import sha256_file
    from packages.verification_engine.pipeline import DocumentInput, ProjectContext
    path = make_docx(tmp_path / "document.docx", ["손해배상 청구에 관한 준비서면이다."])
    pipeline = VerificationPipeline(registry=registry)
    pipeline.settings = replace(get_settings(), rag_drive_folder_id="", allow_network=False)
    result = pipeline.run("health-off", ProjectContext("p", profile=VerificationProfile.QUICK),
                          [DocumentInput("doc", str(path), path.name, sha256=sha256_file(path))])
    health = result.run_manifest["reference_library"]["health"]
    assert health["enabled"] is False and health["disabled_reason"] == "LV_RAG_DRIVE_FOLDER_ID_NOT_SET"
    assert "model_execution_summary" in result.run_manifest


# --- AI 실행 기록: 라우터 훅에서 빠짐없이 ------------------------------------------------------------------
def execution(provider, ok=True, error=""):
    return ModelExecution("PRIMARY_REASONER", provider, f"{provider}-model", ok, error=error)


def test_every_router_call_is_collected_and_previous_hook_still_runs():
    forwarded = []
    router = SimpleNamespace(on_execution=forwarded.append)
    pipeline = VerificationPipeline.__new__(VerificationPipeline)
    pipeline.router = router

    def fake_run(run_id, context, documents, **kwargs):
        pipeline._execution_document = "doc-1"
        router.on_execution(execution("anthropic"))
        router.on_execution(execution("openai", ok=False, error="PROVIDER_TIMEOUT: 시간 초과"))
        pipeline._execution_document = None
        router.on_execution(execution("gemini"))
        return VerificationRunResult(run_id="r", project_id="p", state="COMPLETED", verification_key="k")

    pipeline._run = fake_run
    result = pipeline.run("r", SimpleNamespace(), [])
    assert [e["provider"] for e in result.model_executions] == ["anthropic", "openai", "gemini"]
    assert [e["document_id"] for e in result.model_executions] == ["doc-1", "doc-1", None]
    assert len(forwarded) == 3 and router.on_execution == forwarded.append
    summary = result.run_manifest["model_execution_summary"]
    assert summary["calls"] == 3 and summary["providers"]["openai"]["failed"] == 1


@pytest.mark.parametrize("log, calls, failed", [
    ([], 0, {}),
    ([{"provider": "a", "ok": True}, {"provider": "a", "ok": False, "error": "X"}], 2, {"a": 1}),
    ([{"provider": "b", "ok": False, "error": "E" * 200}, {"provider": "c", "ok": False}], 2, {"b": 1, "c": 1}),
])
def test_execution_summary_counts(log, calls, failed):
    summary = execution_summary(log)
    assert summary["calls"] == calls
    assert {k: v["failed"] for k, v in summary["providers"].items() if v["failed"]} == failed
    assert all(len(reason) <= 80 for v in summary["providers"].values() for reason in v["errors"])


# --- 교차검토 묶음 크기 -------------------------------------------------------------------------------
@pytest.mark.parametrize("count, requests", [(1, 1), (3, 2), (5, 3)])
def test_cross_check_asks_at_most_two_citations_per_request(count, requests):
    from packages.common.enums import ExternalAIPolicy
    from packages.legal_engine import argument_validity_verifier as module
    sent = []

    class Router:
        async def consult_all(self, role, request, **kwargs):
            sent.append(request)
            return [RouterResult(used=True, parsed={"rows": []}, executions=[execution("anthropic")])]

    cases = [{"citation": SimpleNamespace(page=1, raw_text=f"가상 인용 {i}"), "basis": "UNCONFIRMED",
              "context": "문맥"} for i in range(count)]
    result = module.ArgumentValidityResult()
    asyncio.run(module._attach_ai_opinions(result, cases, Router(), ExternalAIPolicy.MASKED, None))
    assert len(sent) == requests
    assert all(len(__import__("json").loads(r.user)["items"]) <= 2 for r in sent)
