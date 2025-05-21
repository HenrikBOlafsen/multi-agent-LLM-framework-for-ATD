import json
import sys

def merge_cycles_files(mod_path, func_path, scc_metrics_path, out_path):
    with open(mod_path) as f:
        mod = json.load(f)
    with open(func_path) as f:
        func = json.load(f)
    with open(scc_metrics_path) as f:
        scc_metrics = json.load(f)

    merged = {
        "cycles": mod.get("cycles", []) + func.get("cycles", []),
        "metrics": scc_metrics
    }

    with open(out_path, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"Merged {len(mod['cycles'])} module + {len(func['cycles'])} function cycles into {out_path}")
    print(f"Included SCC metrics: {scc_metrics}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python3 merge_cycles.py module_cycles.json function_cycles.json scc_metrics.json cycles.json")
        sys.exit(1)

    merge_cycles_files(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
