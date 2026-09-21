"""Release check: python -m scripts.check_ocr_runtime. Never uses case documents."""
import json

from packages.document_engine.ocr_readiness import ocr_readiness


def main():
    state = ocr_readiness(refresh=True)
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0 if state["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
