"""
mars_ai.py — Zeta AI Engine Adapter
Thin wrapper used by app.py.
All heavy lifting is in proper_ai.py.
"""

from proper_ai import query, get_engine_status

__all__ = ["query", "get_engine_status"]
