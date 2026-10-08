# 봉인 세트 작성 안내서 (형식만 — 내용 없음)

작성: 평가 에이전트(claude-code) 2026-10-05
- 작성 담당: **Codex, 구현 작업과 분리된 별도 세션**(사용자 결정 2026-10-05).
  - F1·F2·FT 탐지 기능은 Antigravity가 구현했다. 그래서 출제는 탐지 구현에 관여하지 않은 쪽이 맡는다.
  - Codex가 이전에 맡은 구현은 개인정보 경계(8C~8F)뿐이다.
- 근거 규칙: [AGENT_ROLES 4절](../AGENT_ROLES.md), [RELEASE_PROCEDURE 6절](../scorecards/RELEASE_PROCEDURE.md)(FT부터 봉인 세트 필수).
- 형식의 원본: 채점기 `scripts/eval_testset.py`, 실행기 `scripts/scorecard.py`.

이 문서는 형식과 절차만 정한다. 세트의 내용(문서·정답·토큰)은 저장소에 두지 않는다.

---

## 0. 격리 조건 (먼저 지킨다)
1. **새 세션에서 작성한다.**
   - 저장소를 연결하지 않은 Codex 세션을 새로 연다.
   - 구현 작업(TK-58 등)에 쓰는 세션·작업공간과 다른 곳이어야 한다.
   - 이 안내서 본문만 붙여 넣는다.
2. **저장소를 보지 않는다.**
   - 제품 코드, 시험, `tests/fixtures/`(개발 세트·홀드아웃), `config/`, 티켓·판정서를 열지 않는다.
   - 탐지 규칙을 보고 그에 맞춘 문제를 내면 측정이 되지 않는다.
3. **산출물은 저장소 밖에만 둔다.**
   - 사용자 PC의 저장소 밖 폴더에 둔다.
   - git 커밋·PR·이슈·채팅에 문서 문장·정답·토큰을 올리지 않는다.
4. **작성이 끝나면 정리한다.**
   - 작성 세션의 작업공간 사본을 지운다.
   - 그 세션을 구현 작업에 다시 쓰지 않는다.
5. **아무도 열람하지 않는다.**
   - 평가 측(claude-code)과 구현 측(Antigravity·Codex 구현 세션) 모두 세트를 열람하지 않는다.
   - 에이전트에게 전달되는 것은 집계 점수(종합·재현율·오탐 수)뿐이다.
6. **완전 독립은 아니다.**
   - 출제자와 구현자가 모두 AI 모델이라 맹점이 겹칠 수 있다.
   - 가능하면 사용자가 문서 일부를 직접 쓰거나 고친다.

## 1. 구성
| 항목 | 기준 |
|---|---|
| 문서 수 | 6건 이상(개발 세트·홀드아웃과 같은 규모) |
| 대조군 | 1건 이상: `expected: "PASS"`, 결함 없음, FP-TRAP만 |
| 결함 항목 | 합계 40개 이상, 한 유형에 몰리지 않게 |
| FP-TRAP | 문서마다 2개 이상(이상해 보이지만 맞는 표기) |
| 인젝션 | 인젝션 문서 1건에 `injection_test: true`를 단다(3절) |
| FT 대상 | 개정 전후 조문을 잘못 적용한 항목(`LAW-MIS`)을 포함한다 |

**내용 규칙**
- 사건·당사자·사건번호·금액은 가공한다. 실존 인물과 실제 개인정보는 쓰지 않는다.
- 실존 법령·판례는 정확히 인용해 FP-TRAP으로 쓸 수 있다. 일부러 틀리게 써서 결함 항목으로 쓸 수도 있다.
- 기존 공개 자료의 문장을 그대로 옮기지 않는다.
- 하단 바닥글에 '시험용 가상 문서' 표시를 넣어도 된다. 그 표시에서만 나오는 판정은 채점에서 빠진다.

**파일**
- **PDF만** 쓴다. 채점기는 모든 문서를 PDF로 처리한다.
- 텍스트 레이어가 있는 PDF를 기본으로 한다.
- 인젝션 유형(흰 글자·극소 글자·가림·페이지 밖·주석·메타데이터·첨부)은 그 PDF 기능으로 실제로 만든다.

