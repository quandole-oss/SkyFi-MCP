"""Entry point shim -- ensures PYTHONPATH includes project root."""
import sys
from pathlib import Path

# Add project root and packages/core to sys.path so that
# `from packages.server.local.config import ...` and `from interfaces import ...` resolve.
_project_root = Path(__file__).resolve().parents[3]  # skyfi_mcp -> core -> packages -> root
for p in [str(_project_root), str(_project_root / "packages" / "core")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.server.local.server import main  # noqa: E402

if __name__ == "__main__":
    main()
