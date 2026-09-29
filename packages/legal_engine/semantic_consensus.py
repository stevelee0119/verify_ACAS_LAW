"""Conservative structured aggregation; quote presence does not prove entailment."""


def semantic_consensus(stages, *, grounded, executions=()):
    """비모델 단계(deterministic)와 모델 단계를 구분하여 구조화된 합의를 계산한다.
    
    인용문 원문 일치(grounded)가 확인되고 필수 모델 단계가 모두 성공적으로 실행된 경우에만 합의 판정을 내린다.
    비모델 단계는 used 플래그가 없으므로 모델 실패로 취급하지 않는다.
    """
    # LLM 모델 단계만 필터링 (deterministic 등 비모델 단계 제외)
    model_stages = [s for s in stages if s.get("name") != "deterministic" and s.get("stage_type") != "deterministic"]
    opinions = [s.get("verdict") for s in model_stages if s.get("used") and s.get("verdict")]
    statuses = [str(v.get("status", "")).upper() for v in opinions]
    families = [{"VERIFIED", "SUPPORTED"}, {"CONTRADICTED", "DISTORTED"}, {"DISTINGUISHABLE"}]
    
    # 모델 실패 여부 판정: executions 실패가 있거나, 모델 단계 중 used가 False인 경우
    failed = (
        any(not getattr(e, "ok", False) for e in executions)
        or (bool(model_stages) and any(not s.get("used") for s in model_stages))
        or not statuses
    )
    decision = "UNVERIFIED"
    if grounded and statuses and not failed:
        for family, status in zip(families, ("SUPPORTED", "CONTRADICTED", "DISTINGUISHABLE")):
            if all(s in family for s in statuses):
                decision = status
                break
    normalized = {next((str(i) for i, family in enumerate(families) if s in family), s) for s in statuses}
    return {"status": decision, "model_statuses": statuses,
            "disagreement": len(normalized) > 1,
            "incomplete_models": failed, "advisory_only": True}