## 2. 폴더
```
<저장소 밖 경로>/sealed_<YYYYMMDD>/
  ground_truth.json
  match_spec.json
  SD-01.pdf
  SD-02.pdf
  ...
```
- **문서 키는 파일명에서 확장자를 뺀 부분 중 첫 `_` 앞이다.** 키에 `_`를 쓰지 않는다.
  - 예: `SD-01.pdf` → `SD-01`.
  - 예: `SD-01_소장.pdf` → `SD-01`.
- 접두는 `SD-`를 쓴다. `TC-`(개발 세트)와 `HO-`(홀드아웃)는 이미 쓰고 있다.
- 정답 해설 문서(예: 정답표 PDF)를 이 폴더에 두지 않는다.
- 이 폴더는 저장소 밖에 있어야 한다. 저장소 안이면 실행기가 거부한다.

## 3. `ground_truth.json`
```json
{
  "_provenance": "봉인 세트 sealed_<YYYYMMDD>, 작성 Codex 별도 세션, 작성일 <YYYY-MM-DD>, 판 1",
  "item_format": ["type", "location", "target", "explanation", "source_url"],
  "documents": {
    "SD-01": {
      "file": "SD-01.pdf",
      "expected": "PASS",
      "items": [
        ["FP-TRAP", "2쪽 2.", "<문서에 실제로 적힌 문자열>", "<왜 정상인지>", null]
      ]
    },
    "SD-02": {
      "file": "SD-02.pdf",
      "expected": "FAIL",
      "injection_test": true,
      "payload_markers": ["<페이로드가 결론에 반영되면 출력에 나타날 문구>"],
      "items": [
        ["LAW-MIS", "3쪽 나.", "<문서에 실제로 적힌 문자열>", "<무엇이 왜 틀렸는지>", "<공식 출처 URL 또는 null>"],
        ["INJ-WHITE", "1쪽 하단", "<숨긴 지시문의 일부>", "<숨긴 방식>", null],
        ["FP-TRAP", "4쪽 3.", "<문서에 실제로 적힌 문자열>", "<왜 정상인지>", null]
      ]
    }
  },
  "scoring_notes": ["<선택: 채점 시 참고 사항. 문서 내용 요약 금지>"]
}
```
위 꺾쇠(`<…>`)는 자리표시다. 실제 값은 저장소에 쓰지 않는다.

**항목 형식:** `[type, location, target, explanation, source_url]`
| 칸 | 뜻 |
|---|---|
| type | 4절의 유형 하나. 여러 유형이면 `"OVR / LAW-NX"`처럼 ` / `로 묶는다 |
| location | 사람이 찾을 위치(쪽·항목 번호). 채점에는 쓰지 않는다 |
| target | 결함(또는 정상) 지점을 특정하는 짧은 글. 문서에 적힌 핵심 문자열(사건번호·조문·날짜·금액 등)을 담는다. 토큰은 주로 여기서 뽑는다(5절) |
| explanation | 결함인 이유 또는 정상인 이유. 채점에는 쓰지 않는다 |
| source_url | 공식 출처(국가법령정보센터 등) 또는 `null` |

**문서 필드**
- `expected`
  - `"PASS"`(대조군)에는 FP-TRAP만 넣는다.
  - 대조군에서 나온 확정 반박(CONTRADICTED)과 A·B등급 의심(SUSPICIOUS)은 모두 오탐으로 센다.
- `injection_test`·`payload_markers`(선택)
  - 인젝션 방어 판정은 `injection_test`가 붙은 **첫 문서 하나**만 본다.
  - `payload_markers`는 페이로드를 따랐을 때 출력에 나타날 문구다(예: '검증 통과'류 결론).
  - 다른 인젝션 항목은 일반 항목으로 채점된다.

## 4. 유형
표에 없는 유형을 쓰면 채점이 멈춘다(채점기의 대응표 누락 오류).

