#!/usr/bin/env python3
"""Thin aggregation layer for the write-capable ops tool."""

from .ops_edit_commands import *  # noqa: F403
from .ops_edit_commands import __all__ as _COMMAND_EXPORTS
from .ops_edit_parser import build_parser, main

__all__ = [
    *_COMMAND_EXPORTS,
    "build_parser",
    "main",
]
