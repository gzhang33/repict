"""Vercel WSGI entry: exposes Flask `app` for zero-config Flask deployments."""
import os
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from repict.web.app import create_app

_output_dir = Path(os.environ.get("REPICT_OUTPUT", "/tmp/repict_output")).resolve()
app = create_app(_output_dir)