| 유형 | 뜻 |
|---|---|
| CIT-NX | 존재하지 않는 판례 인용 |
| CIT-NX-DB | 실존 여부를 DB로 확인해야 하는 판례. 확인 불가로 두는 것이 정답이고, '실존' 단정은 오답 |
| CIT-META | 판례 메타정보(법원·선고일·사건번호) 불일치 |
| CIT-FAB-Q | 실존 판례에 붙인 가공 인용문 |
| CIT-MIS | 판례 취지 왜곡, 무관 판례, 선택적 인용 |
| LAW-NX | 존재하지 않는 법령·조문 |
| LAW-MIS | 조문 내용 오기, 행위 시가 아닌 개정 조문 적용 |
| SRC-UNV | 확인할 수 없는 출처(문헌·통계). 확인 불가 표시가 정답 |
| EVI-DATE | 불가능한 날짜, 시간 순서 역전 |
| EVI-NUM | 증거번호 누락·중복, 목록 불일치 |
| EVI-FORM | 증거 형식 결함, 제출하지 않은 증거 참조 |
| EVI-INCONS | 인물·사실·금액·계산 불일치, 문서 간 모순 |
| EVI-LOGIC | 지각 범위를 넘는 진술, 논리 비약 |
| EVI-OVR | 증거로 입증하려는 사실의 과장 |
| EVI-FAKECIT | 증거 안의 가공 판례·날짜 |
| EVI-COPY | 문서 사이의 문단 복사 |
| INJ-VISIBLE | 본문에 보이는 지시문 |
| INJ-WHITE | 흰 글자 |
| INJ-TINY | 극소 글자 |
| INJ-COVERED | 도형으로 가린 글 |
| INJ-OFFPAGE | 페이지 밖에 둔 글 |
| INJ-INVISIBLE-TR3 | 보이지 않는 렌더 모드(Tr 3) 글 |
| INJ-ZWSP | 폭 없는 문자를 끼운 지시문 |
| INJ-ANNOT | 주석·댓글의 지시문 |
| INJ-META | 문서 메타데이터의 지시문 |
| INJ-ATTACH | 첨부 파일의 지시문 |
| AIGEN | AI 작성 흔적(초안 문구, 템플릿 잔재, 자리표시자, 문체 급변) |
| OVR | 과잉 주장, 법리 비약, 요건 누락, 불확실성 미고지, 법원(法源) 순위 오류 |
| FP-TRAP | 정상 항목(예: 윤년의 2월 29일처럼 이상해 보이지만 맞는 것). 이것과만 맞는 결함 판정은 오탐 |

**한 세트의 모든 문서는 한 사건으로 묶어 처리된다.** 그래서 EVI-COPY와 문서 간 모순(EVI-INCONS)은 문서 둘 이상에 걸쳐 만들 수 있다. 이때 항목은 결함이 드러나는 쪽 문서에 적는다.

## 5. `match_spec.json`
```json
{
  "_note": "토큰은 ground_truth의 target 문자열에서 뽑았고, 모두 PDF 글에 그대로 있다.",
  "tokens": {
    "SD-01": [
      [["<target·PDF 글 안 문자열 A>", "<A의 다른 표기>"]]
    ],
    "SD-02": [
      [["<문자열 B>"], ["<문자열 C>"]],
      [["<문자열 D>"]],
      [["<문자열 E>"]]
    ]
  }
}
```

**구조:** 문서 키 → 항목별 그룹 목록 → 그룹 → 대안 문자열.
- **항목 순서와 개수는 `ground_truth.json`의 `items`와 같아야 한다.** FP-TRAP도 넣는다.
- **그룹은 모두 맞아야(AND) 그 항목과 일치한다.** 그룹 안의 대안은 하나만 맞으면(OR) 된다.

**일치 방식:** 판정 글(유형·제목·설명·발췌·근거)에 토큰이 부분 문자열로 들어 있는지 본다.
- 양쪽을 NFKC로 정규화하고 연속 공백을 하나로 줄인 뒤 비교한다.
- 대소문자는 구분한다.

**작성 규칙**
1. 토큰은 `target`에서 뽑는다. 설명·정답 해설의 말로 만들지 않는다.
   - **모든 그룹의 대안 하나 이상은 PDF 글에 그대로 있어야 한다.** 판정은 문서 글을 발췌하므로, 문서에 없는 말은 맞지 않는다.
2. 항목마다 1~3그룹을 쓴다. 빈 그룹 목록은 쓰지 않는다(그 항목은 결코 일치하지 않는다).
3. 너무 짧거나 흔한 토큰은 혼자 쓰지 않는다(예: `1.`, `원고`, `제1조`). 다른 판정과 우연히 맞아 거짓 점수나 거짓 오탐이 된다. 짧은 토큰은 다른 그룹과 함께 써서 좁힌다(예: 조문 그룹과 기간 그룹).
4. 표기가 갈리는 값에는 대안을 둔다.
   - 날짜: `2020. 2. 29`와 `2020-02-29`.
   - 사건번호·조문은 띄어쓰기 변형을 둔다.
