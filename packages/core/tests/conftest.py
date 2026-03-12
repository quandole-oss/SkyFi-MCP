"""Add project root to sys.path so 'from interfaces import ...' works."""

import sys
from pathlib import Path

# Add project root (where interfaces.py lives) to sys.path
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
