"""Run on the Render worker with its real environment, not fixture mirrors."""
import json

from packages.common.config import get_settings
from packages.rag_engine.library import ReferenceLibrary


def main():
    library = ReferenceLibrary(get_settings())
    result = library.sync()
    # No reference contents, tokens, private paths or API keys in the diagnostic output.
    print(json.dumps({k: v for k, v in result.items() if k != "sources"}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