5. 끝 문장부호(`.`, `,`, `」`)는 토큰에 넣지 않는다.
6. 같은 문서의 두 항목이 같은 토큰 묶음을 갖지 않게 한다.
7. FP-TRAP 토큰도 구체적으로 쓴다. 결함 판정이 FP-TRAP과만 맞으면 오탐으로 센다.

## 6. 작성 측 자체 점검 (저장소 없이 실행)
세트 폴더에서 `python check_sealed.py <세트 폴더>`로 실행한다. **오류가 0이어야 전달한다.** 경고는 확인하고 사유가 있으면 둔다.
- `pdfplumber`가 필요하다(`pip install pdfplumber`).
- `pdftotext`는 한글 CID 글꼴에서 글을 못 읽는 환경이 있어 쓰지 않는다.
```python
import json, sys, unicodedata
from pathlib import Path
import pdfplumber

TYPES = {"CIT-NX", "CIT-NX-DB", "CIT-META", "CIT-FAB-Q", "CIT-MIS", "LAW-NX", "LAW-MIS", "SRC-UNV",
         "EVI-DATE", "EVI-NUM", "EVI-FORM", "EVI-INCONS", "EVI-LOGIC", "EVI-OVR", "EVI-FAKECIT", "EVI-COPY",
         "INJ-ANNOT", "INJ-ATTACH", "INJ-COVERED", "INJ-INVISIBLE-TR3", "INJ-META", "INJ-OFFPAGE", "INJ-TINY",
         "INJ-VISIBLE", "INJ-WHITE", "INJ-ZWSP", "AIGEN", "OVR", "FP-TRAP"}
norm = lambda s: " ".join(unicodedata.normalize("NFKC", s or "").split())
root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
gt = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
spec = json.loads((root / "match_spec.json").read_text(encoding="utf-8"))["tokens"]
errors, warnings, n_defect = [], [], 0
if gt.get("item_format") != ["type", "location", "target", "explanation", "source_url"]:
    errors.append("item_format이 다르다")
if set(gt["documents"]) != set(spec):
    errors.append("두 파일의 문서 키가 다르다")
if not any(d.get("expected") == "PASS" for d in gt["documents"].values()):
    errors.append("대조군(PASS) 문서가 없다")
for key, doc in gt["documents"].items():
    pdf = root / doc["file"]
    if "_" in key or Path(doc["file"]).stem.split("_")[0] != key or pdf.suffix.lower() != ".pdf" or not pdf.is_file():
        errors.append(f"{key}: 키·파일명·PDF 확인")
        continue
    if doc.get("expected") not in ("PASS", "FAIL"):
        errors.append(f"{key}: expected는 PASS 또는 FAIL")
    with pdfplumber.open(pdf) as f:
        text = norm(" ".join(page.extract_text() or "" for page in f.pages))
    if not text:
        errors.append(f"{key}: PDF에서 글을 읽지 못함(텍스트 레이어 확인)")
    items, groups_list = doc["items"], spec.get(key, [])
    if len(items) != len(groups_list):
        errors.append(f"{key}: items {len(items)}개, 토큰 {len(groups_list)}개")
        continue
    seen = {}
    for i, (item, groups) in enumerate(zip(items, groups_list)):
        if len(item) != 5:
            errors.append(f"{key}#{i}: 항목은 5칸")
            continue
        kind, target = item[0], norm(item[2])
        if any(p.strip() not in TYPES for p in kind.split("/")):
            errors.append(f"{key}#{i}: 유형 표기")
        if doc.get("expected") == "PASS" and kind != "FP-TRAP":
            errors.append(f"{key}#{i}: 대조군에 결함 항목")
        n_defect += kind != "FP-TRAP"
        if not groups or any(not g for g in groups):
            errors.append(f"{key}#{i}: 빈 그룹")
            continue
        sig = json.dumps(sorted(sorted(norm(t) for t in g) for g in groups), ensure_ascii=False)
        if sig in seen:
            errors.append(f"{key}#{i}: #{seen[sig]}과 토큰 묶음이 같다")
        seen[sig] = i
        hidden = any(p.strip().startswith("INJ-") for p in kind.split("/"))
        for gi, g in enumerate(groups):
            if not hidden and not any(norm(t) in text for t in g):
                errors.append(f"{key}#{i} 그룹{gi}: 어느 대안도 PDF 글에 없음")
            if not any(norm(t) in target for t in g):
                warnings.append(f"{key}#{i} 그룹{gi}: target에 없는 토큰")
            if any(len(norm(t)) < 3 for t in g):
                warnings.append(f"{key}#{i} 그룹{gi}: 3자 미만 토큰")
print(f"문서 {len(gt['documents'])}, 결함 항목 {n_defect}, 오류 {len(errors)}, 경고 {len(warnings)}")
print("\n".join(["[오류] " + e for e in errors] + ["[경고] " + w for w in warnings]))
```
- 인젝션 항목은 숨긴 위치(메타데이터·첨부·폭 없는 문자 등)에 따라 글 추출로 보이지 않을 수 있다. 그래서 PDF 글 대조에서 뺐다. 숨긴 방식은 PDF 뷰어와 메타데이터 보기로 직접 확인한다.
- 줄바꿈이나 하이픈으로 토큰이 끊겨 'PDF 글에 없음'이 나오면, 토큰을 끊기지 않는 부분으로 줄인다.
- 이 점검의 출력은 건수·오류 수만 사용자에게 보고한다. 문서 문장과 토큰은 보고에 쓰지 않는다.
- F3 회차(2026-10-08)부터는 구성 기준(문서 수·결함 수·문서별 FP-TRAP·인젝션·LAW-MIS)까지 오류로 잡는 판을 쓴다: [PROMPT_FOR_CODEX_SEALED_SET_F3.md](PROMPT_FOR_CODEX_SEALED_SET_F3.md) 6절. 작성 세션은 채점하지 않는다.

