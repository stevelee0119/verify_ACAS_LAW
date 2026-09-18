"""Project-scoped explicit identity resolution and separate lexical candidates."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
import unicodedata

from packages.common.schemas import Claim, Entity


def resolve_entities(entities: list[Entity], *, project_id: str | None = None) -> list[Entity]:
    """Merge only explicit identifiers/explicit_aliases inside one known project.

    Name equality, substring matching, legacy aliases and lexical similarity are
    never identity proof. Ambiguous alias groups with conflicting IDs stay apart.
    Returned objects are copies; input entities and their mentions are untouched.
    """
    copies = deepcopy(entities)
    if project_id is not None:
        if not project_id.strip() or any(e.project_id not in (None, project_id) for e in copies):
            raise ValueError("Entities must belong to the requested project")
        for entity in copies:
            entity.project_id = project_id
    graph = [set() for _ in copies]
    for i, first in enumerate(copies):
        for j in range(i + 1, len(copies)):
            second = copies[j]
            if not first.project_id or first.project_id != second.project_id or first.type != second.type:
                continue
            shared = any(value and second.explicit_identifiers.get(key) == value
                         for key, value in first.explicit_identifiers.items())
            alias = (first.name in second.explicit_aliases or second.name in first.explicit_aliases
                     or bool(set(first.explicit_aliases) & set(second.explicit_aliases)))
            if shared or alias:
                graph[i].add(j)
                graph[j].add(i)
    output = []
    visited = set()
    for root in range(len(copies)):
        if root in visited:
            continue
        pending, component = [root], []
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(copies[node])
            pending.extend(graph[node] - visited)
        values: dict[str, set[str]] = {}
        for entity in component:
            for key, value in entity.explicit_identifiers.items():
                if value:
                    values.setdefault(key, set()).add(value)
        if any(len(v) > 1 for v in values.values()):
            for entity in component:
                entity.needs_user_confirmation = True
                entity.resolution_basis = "CONFLICTING_EXPLICIT_IDENTIFIERS"
            output.extend(component)
            continue
        component.sort(key=lambda e: (e.name, e.entity_id))
        result = component[0]
        identifiers = {k: next(iter(v)) for k, v in sorted(values.items())}
        aliases = sorted({name for e in component for name in [e.name, *e.explicit_aliases]})
        if result.project_id and (identifiers or len(component) > 1):
            anchor = sorted(identifiers.items())[0] if identifiers else aliases
            payload = json.dumps([result.project_id, str(result.type), anchor], ensure_ascii=True)
            result.entity_id = "ENT_" + sha256(payload.encode()).hexdigest()[:24]
            result.resolution_basis = "EXPLICIT_IDENTIFIER" if identifiers else "EXPLICIT_ALIAS"
            result.explicit_identifiers = identifiers
            result.explicit_aliases = [name for name in aliases if name != result.name]
            result.aliases = sorted(set(result.aliases + result.explicit_aliases))
            result.mentions = [mention for e in component for mention in e.mentions]
            result.merge_confidence = 1.0
            result.needs_user_confirmation = False
        else:
            result.resolution_basis = "UNRESOLVED"
            result.needs_user_confirmation = True
        output.append(result)
    return sorted(output, key=lambda e: (e.project_id or "", str(e.type), e.name, e.entity_id))


@dataclass(frozen=True)
class ClaimCandidate:
    claim_id: str
    document_id: str | None
    block_id: str | None
    page: int | None
    source_run_id: str | None
    score: float
    method: str = "difflib.SequenceMatcher lexical similarity"
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def search_claim_candidates(
    query: str, claims: list[Claim], *, project_id: str,
    limit: int = 10, minimum_score: float = 0.2,
) -> list[ClaimCandidate]:
    """Bounded lexical candidates, not embeddings, entity merges, or proof."""
    if not project_id or not 1 <= limit <= 100 or not 0 <= minimum_score <= 1:
        raise ValueError("Require project_id, limit 1..100, minimum_score 0..1")
    normalize = lambda text: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()
    needle = normalize(query)
    if not needle:
        return []
    if len(needle) > 4096:
        raise ValueError("Query exceeds 4096 characters")
    results = []
    for claim in claims:
        if claim.project_id != project_id:
            continue
        haystack = normalize(claim.text)[:8192]
        similarity = SequenceMatcher(None, needle, haystack, autojunk=False).ratio()
        if similarity >= minimum_score:
            results.append(ClaimCandidate(claim.claim_id, claim.document_id, claim.block_id,
                                          claim.page, claim.source_run_id, similarity))
    return sorted(results, key=lambda result: (-result.score, result.claim_id))[:limit]
