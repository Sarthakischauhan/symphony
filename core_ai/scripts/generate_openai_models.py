#!/usr/bin/env python3
"""Backward-compatible wrapper around generate_models.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_models import main

if __name__ == "__main__":
    main()
