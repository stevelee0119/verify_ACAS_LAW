# 10시간 릴리스 준비표

기준: 운영 main9c1b21848110a8df6ba0e6308b49e6947c0d6feb /0.12.0. 수용분 제품 통합84461079dea09a4dbd20350d9139fb8c2bb23e31, 기록전용4ec0aa8은 제품변경0이다. 최종14TK 후보는 아직 미확정이며 수용·전체검증·봉인·배포를 구분한다. 2026-10-11 최신 사용자 지시는 미배포/보완 TK 완료 및 릴리스 집중이다.

| 항목 | 상태·다음 조치 |
|---|---|
| 기존8TK | 24·43·56·69·70·72·74·75, Steve5dea에 기술수용/병합·운영미배포 |
| 잔여6TK 목표 | 44·45·49·55·57·73. #78/#81/#82/#86 수용분만 평가통합. TK44/49 직접SPACE·UNKNOWN진단 및 TK55 first-party 경계는 제한범위이며 역사적UNKNOWNprimary/legacy역할 잔여를 완전해소로 기록하지 않음 |
| 최종 미수용 | TK45 #84 d11ae3e 및 TK73 #79 2f1424d 모두 정확SHA CI성공·3줄요청 후 불수용. TK45 정상7/8·확장0/4(actualTXT전체경로동일), TK73 AFP3/필수0 유지. 공개363/555 및 좁은감사PASS는 대체불가. 새원인설계부터 보완·미통합 |
| 독립 감사 | 기존8TK [감사](RELEASE_AUDIT_73_74.md), 추가수용분/최종공개후보 [10시간 감사](RELEASE_10H_PUBLIC_AUDIT.md). 공개감사는 비공개/봉인/전체 수용을 대신하지 않음 |
| 전체 verify_all | 최종수용 통합 후보에서 full1회 예정. 아래ba12 원본exit1/환경보완 이력은 이전8TK 증거로 보존하며 새후보 full통과로 사용하지 않음 |
| 통합 SHA CI | 수용분8446107 CI38106543045/점수38106543021 SUCCESS. 후속45/73 포함 최종SHA CI는 별도이며 미완료 |
| 측정 도구 일치 | 운영9c1b218·Steve5dea·수용분844·최종미수용d11/2f의 requirements/scorecard/eval_testset/score_gate/baseline SHA256 동일. 측정도구/기준선 변경없음; 점수측정이나 수용 증거로 대신하지 않음 |
| 새 봉인 | ZIP 자체점검8문서/57결함/28유형·오류0/경고0·지문1abd74597ec4b25a. 미채점. 최종수용SHA 동결 후 운영/후보 같은환경 최초1회 비교. 원문/정답 열람·게시 없음 |
| 고정 비공개 벤치 | 최종후보 미측정. 기존 사용자42문서20.5 집계는 이번후보 결과가 아님; 자료 미연결 상태를 숨기지 않음 |
| 버전 | 0.12.0 유지·최종판정대기. P1~P6·고정/봉인·같은조건 개선/해소근거 확인 후 정책판정. 상향시별도구현버전커밋1개·exact최종CI |
| DB/배포 구성 | 운영→844 공개읽기전용점검 migrations/의존성/Docker/Render/startup/worker 변경0. 추가설치·마이그레이션 작업없음. 후속45/73 포함후변경범위 재확인 |
| Render 기본 OFF | 운영자11:14KST 키없이회신: 단일서비스내부worker, profile환경미설정→OFF, activejobs0·동시재로드가능. 배포후실제main SHA·DB·API/worker/OFF 확인은 아직미완료 |
| TK75 활용 | 기본OFF 기술수용. 배포후 같은조건6쌍OFF/ON·독립한국변호사1명 조건가림채점, 제3판정없음. 17:51–19:21KST 운영자/채점가능확인. 품질개선 미확인 |
| 평가 절차 | 가격PR87 미병합폐기. 별도단가/정밀비용/비용증가율 조건삭제, 기존예산보호/USD40상한유지. ON 분석JSON에 기존실제Claude input/output/total의OFF/ON·차이·변화율과coverage를참고기록. 새로운제품PR/배포선행조건추가없음 |
| 릴리스 실행 | 사용자10시간배포완료 지시로 목표승인. 기술/봉인/버전/exactCI 조건충족뒤 Steve→main 준비PR77 갱신·병합/Render확인 순서. 현재조건미충족이므로main미병합·실제배포미완료 |

**준비 PR #83/#77은 draft다.** final14 SHA가 없으면 봉인채점하지 않고, 필수평가/새봉인/최종CI 전에는main병합하지 않는다. 실제배포health SHA 확인뒤에만 배포 상태를 기록한다. 30개 법률서면은 검증전provisional이며 이번봉인 대체불가. 추가제품범위를 늘리지 않고 TK45/73 수용·최종통합에 집중한다.

## 제품 후보 full 1회·실패 환경 재확인 (2026-10-11 한국 시각)

- 대상 ba12d25c7f1a877d9d3083dcad460816c718faf6, 기준 운영9c1b21848110a8df6ba0e6308b49e6947c0d6feb. clean tree·오프라인, Python3.11.15/Tesseract5.5.0 kor(저장소CI5.3.4와 다름), `--allow-env-mismatch` 명시. 기존 Playwright 캐시·외부 NanumGothic 경로 대역으로 글꼴 위치만 보완했다. 제품/시험/기준/시간상한 변경 없음.
- **원본 verify_all full 종료1:** acceptance1014/실제실패0, regression_ledger591/0, full_tests6207/실제실패1, browser_tests197/0. score/regression/hardcoding/test-edit/protected/version 게이트 모두 통과. raw JSON/log는 평가 artifact에 그대로 보존한다. 이 원본을 종료0으로 덮어쓰지 않았다.
- 유일한 실패는 `tests/test_durability.py::test_mount_detection_uses_the_filesystem_not_the_path`. 운영9c1b218·후보ba12d25의 해당제품/시험 diff0이며 같은 환경의 기본 `/tmp`에서 양쪽 모두 같은assertion 실패를 직접 재현했다. stat device `/`=27, `/tmp`=33, `/workspace`=27: `/tmp`가 별도파일시스템이라 시험의 비마운트 가정이 맞지 않았다.
- 제품/시험 수정이나 가짜 mount 응답 없이 pytest `--basetemp=/workspace/scratch/<대상>-pytest`로 실패1건만 재검증했다. 운영본exit0/후보exit0 **각1건 통과**. 통과한 나머지 묶음은 재실행하지 않았다. 전체원본1·별도환경보완2통과를 구분하며 full명령 전체종료0으로 표현하지 않는다. 현재 확인된 후보 고유 코드 실패0; 최종같은SHA CI 및 새봉인/버전/사용자배포승인은 별도다.
- 고정 성적표 후보 dev81.7/holdout79.2/FP0, A0·인젝션방어. 환경이 다른 사용자 고정비공개벤치마크20.5와 같은 측정으로 합치지 않는다. 실제법률품질/과금/지연·새봉인·최종고정비공개벤치마크 미측정.
