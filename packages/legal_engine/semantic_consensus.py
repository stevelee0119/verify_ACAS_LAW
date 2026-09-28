"""Conservative structured aggregation; quote presence does not prove entailment."""


def semantic_consensus(stages, *, grounded, executions=()):
    opinions = [s.get("verdict") for s in stages if s.get("used") and s.get("verdict")]
    statuses = [str(v.get("status", "")).upper() for v in opinions]
    families = [{"VERIFIED", "SUPPORTED"}, {"CONTRADICTED", "DISTORTED"}, {"DISTINGUISHABLE"}]
    failed = any(not getattr(e, "ok", False) for e in executions) or any(not s.get("used") for s in stages)
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
