# run like this: python diff_scc_metrics.py old.json new.json
import json, sys
old, new = (json.load(open(p)) for p in sys.argv[1:3])

def summarize(x):
    s = x["sccs"]
    return {
        "scc_count": x["scc_count"],
        "total_nodes": x["total_nodes_in_cyclic_sccs"],
        "total_edges": x["total_edges_in_cyclic_sccs"],
        "max_scc_size": x["max_scc_size"],
        "cycle_pressure_lb": sum(scc["edge_surplus_lb"] for scc in s),
        "sizes": sorted((scc["size"] for scc in s), reverse=True),
    }

a, b = summarize(old), summarize(new)
print("OLD:", a)
print("NEW:", b)
print("Δ:", {k: b[k]-a[k] if isinstance(a[k], (int,float)) else None for k in a})
