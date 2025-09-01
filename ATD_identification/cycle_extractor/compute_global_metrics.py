# compute_global_metrics.py
import json
import sys
import os
import networkx as nx

def load_module_edges_from_sdsm(path):
    with open(path) as f:
        data = json.load(f)

    variables = data.get("variables", [])
    edges = set()
    nodes = set()

    for cell in data.get("cells", []):
        src_idx = cell["src"]; dst_idx = cell["dest"]
        try:
            src_full = variables[src_idx]; dst_full = variables[dst_idx]
        except IndexError:
            continue

        src = os.path.splitext(os.path.basename(src_full))[0]
        dst = os.path.splitext(os.path.basename(dst_full))[0]

        # Skip tests
        if "test" in src.lower() or "tests" in src.lower():
            continue
        if "test" in dst.lower() or "tests" in dst.lower():
            continue

        nodes.add(src); nodes.add(dst)
        edges.add((src, dst))

    return nodes, edges

def scc_metrics(G: nx.DiGraph):
    sccs = [set(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    metrics = {
        "scc_count": len(sccs),
        "total_nodes_in_cyclic_sccs": 0,
        "total_edges_in_cyclic_sccs": 0,
        "max_scc_size": 0,
        "avg_scc_size": 0.0,
        "sccs": []
    }
    if not sccs:
        return metrics

    sizes = []
    for scc in sorted(sccs, key=len, reverse=True):
        sub = G.subgraph(scc).copy()
        n = sub.number_of_nodes()
        m = sub.number_of_edges()
        sizes.append(n)

        # Directed density
        dens = m / (n * (n - 1)) if n > 1 else 0.0

        # Edge surplus lower bound (undirected projection)
        und = sub.to_undirected()
        m_und = und.number_of_edges()
        edge_surplus_lb = max(0, m_und - (n - 1))

        metrics["sccs"].append({
            "size": n,
            "edge_count": m,
            "density_directed": round(dens, 4),
            "edge_surplus_lb": edge_surplus_lb
        })
        metrics["total_nodes_in_cyclic_sccs"] += n
        metrics["total_edges_in_cyclic_sccs"] += m

    metrics["max_scc_size"] = max(sizes)
    metrics["avg_scc_size"] = round(sum(sizes) / len(sizes), 2)
    return metrics

def run(sdsm_path, out_path):
    nodes, edges = load_module_edges_from_sdsm(sdsm_path)
    G = nx.DiGraph()
    G.add_nodes_from(nodes)
    G.add_edges_from(edges)
    res = scc_metrics(G)
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2)
    print(f"SCC metrics written to: {out_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python compute_global_metrics.py <module_sdsm.json> <out.json>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
