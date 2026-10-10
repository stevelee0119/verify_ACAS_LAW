"""TK-43: category-scoped common nouns, not personal-name prefixes.

These closed sets supplement the existing candidate stopwords. Sources describe
the categories; they are not live dictionaries and introduce no download or
morphological-analysis dependency. Supplemental nouns use complete original
words, optionally with one grammatical particle. The standard-name ambiguity
guard is defined in detector.py. Do not use substring/prefix exclusion or
recursive particle removal; legacy stopword rules remain separate.
"""

# Category: procedural acts, disposition, and stated intent in proceedings.
# Sources: 민사소송법 (총칙/소송절차), 민사소송규칙, 행정절차법 (처분/신고).
# https://www.law.go.kr/법령/민사소송법
# https://www.law.go.kr/법령/민사소송규칙
# https://www.law.go.kr/법령/행정절차법
PROCEDURE_NOUNS = frozenset({
    "절차", "기간", "기한", "순서", "방법", "요건", "효력", "이유", "경위", "경과",
    "사건", "사정", "상황", "쟁점", "분쟁", "행위", "권리", "의무", "이익", "구제",
    "진행", "참가", "참여", "관여", "동행", "동의", "승낙", "협의", "협조", "요청",
    "요구", "문의", "질의", "응답", "회신", "설명", "안내", "상담", "방문", "접수",
    "제출", "송부", "보완", "보정", "연기", "연장", "중단", "정지", "속행", "확정",
    "신고", "청원", "진정", "선서", "서약", "진술권", "신청권", "동의권", "취소권", "거부권",
})

# Category: application, notification, certification, and accompanying records.
# Sources: 대한민국 법원 전자민원센터 양식모음 (민사/가사/신청/집행),
# 민원 처리에 관한 법률 및 시행규칙 (신청/처리/발급 서식).
# https://help.scourt.go.kr (양식모음)
# https://www.law.go.kr/법령/민원처리에관한법률시행규칙
RECORD_NOUNS = frozenset({
    "서식", "양식", "서신", "서한", "문안", "문구", "문항", "문답", "문답서", "자료",
    "내역", "목록", "사본", "원본", "정본", "등본", "초본", "부본", "첨부", "별지",
    "별첨", "부속", "증빙", "증빙서류", "신고서", "동의서", "승낙서", "서약서", "선서",
    "선서문", "각서", "증명서", "증서", "증빙자료", "진정서", "청원서", "회신서", "질의서", "경위서",
    "시말서", "사유서", "요청서", "요구서", "보정서", "통지서", "명세서", "명세", "신청내용", "신고내용",
    "제출자료", "첨부자료", "접수증", "수령증", "수령서", "납부서", "납부확인", "발급", "교부", "열람",
})

# Category: assets, income, payment, expenses, and tax/financial account items.
# Sources: 소득세법 (소득/세액), 민사집행법 (재산명시/재산조회),
# 국민기초생활 보장법 (소득/재산), 은행법 (은행업의 업무 범위).
# https://www.law.go.kr/법령/소득세법
# https://www.law.go.kr/법령/민사집행법
# https://www.law.go.kr/법령/국민기초생활보장법
# https://www.law.go.kr/법령/은행법
FINANCIAL_NOUNS = frozenset({
    "재산", "자산", "소득", "수입", "지출", "수익", "손실", "손해", "금액", "금원",
    "금전", "금융", "현금", "예금", "적금", "예치금", "출금", "입금", "이체", "송금",
    "거래", "거래내역", "잔액", "잔고", "이자", "원금", "대출", "차입", "차용", "차용금",
    "대여", "차용증", "신용", "신탁", "증권", "주식", "출자", "출자금", "지분", "배당금",
    "세금", "조세", "세액", "과세", "납세", "징수", "공과금", "수수료", "비용", "경비",
    "생활비", "교육비", "양육비", "부양료", "보험", "보험료", "보험금", "공적연금", "연금", "연금액",
    "급여", "수당", "급여액", "수당액", "납입", "납입금", "지급", "수령", "납부", "완납",
})

# Category: identity, contact, family relationship, residence and support fields.
# Sources: 가족관계의 등록 등에 관한 법률 및 규칙 (등록부/증명서),
# 주민등록법 및 시행규칙 (신고/등록표), 가사소송규칙 (당사자/가족관계).
# https://www.law.go.kr/법령/가족관계의등록등에관한법률
# https://www.law.go.kr/법령/주민등록법시행규칙
# https://www.law.go.kr/법령/가사소송규칙
IDENTITY_NOUNS = frozenset({
    "신원", "신상", "신분", "신분증", "인적정보", "신원정보", "신분관계", "성별", "연령", "나이",
    "국적", "본적", "본관", "등록지", "등록주소", "거주", "거주지", "거소", "거소지", "주소지",
    "연락", "연락망", "연락정보", "전화", "휴대폰", "우편", "우편물", "우편번호", "팩스", "팩스번호",
    "출생", "출생지", "출생신고", "사망", "사망일", "사망신고", "혼인", "이혼", "혼인관계", "가족관계",
    "친족", "친족관계", "혈연", "양육", "양육권", "친권", "후견", "후견등기", "상속", "상속분",
    "상속재산", "분할", "부양", "부양의무", "보호", "보호조치", "면접교섭", "면접교섭권", "주거", "주거지",
})

# Category: employment, duties, working conditions and workplace record fields.
# Sources: 근로기준법 및 시행규칙 (근로조건/임금대장), 산업안전보건법
# (안전보건/교육), 개인정보 보호법 (처리/접근/기록 관리).
# https://www.law.go.kr/법령/근로기준법시행규칙
# https://www.law.go.kr/법령/산업안전보건법
# https://www.law.go.kr/법령/개인정보보호법
WORK_NOUNS = frozenset({
    "업무", "직무", "근무", "근로", "근속", "경력", "이력", "학력", "자격", "자격증",
    "교육", "훈련", "연수", "수료", "수료증", "이수", "일정표", "근무표", "근무일", "출근",
    "퇴근", "출퇴근", "결근", "지각", "조퇴", "휴가", "병가", "연차", "휴일", "휴게",
    "근로조건", "근무조건", "급여명세", "임금대장", "명부", "인사기록", "인사정보", "재직", "재직증명", "퇴직",
    "퇴사", "퇴직증명", "사직", "사직서", "해고", "해고예고", "징계", "조직", "부서", "소속부서",
    "접근권한", "접속기록", "열람기록", "처리기록", "이용기록", "동의기록", "관리대장", "업무기록", "근무기록", "교육기록",
})

PERSON_STOPWORD_CATEGORIES = {
    "procedure": PROCEDURE_NOUNS,
    "records": RECORD_NOUNS,
    "financial": FINANCIAL_NOUNS,
    "identity": IDENTITY_NOUNS,
    "work": WORK_NOUNS,
}
PERSON_CATEGORY_STOPWORDS = frozenset().union(*PERSON_STOPWORD_CATEGORIES.values())
