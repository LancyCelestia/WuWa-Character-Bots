"""Compat shim: moved to domains/weather/capabilities/weather.py (v21r2 reorg W3)."""

from plugins.bot_unified_runtime.domains.weather.capabilities.weather import *
from plugins.bot_unified_runtime.domains.weather.capabilities.weather import (  # noqa: F401
    _WEATHER_RE,
    _nmc_query_with_retry,
    _query_variants,
)
