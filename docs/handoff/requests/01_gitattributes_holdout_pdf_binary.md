# 01_gitattributes_holdout_pdf_binary

- **무엇이**: `.gitattributes` 파일에 `tests/fixtures/holdout/*.pdf -text -diff` 등록
- **왜**: Windows 환경(Git `core.autocrlf = true`)에서 저장소 클론 및 체크아웃 시 `tests/fixtures/holdout/*.pdf` 파일들이 텍스트로 인식되어 `\r\n`으로 줄바꿈 변환됨. 이로 인해 PDF 바이트 크기와 `startxref` 오프셋(3780)이 어긋나 `_structure_problems()`가 `startxref 위치에 교차참조표가 없다(MALFORMED_PDF)`로 판정하고, 대조군 `HO-01`에서 A등급 오탐(false positive)이 발생함.
- **제안하는 변경**:
  `.gitattributes` 파일 끝에 아래 내용을 추가:
  ```gitattributes
  tests/fixtures/holdout/*.pdf -text -diff
  ```
