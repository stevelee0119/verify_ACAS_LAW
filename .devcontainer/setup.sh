#!/usr/bin/env bash
# Codespaces 초기 설정. 한국어 OCR과 파이썬 의존성을 설치한다.
set -euo pipefail

echo "== 시스템 패키지 =="
sudo apt-get update -qq
sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-kor
tesseract --list-langs

echo "== 파이썬 의존성 =="
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "== 스키마 준비 (기본 SQLite) =="
python -c "from apps.api.db import init_db; init_db(); print('DB 준비 완료')"

cat <<'MSG'

준비가 끝났습니다.

  웹 콘솔 실행:   uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
                  (포트 8000이 자동으로 열립니다)
  테스트:         pytest
  외부 연동 점검: python scripts/live_source_check.py --strict
  CLI 검증:       python scripts/verify_cli.py --input samples --out out

API Key는 Codespaces Secrets에 등록하면 자동 주입됩니다.
  GitHub → Settings → Codespaces → Repository secrets

MSG
