# 다음8TK 릴리스 준비표

기준: 운영 main9c1b21848110a8df6ba0e6308b49e6947c0d6feb /0.12.0, 제품후보 ba12d25c7f1a877d9d3083dcad460816c718faf6. 참고 문서등록4178cca 및 이후 평가 기록 변경은 제품·시험·채점기 변경과 구분한다. 후보 제품 변경이 추가되면 검증/채점 대상을 새SHA로 갱신하며 이전 결과를 동일 후보 결과로 주장하지 않는다.

| 항목 | 상태·다음 조치 |
|---|---|
| 포함 TK | 24·43·56·69·70·72·74·75, Steve 병합. 운영 미배포 |
| 기술 수용 | #73리뷰5481242311·#74리뷰5481214189 및 각 동일SHA CI 성공 |
| 독립 감사 | 공개범위 새P1 미발견, 공개70건·통합교차25건 통과. [감사](RELEASE_AUDIT_73_74.md) |
| 전체 verify_all | 제품후보ba12d25 full1회 원본exit1: acceptance1014/원장591/전체6207/브라우저197통과, 마운트시험1실패. 같은운영본실패 재현·workspace basetemp에서양쪽각1통과. 제품고유실패0, 원본full0으로위장하지않음. 아래환경기록참조 |
| 최종 SHA CI | 평가 기록PR 및 Steve→main 준비PR에서 같은 SHA 필수 체크 확인. 개별PR green으로 대체하지 않음 |
| 새 봉인 | 필수·미완료. [작성](../handoff/PROMPT_FOR_CODEX_SEALED_SET_RELEASE_NEXT.md)→별도자체점검→[동일조건채점](../handoff/PROMPT_FOR_SCORING_SEALED_RELEASE_NEXT.md). 원문/정답은 사용자영역, 집계만 회신 |
| 고정 비공개 벤치 | 최종8TK 후보 미측정. 이전ad25f51=운영20.5는 이번 후보 결과 아님. 자료 미연결 시 미측정으로 유지 |
| 버전 | 0.12.0 유지 상태, 최종 판정 대기. TK56 알려진미해결21해소 등M3와기존수용근거를검토하되 P1~P6/새봉인·최종CI 확인 전 상향을 확정하지 않음. 상향이면 별도 구현버전커밋1개 후 releasePR갱신 |
| DB | 운영main 대비 migrations/ 변경0. 이번diff 기준 별도DB마이그레이션 없음 |
| TK75 활용 | 기본OFF 포함. 실제 법률개선 미확인. 배포 후 [온라인전체OFF/ON](../handoff/requests/TK75_ONLINE_OFF_ON_CHECK.md), 독립한국변호사1명 조건가림·제3판정 없음·비용/p95+20%참고 |
| 배포 승인 | 미요청. main병합이Render자동배포; 사용자 새봉인집계·후보/CI·버전판정 확인후 마지막 승인 |

**현재 준비PR은 검토용 draft다.** 봉인/후보 필수 조건 미충족 상태에서main병합·Render배포·기본ON으로 변경하지 않는다. 문서/등록부만 업데이트한 것과 실제검증/배포를 구분한다. 30개 서면은법률검증전provisional 기준 후보이고 새봉인 대체불가.


## 제품 후보 full 1회·실패 환경 재확인 (2026-10-11 한국 시각)

- 대상 ba12d25c7f1a877d9d3083dcad460816c718faf6, 기준 운영9c1b21848110a8df6ba0e6308b49e6947c0d6feb. clean tree·오프라인, Python3.11.15/Tesseract5.5.0 kor(저장소CI5.3.4와 다름), `--allow-env-mismatch` 명시. 기존 Playwright 캐시·외부 NanumGothic 경로 대역으로 글꼴 위치만 보완했다. 제품/시험/기준/시간상한 변경 없음.
- **원본 verify_all full 종료1:** acceptance1014/실제실패0, regression_ledger591/0, full_tests6207/실제실패1, browser_tests197/0. score/regression/hardcoding/test-edit/protected/version 게이트 모두 통과. raw JSON/log는 평가 artifact에 그대로 보존한다. 이 원본을 종료0으로 덮어쓰지 않았다.
- 유일한 실패는 `tests/test_durability.py::test_mount_detection_uses_the_filesystem_not_the_path`. 운영9c1b218·후보ba12d25의 해당제품/시험 diff0이며 같은 환경의 기본 `/tmp`에서 양쪽 모두 같은assertion 실패를 직접 재현했다. stat device `/`=27, `/tmp`=33, `/workspace`=27: `/tmp`가 별도파일시스템이라 시험의 비마운트 가정이 맞지 않았다.
- 제품/시험 수정이나 가짜 mount 응답 없이 pytest `--basetemp=/workspace/scratch/<대상>-pytest`로 실패1건만 재검증했다. 운영본exit0/후보exit0 **각1건 통과**. 통과한 나머지 묶음은 재실행하지 않았다. 전체원본1·별도환경보완2통과를 구분하며 full명령 전체종료0으로 표현하지 않는다. 현재 확인된 후보 고유 코드 실패0; 최종같은SHA CI 및 새봉인/버전/사용자배포승인은 별도다.
- 고정 성적표 후보 dev81.7/holdout79.2/FP0, A0·인젝션방어. 환경이 다른 사용자 고정비공개벤치마크20.5와 같은 측정으로 합치지 않는다. 실제법률품질/과금/지연·새봉인·최종고정비공개벤치마크 미측정.
