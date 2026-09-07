"""외부 Source·LLM Provider 실연동 점검.

이그레스가 열린 환경(GitHub Actions 등)에서 실행해 다음을 확인한다.
- 어떤 Secret이 실제로 주입되었는가 (이름만, 값은 절대 출력하지 않는다)
- Adapter가 READY로 전환되는가
- 실제 호출이 성공하고 응답이 내부 표준 형태로 정규화되는가

값은 어떤 경로로도 출력하지 않는다. 길이와 존재 여부만 보고한다.
LLM 점검은 최소 토큰으로 수행하며 --with-llm 을 준 경우에만 호출한다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.common.config import get_settings  # noqa: E402
from packages.common.enums import AdapterStatus  # noqa: E402

# 출력에 섞여 들어갈 수 있는 비밀값 형태를 지운다(이중 안전장치).
SECRET_LIKE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{10,}|"
    r"Bearer\s+[A-Za-z0-9._\-]{10,}|[?&](OC|key|apiKey|api_key)=[^&\s\"']+)"
)

SECRET_ENVS = [
    ("LV_LAW_GO_KR_OC", "국가법령정보 공동활용 OC", "판례·법령 공식 검증"),
    ("LV_KCI_KEY", "KCI Open API Key", "국내 학술자료 검증"),
    ("LV_CROSSREF_MAILTO", "Crossref 연락처", "국제 문헌 교차검증 우선순위"),
    ("LV_SEMANTIC_SCHOLAR_KEY", "Semantic Scholar Key", "학술 검증 한도 상향(선택)"),
    ("OPENAI_API_KEY", "OpenAI API Key", "LLM 역할 분담"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key", "독립 Critic"),
    ("GEMINI_API_KEY", "Gemini API Key", "Grounded Search"),
]


def sanitize(text: Any, limit: int = 240) -> str:
    cleaned = SECRET_LIKE.sub("[REDACTED]", str(text))
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


@dataclass
class CheckResult:
    name: str
    category: str
    configured: bool
    status: str
    ok: bool
    detail: str = ""
    records: Optional[int] = None
    fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
def check_secrets() -> List[CheckResult]:
    out: List[CheckResult] = []
    for env_name, label, purpose in SECRET_ENVS:
        value = os.getenv(env_name) or ""
        out.append(
            CheckResult(
                name=env_name,
                category="secret",
                configured=bool(value),
                status="주입됨" if value else "없음",
                ok=bool(value),
                detail=f"{label} — {purpose}" + (f" (길이 {len(value)})" if value else ""),
            )
        )
    return out


def check_adapters(registry) -> List[CheckResult]:
    out: List[CheckResult] = []
    for state in registry.states():
        out.append(
            CheckResult(
                name=state.name,
                category="adapter_status",
                configured=state.status == AdapterStatus.READY,
                status=str(state.status),
                ok=state.status == AdapterStatus.READY,
                detail=sanitize(state.note),
            )
        )
    return out


def _payload_shape(payload: Any, depth: int = 0, max_keys: int = 14) -> str:
    """응답의 구조만 스케치한다. 값은 넣지 않고 키 이름과 타입만 남긴다.

    호출은 성공했는데 정규화가 0건이면 응답 형식이 매핑과 다르다는 뜻이므로,
    한 번의 실행으로 원인을 알 수 있도록 구조를 보고한다.
    """
    if depth > 2:
        return "…"
    if isinstance(payload, dict):
        keys = list(payload.keys())[:max_keys]
        inner = ", ".join(f"{k}:{_payload_shape(payload[k], depth + 1)}" for k in keys)
        more = "…" if len(payload) > max_keys else ""
        return "{" + inner + more + "}"
    if isinstance(payload, list):
        return f"[{len(payload)}×{_payload_shape(payload[0], depth + 1) if payload else 'empty'}]"
    return type(payload).__name__


def _diagnose(response: Any) -> str:
    """실패·0건일 때 원인 파악에 필요한 정보를 만든다."""
    if response.records:
        return "정규화 성공"
    if response.message:
        return sanitize(response.message)
    record = getattr(response, "source_record", None)
    payload = (record.payload if record else {}) or {}
    if payload:
        return sanitize("응답은 왔으나 정규화 0건. 응답 구조 = " + _payload_shape(payload), 400)
    return "응답은 왔으나 결과 0건"


def _record_fields(records: List[Dict[str, Any]]) -> List[str]:
    if not records:
        return []
    return sorted(k for k, v in records[0].items() if k != "raw" and v not in (None, "", []))


def check_law_go_kr(registry) -> List[CheckResult]:
    """국가법령정보 실호출. 특정 판례의 존재를 단정하지 않고 응답 형태만 확인한다."""
    out: List[CheckResult] = []
    adapter = registry.law

    response = adapter.search_law("형법")
    out.append(
        CheckResult(
            name="law_go_kr:법령검색(형법)",
            category="live_legal",
            configured=adapter.status() == AdapterStatus.READY,
            status=str(response.status),
            ok=response.status == AdapterStatus.READY,
            detail=_diagnose(response),
            records=len(response.records),
            fields=_record_fields(response.records),
        )
    )

    response = adapter.search_case("손해배상")
    out.append(
        CheckResult(
            name="law_go_kr:판례검색(키워드)",
            category="live_legal",
            configured=adapter.status() == AdapterStatus.READY,
            status=str(response.status),
            ok=response.status == AdapterStatus.READY,
            detail=_diagnose(response),
            records=len(response.records),
            fields=_record_fields(response.records),
        )
    )
    return out


def check_academic(registry) -> List[CheckResult]:
    out: List[CheckResult] = []
    queries = {"kci": "형법", "openalex": "criminal law", "semantic_scholar": "criminal law",
               "crossref": "criminal law"}
    for adapter in registry.academic:
        response = adapter.search(queries.get(adapter.name, "law"))
        out.append(
            CheckResult(
                name=adapter.name,
                category="live_academic",
                configured=adapter.status() == AdapterStatus.READY,
                status=str(response.status),
                ok=response.status == AdapterStatus.READY,
                detail=_diagnose(response),
                records=len(response.records),
                fields=_record_fields(response.records),
            )
        )
    return out


async def check_llm(include: bool) -> List[CheckResult]:
    """최소 토큰으로 각 Provider를 1회 호출한다."""
    from packages.llm_router import LLMRequest, build_providers

    out: List[CheckResult] = []
    for name, provider in build_providers().items():
        if provider.config.kind == "local":
            continue
        configured = provider.config.has_key
        if not include:
            out.append(
                CheckResult(name=name, category="llm", configured=configured,
                            status="SKIPPED", ok=False,
                            detail=f"모델 {provider.config.model} — --with-llm 미지정으로 호출하지 않음"))
            continue
        if not provider.available:
            out.append(
                CheckResult(name=name, category="llm", configured=configured,
                            status="MISSING_KEY" if not configured else "DISABLED", ok=False,
                            detail=f"모델 {provider.config.model} — 키 없음 또는 비활성"))
            continue

        request = LLMRequest(
            system="You are a connectivity probe. Answer with a single digit only.",
            user="Reply with the digit 1 and nothing else.",
            max_tokens=8,
            temperature=0.0,
        )
        response = await provider.generate(request)
        out.append(
            CheckResult(
                name=name,
                category="llm",
                configured=configured,
                status="OK" if response.ok else "ERROR",
                ok=response.ok,
                detail=(
                    f"모델 {response.model or provider.config.model}"
                    + (f" — 응답 {sanitize(response.text, 40)!r}, "
                       f"토큰 in {response.input_tokens}/out {response.output_tokens}, "
                       f"{response.latency_ms}ms" if response.ok else f" — {sanitize(response.error)}")
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
def render_markdown(groups: Dict[str, List[CheckResult]]) -> str:
    lines: List[str] = ["# 외부 Source 실연동 점검 결과", ""]
    settings = get_settings()
    lines += [
        f"- 규칙 버전 `{settings.rule_version}` / 프롬프트 `{settings.prompt_version}`",
        f"- 네트워크 허용: `{settings.allow_network}`",
        "",
        "## 1. Secret 주입 상태",
        "",
        "| 환경변수 | 상태 | 용도 |",
        "|---|---|---|",
    ]
    for item in groups["secret"]:
        mark = "✅ 주입됨" if item.ok else "⚪ 없음"
        lines.append(f"| `{item.name}` | {mark} | {item.detail} |")

    lines += ["", "## 2. Adapter 상태", "", "| Source | 상태 | 비고 |", "|---|---|---|"]
    for item in groups["adapter_status"]:
        mark = "✅" if item.ok else "⚠️"
        lines.append(f"| `{item.name}` | {mark} {item.status} | {item.detail or '-'} |")

    lines += ["", "## 3. 실제 호출 결과", "", "| 대상 | 결과 | 건수 | 정규화된 필드 | 비고 |", "|---|---|---|---|---|"]
    for key in ("live_legal", "live_academic"):
        for item in groups.get(key, []):
            mark = "✅" if item.ok else ("⚪" if not item.configured else "❌")
            fields = ", ".join(f"`{f}`" for f in item.fields[:6]) or "-"
            lines.append(
                f"| `{item.name}` | {mark} {item.status} | {item.records if item.records is not None else '-'} "
                f"| {fields} | {item.detail or '-'} |"
            )

    lines += ["", "## 4. LLM Provider", "", "| Provider | 결과 | 비고 |", "|---|---|---|"]
    for item in groups.get("llm", []):
        mark = "✅" if item.ok else ("⚪" if item.status in ("SKIPPED", "MISSING_KEY") else "❌")
        lines.append(f"| `{item.name}` | {mark} {item.status} | {item.detail} |")

    failures = [i for g in groups.values() for i in g
                if i.category != "secret" and i.configured and not i.ok and i.status != "SKIPPED"]
    lines += ["", "## 판정", ""]
    if failures:
        lines.append(f"❌ 키가 설정되었는데도 실패한 항목 **{len(failures)}건**")
        for item in failures:
            lines.append(f"- `{item.name}` — {item.status}: {item.detail}")
    else:
        lines.append("✅ 설정된 Source가 모두 정상 응답했다. 키 미설정 항목은 설계대로 UNVERIFIED로 남는다.")
    lines += [
        "",
        "> 비밀값은 어떤 항목에도 출력되지 않는다. 존재 여부와 길이만 기록한다.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="외부 Source·LLM 실연동 점검")
    parser.add_argument("--with-llm", action="store_true", help="LLM Provider를 실제로 1회 호출한다(소액 과금)")
    parser.add_argument("--json-out", default="", help="결과 JSON 저장 경로")
    parser.add_argument("--strict", action="store_true", help="설정된 Source가 실패하면 종료코드 1")
    args = parser.parse_args()

    from packages.source_adapters import SourceRegistry

    registry = SourceRegistry()
    groups: Dict[str, List[CheckResult]] = {
        "secret": check_secrets(),
        "adapter_status": check_adapters(registry),
        "live_legal": check_law_go_kr(registry),
        "live_academic": check_academic(registry),
        "llm": asyncio.run(check_llm(args.with_llm)),
    }

    markdown = render_markdown(groups)
    print(markdown)

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")

    if args.json_out:
        payload = {key: [item.to_dict() for item in items] for key, items in groups.items()}
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    failures = [i for g in groups.values() for i in g
                if i.category != "secret" and i.configured and not i.ok and i.status != "SKIPPED"]
    return 1 if (failures and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
