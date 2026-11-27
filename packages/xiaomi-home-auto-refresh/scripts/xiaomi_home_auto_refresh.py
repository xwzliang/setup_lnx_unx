#!/usr/bin/env python3
"""Launch the Xiaomi Home refresh installer from the package catalog."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[3]
    runpy.run_path(str(repo / "setup_homeassistant" / Path(__file__).name), run_name="__main__")
