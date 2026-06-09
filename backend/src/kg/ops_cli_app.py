#!/usr/bin/env python3
"""Thin aggregation layer for the readonly ops CLI."""

from .ops_cli_costs import cmd_cost, cmd_cost_overview, cmd_fleet_overview
from .ops_cli_observability import cmd_llm_errors, cmd_timeseries, cmd_trends
from .ops_cli_parser import build_parser, main
from .ops_cli_queries import (
    cmd_active_users,
    cmd_analyze,
    cmd_card_find,
    cmd_card_get,
    cmd_db_query,
    cmd_quota_overview,
    cmd_sync_trace,
    cmd_user_config,
    cmd_user_quota,
    cmd_user_stats,
    cmd_world_diff,
    cmd_world_state,
)
from .ops_cli_shared import (
    _bucket_key,
    _bucket_key_from_date,
    _cutoff_iso,
    _enumerate_buckets,
    _flatten_user_config,
    _ops_passthrough_normalize,
    _parse_day,
)
