"""실행 매니페스트(run_manifest, v4 P0).

엔진마다 '실행했는지, 무엇을 몇 건 넣었는지, finding을 몇 건 만들었는지, 얼마나 걸렸는지, 건너뛰었다면 왜인지'를
남긴다. 결과가 0건일 때 '실행했는데 없음'과 '실행하지 않음'을 구분하기 위해서다.
- 문서 단위 엔진은 문서마다 기록하고 엔진별로 합산한다(documents에 문서별 내역).
- finding 수는 그 단계가 결과 목록에 더한 건수다. 뒤의 병합·중복 제거(finalize) 전 값이다.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional


class StageHandle:
    """한 번의 단계 실행. 본문에서 입력 건수·건너뛴 사유·오류를 채운다."""

    def __init__(self, inputs: Optional[int]) -> None:
        self.inputs = inputs
        self.skip_reason: Optional[str] = None
        self.error: Optional[str] = None
        self.findings: Optional[int] = None  # 결과 목록 길이로 셀 수 없는 단계가 직접 적는다
        self.note: Optional[str] = None


class RunManifest:
    def __init__(self) -> None:
        self.engines: Dict[str, Dict[str, Any]] = {}
        self.order: List[str] = []

    def _record(self, name: str) -> Dict[str, Any]:
        if name not in self.engines:
            self.order.append(name)
            self.engines[name] = {"executed": False, "runs": 0, "skipped_runs": 0, "inputs": 0, "findings": 0,
                                  "seconds": 0.0, "skip_reasons": [], "errors": [], "documents": []}
        return self.engines[name]

    @contextmanager
    def stage(self, name: str, findings: List[Any], *, inputs: Optional[int] = None,
              document_id: Optional[str] = None) -> Iterator[StageHandle]:
        record = self._record(name)
        handle = StageHandle(inputs)
        before = len(findings)
        started = time.perf_counter()
        try:
            yield handle
        except Exception as exc:
            handle.error = f"{type(exc).__name__}"
            raise
        finally:
            elapsed = time.perf_counter() - started
            added = handle.findings if handle.findings is not None else max(0, len(findings) - before)
            entry: Dict[str, Any] = {"document_id": document_id, "inputs": handle.inputs, "findings": added,
                                     "seconds": round(elapsed, 3)}
            if handle.skip_reason:
                record["skipped_runs"] += 1
                entry["skipped"] = handle.skip_reason
                if handle.skip_reason not in record["skip_reasons"]:
                    record["skip_reasons"].append(handle.skip_reason)
            else:
                record["executed"] = True
                record["runs"] += 1
            if handle.error:
                entry["error"] = handle.error
                record["errors"].append(f"{document_id or 'project'}: {handle.error}")
            if handle.note:
                entry["note"] = handle.note
            record["inputs"] += int(handle.inputs or 0)
            record["findings"] += added
            record["seconds"] += elapsed
            record["documents"].append(entry)

    def skip(self, name: str, reason: str, *, document_id: Optional[str] = None) -> None:
        with self.stage(name, [], document_id=document_id) as handle:
            handle.skip_reason = reason

    def to_dict(self, versions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """versions: 이 실행에 쓰인 프로그램·규칙·프롬프트·모델 설정 버전. 같은 문서의 결과가 달라졌을 때
        어느 버전 변화 때문인지 매니페스트만으로 추적할 수 있게 함께 남긴다."""
        engines = {}
        for name in self.order:
            record = dict(self.engines[name])
            record["seconds"] = round(record["seconds"], 3)
            engines[name] = record
        return {
            "schema": 1,
            "versions": dict(versions or {}),
            "engines": engines,
            "not_executed": [name for name in self.order if not self.engines[name]["executed"]],
            "note": ("findings는 각 단계가 결과 목록에 더한 건수(병합·중복 제거 전)다. executed=false는 그 엔진이 "
                     "어떤 문서에서도 실행되지 않았다는 뜻이고, 사유는 skip_reasons에 있다."),
        }
