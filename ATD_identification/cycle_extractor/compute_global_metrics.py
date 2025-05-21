import json
import sys
import networkx as nx
import os

def load_edges_from_sdsm(path):
    with open(path) as f:
        data = json.load(f)

    edges = set()
    variables = data.get("variables", [])
    for cell in data.get("cells", []):
        src_idx = cell["src"]
        dst_idx = cell["dest"]

        try:
            src = variables[src_idx]
            dst = variables[dst_idx]
        except IndexError:
            continue

        # Strip file and object format if present
        src_key = src.split("(")[-1].rstrip(")") if "(" in src else os.path.splitext(os.path.basename(src))[0]
        dst_key = dst.split("(")[-1].rstrip(")") if "(" in dst else os.path.splitext(os.path.basename(dst))[0]

        edges.add((src_key, dst_key))

    return edges

def compute_scc_metrics(edges):
    G = nx.DiGraph()
    G.add_edges_from(edges)

    sccs = list(nx.strongly_connected_components(G))
    nontrivial_sccs = [scc for scc in sccs if len(scc) > 1]

    return {
        "scc_count": len(nontrivial_sccs),
        "max_scc_size": max((len(scc) for scc in nontrivial_sccs), default=0),
        "avg_scc_size": round(
            sum(len(scc) for scc in nontrivial_sccs) / len(nontrivial_sccs), 2
        ) if nontrivial_sccs else 0
    }

def run(module_input_json, function_input_json, output_path):
    module_edges = load_edges_from_sdsm(module_input_json)
    function_edges = load_edges_from_sdsm(function_input_json)

    combined_edges = module_edges.union(function_edges)
    metrics = compute_scc_metrics(combined_edges)

    with open(output_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nGlobal SCC metrics written to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python compute_global_metrics.py result-modules.json result-functions.json scc_metrics.json")
        sys.exit(1)

    run(sys.argv[1], sys.argv[2], sys.argv[3])
