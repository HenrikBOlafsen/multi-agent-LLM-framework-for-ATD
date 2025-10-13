#!/usr/bin/env python3
"""
Selects the smallest representative cycle from the largest SCC
in a module_cycles.json produced by analyze_cycles.sh.

Usage:
    python select_cycle.py path/to/module_cycles.json
Prints:
    The selected cycle ID on stdout.
"""

import json
import sys
from pathlib import Path


def scc_size(scc):
    """Compute SCC size from available fields."""
    return scc.get("size") or scc.get("num_nodes") or len(scc.get("nodes") or [])


def cycles_list(scc):
    """Return representative cycles (or plain cycles) list."""
    reps = scc.get("representative_cycles") or []
    return reps or scc.get("cycles") or []


def cycle_len(cycle):
    """Return cycle length."""
    return cycle.get("length") or len(cycle.get("nodes") or [])


def main(path):
    data = json.loads(Path(path).read_text())

    sccs = data.get("sccs") or data.get("SCCs") or []
    if not sccs:
        print("", end="")
        return 3  # no SCCs

    # Pick the biggest SCC by size
    biggest = max(sccs, key=scc_size)

    # Then pick the smallest representative cycle
    cycs = cycles_list(biggest)
    if not cycs:
        print("", end="")
        return 4  # no cycles in biggest SCC

    def keyfn(c):
        l = cycle_len(c)
        cid = c.get("id") or c.get("cycle_id") or ""
        return (l, cid)

    chosen = min(cycs, key=keyfn)
    cid = chosen.get("id") or chosen.get("cycle_id") or ""
    print(cid, end="")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python select_cycle.py module_cycles.json", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
