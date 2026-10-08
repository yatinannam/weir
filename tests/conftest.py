"""Repo-root tests (the demo launcher). The repo root has no package, so put it on the import path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
