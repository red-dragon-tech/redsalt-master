#!/usr/bin/env python3
"""ARCHIVED, HISTORICAL ONLY — execution is disabled.

This retired RDT LLM regression watchdog is retained for traceability only.
It refers to removed tools and the retired host/model and is not supported.
"""
from __future__ import annotations

import sys


def main() -> int:
    print("ARCHIVED, HISTORICAL ONLY: this RDT LLM watchdog is disabled.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
