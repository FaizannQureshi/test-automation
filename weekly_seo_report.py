#!/usr/bin/env python3
"""Weekly Connection Inc client visibility snapshot. Never prints secrets.

Entrypoint — all logic lives in the ``visibility_report`` package.
Run from the repository root:

    python3 weekly_seo_report.py
"""

from __future__ import annotations

import sys

from visibility_report.main import main

if __name__ == "__main__":
    sys.exit(main())
