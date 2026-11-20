#!/usr/bin/env python3
"""Subscribe to Shanghai/Shenzhen A-shares or CSI 2000 native 1-minute bars."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ricequant_integration.realtime import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
