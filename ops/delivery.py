#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# ///
"""Executable entrypoint for the deterministic delivery control plane."""

from delivery_control.cli import main


raise SystemExit(main())
