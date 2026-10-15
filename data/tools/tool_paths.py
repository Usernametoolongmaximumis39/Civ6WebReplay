"""Separate read/write locations for development archives and shipped data."""
from pathlib import Path
import sys

DEV = Path(__file__).resolve().parents[1]
WORKSPACE = DEV.parent
ROOT = WORKSPACE / "Civ6WebReplay"
sys.path.insert(0, str(ROOT / "src"))
