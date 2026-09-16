"""Make `revision_pipeline` importable when pytest is run from anywhere.

These tests deliberately do not touch Django: Layer 1 is pure text analysis,
and keeping it free of the ORM means it can be tested without a database.
"""

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[2]      # Backend/ml
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))
