"""Absolute-path bootstrap; no client configuration, prompts or tool results read."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shion.codex_mcp import main

if __name__ == "__main__":
    raise SystemExit(main())
