"""Sanity check that does not need a network or a Pi.

Run: python -m app.devcheck
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("DEV_MODE", "1")
    from app.config import load_settings
    from app.tools.registry import build_default_registry

    settings = load_settings()
    registry = build_default_registry(settings)

    print(f"config OK  model={settings.model}  dev_mode={settings.dev_mode}")
    print(f"tools: {', '.join(registry.names())}")

    dt = registry.call("get_datetime", {})
    assert dt.ok, dt.data
    assert "utc" in dt.data and "ist" in dt.data, dt.data
    print(f"get_datetime OK  utc={dt.data['utc']}  ist={dt.data['ist']}")

    stats = registry.call("get_system_stats", {})
    assert stats.ok, stats.data
    assert "memory" in stats.data, stats.data
    print(
        "get_system_stats OK  "
        f"cpu={stats.data.get('cpu_percent')}  "
        f"temp={stats.data.get('temperature_c')}  "
        f"mem%={stats.data['memory'].get('percent')}"
    )

    denied = registry.call("run_allowlisted_command", {"name": "rm -rf /"})
    assert not denied.ok, "allowlist must reject unknown commands"
    print("allowlist rejection OK")

    listed = registry.call("list_allowlisted_commands", {})
    assert listed.ok and listed.data.get("commands"), listed.data
    print(f"allowlist has {len(listed.data['commands'])} commands")

    unknown = registry.call("definitely_not_a_tool", {})
    assert not unknown.ok
    print("unknown tool rejection OK")

    print("devcheck passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
