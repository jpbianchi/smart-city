import sys
from pathlib import Path

# The dashboard imports the platform package (smartcity) from the repo's src/.
_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