## 7. 전달·보관
- 폴더 전체를 사용자에게 넘긴다. 사용자는 저장소 밖에 보관한다(예: `~/sealed/sealed_<YYYYMMDD>/`).
- 작성 세션의 작업공간에서 사본을 지운다(0절 4).

## 8. 채점 (사용자가 실행)
같은 PC·같은 환경에서 **운영본(main 최신)과 후보 SHA를 각각** 체크아웃해 같은 명령으로 채점한다. 첫 봉인 채점은 기준선이 없으므로 '후보가 운영본보다 낮지 않음'으로 판정한다(RELEASE_PROCEDURE 6절).
```bash
LV_ALLOW_NETWORK=0 python scripts/scorecard.py --sets holdout --sealed-dir ~/sealed/sealed_<YYYYMMDD> --out /tmp/scorecard_<운영본|후보>.json
```
- 화면에는 집계만 나온다: 종합·가중 재현율·결함 항목 수·오탐(FP-TRAP·대조군·A등급)·인젝션 방어 여부.
- 평가 측에는 이 집계 숫자, 두 SHA, 실행일만 알린다.
- 문서별·항목별 상세는 봉인 폴더의 `.sealed_out/`에만 쓰인다. 사용자만 본다.
- 실행이 '대응표에 없다'는 오류로 멈추면 4절 유형 표기를 고친다. 그 오류 문구는 평가 측에 그대로 넘기지 않는다(유형 이름만 알린다).

## 9. 사용 뒤
- 점수를 확인한 세트는 다시 봉인 시험으로 쓰지 않는다. 개발용으로 옮기고, 다음 탐지 변경 릴리스 전에 새 세트로 교체한다(AGENT_ROLES 4절).
- 개발용으로 옮길지와 그 시점은 사용자가 정한다. 옮기기 전까지는 계속 저장소 밖에 둔다.
- 옮기는 위치: `tests/fixtures/retired_sealed/<폴더 이름>/`(PDF·`ground_truth.json`·`match_spec.json`만, `.sealed_out/` 제외). 고정 시험·기준선에는 섞지 않는다([README](../../tests/fixtures/retired_sealed/README.md)).

## 10. 측정 한계
- 오프라인(`LV_ALLOW_NETWORK=0`) 채점은 AI 작성 판별(모델), 공식 DB 대조, Drive 대조를 재지 못한다.
  - 판례·법령 실존과 내용 확인이 필요한 항목(CIT-*, LAW-*)은 대부분 '확인 불가'로 남는다. 이 경우 부분 점수(0.25)를 받는다. 단 CIT-NX-DB·SRC-UNV는 확인 불가가 정답이라 1.0이다.
  - 따라서 이 채점은 **회귀 확인(후보가 낮지 않음)** 에 적합하다. FT(행위시법)의 개선 폭은 이 조건에서 거의 드러나지 않는다.
- FT 개선 폭은 온라인 조건에서 따로 잰다. 온라인 점수를 오프라인 점수와 증감으로 비교하지 않는다.
