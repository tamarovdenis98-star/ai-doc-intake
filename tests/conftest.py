import sys
from pathlib import Path

# the service package (app.*) lives in services/extractor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "extractor"))
