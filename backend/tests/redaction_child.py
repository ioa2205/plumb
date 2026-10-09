"""Trusted stdout fixture for LlamaServer lifecycle tests; does not load a model."""

import sys
import time
from pathlib import Path

if __name__ == "__main__":
    marker, key, literal, mode = sys.argv[1:]
    print("child ready", key, literal, "ghp_" + "a" * 36, flush=True)
    Path(marker).write_text("ready", encoding="utf-8")
    if mode == "exit":
        sys.exit(3)
    time.sleep(60)
