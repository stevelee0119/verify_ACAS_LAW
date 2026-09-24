"""법령 적용 기준일 후보 추출.

문서에 날짜가 있어도 그것을 법령 적용 기준일로 자동 확정하지 않는다. 처분일·행위일·
신청일·사고일 가운데 무엇이 기준일인지는 쟁점과 법령(부칙·경과규정)에 따라 달라서
사람이 정해야 한다. 여기서는 날짜와 그 날짜가 문서에서 무엇을 뜻하는지만 찾아
검토자에게 후보로 보인다.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List

DATE_RE = re.compile(r"(?P<y>(?:19|20)\d{2})\s*[.\-년]\s*(?P<m>\d{1,2})\s*[.\-월]\s*(?P<d>\d{1,2})\s*[.일]?")

# 날짜 앞뒤에 오는 말 → 날짜의 뜻. 법령 적용 기준일이 될 수 있는지는 판단하지 않는다.
MEANINGS = [
    ("DISPOSITION", "처분일", r"처분|징계|해임|파면|강등|정직|감봉|견책|부과|취소처분|거부처분"),
    ("NOTICE", "통지·송달일", r"통지|송달|고지|통보|수령"),
    ("APPLICATION", "신청·청구일", r"신청|청구|제기|접수|제출"),
    ("CONDUCT", "행위·사고일", r"사고|발생|행위|위반|폭행|근무|복무|적발"),
    ("CONTRACT", "계약·합의일", r"계약|합의|약정|체결"),
    ("DECISION", "선고·결정일", r"선고|판결|결정|재결|의결"),
    ("HEARING", "청문·의견제출일", r"청문|의견\s*제출|진술"),
    ("ENFORCEMENT", "시행·공포일", r"시행|공포|발령|개정"),
    ("DOCUMENT", "작성일", r"작성|작성일"),
]


def reference_date_candidates(text: str, *, limit: int = 30) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for match in DATE_RE.finditer(text or ""):
        try:
            value = date(int(match.group("y")), int(match.group("m")), int(match.group("d"))).isoformat()
        except ValueError:
            continue
        before = text[max(0, match.start() - 25):match.start()]
        after = text[match.end():match.end() + 20]
        meaning, label = "UNKNOWN", "뜻 미상"
        # 날짜 바로 뒤("… 처분을")를 먼저, 바로 앞("처분일: …")을 다음으로 본다. 앞 문맥은
        # 이전 절의 낱말이 섞이므로 가까운 범위만 본다.
        hit = (next(((code, name) for code, name, pattern in MEANINGS if re.search(pattern, after[:12])), None)
               or next(((code, name) for code, name, pattern in MEANINGS if re.search(pattern, before[-8:])), None))
        if hit:
            meaning, label = hit
        key = (value, meaning)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": value, "meaning": meaning, "label": label,
                    "excerpt": " ".join((before + match.group(0) + after).split()),
                    # 시행·공포일은 법령 자체의 날짜라 사건의 기준일 후보가 아니다.
                    "candidate_for_reference": meaning not in ("ENFORCEMENT", "DOCUMENT", "DECISION"),
                    "auto_applied": False})
        if len(out) >= limit:
            break
    return out
