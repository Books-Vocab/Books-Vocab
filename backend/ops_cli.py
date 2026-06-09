#!/usr/bin/env python3
"""Thin public wrapper for the backend ops CLI entrypoint."""

from kg.ops_cli_app import *  # noqa: F403
from kg.ops_cli_app import _bucket_key, _flatten_user_config, main


if __name__ == "__main__":
    main()
