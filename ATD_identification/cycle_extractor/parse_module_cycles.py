import json
import os
import sys
import heapq
import networkx as nx

def load_sdsm_module_json(path):
    with open(path, "r") as f:
        data = json.load(f)

    modules = data["variables"]
    edges = []

    for cell in data.get("cells", []):
        src_idx = cell["src"]
        dst_idx = cell["dest"]
        src_full_path = modules[src_idx]
        dst_full_path = modules[dst_idx]

        src_module = os.path.splitext(os.path.basename(src_full_path))[0]
        dst_module = os.path.splitext(os.path.basename(dst_full_path))[0]

        # Skip if either module is test-related
        if is_test_node(src_module) or is_test_node(dst_module):
            continue

        edges.append((src_module, dst_module))

    return modules, edges

def is_test_node(name):
    lowered = name.lower()
    return "test" in lowered or "tests" in lowered

def find_cycles_by_scc(edges, min_len=2, max_cycles=500, max_cycles_per_scc=5000):
    G = nx.DiGraph()
    G.add_edges_from(edges)

    print(f"Graph loaded: {len(G.nodes)} modules, {len(G.edges)} edges")

    all_cycles = []
    sccs = sorted(nx.strongly_connected_components(G), key=len, reverse=True)

    for i, scc in enumerate(sccs):
        if len(scc) <= 1:
            continue

        print(f"\nProcessing SCC {i}: {len(scc)} nodes")
        subgraph = G.subgraph(scc).copy()
        cycle_heap = []
        found = 0

        for cycle in nx.simple_cycles(subgraph):
            if len(cycle) < min_len:
                continue
            heapq.heappush(cycle_heap, (-len(cycle), cycle))
            if len(cycle_heap) > max_cycles:
                heapq.heappop(cycle_heap)
            found += 1
            if found % 100 == 0:
                print(f"...{found} cycles seen (heap size: {len(cycle_heap)})")
            if found >= max_cycles_per_scc:
                print(f"Reached max cycles for SCC ({max_cycles_per_scc}), stopping search")
                break

        selected_cycles = [cycle for _, cycle in sorted(cycle_heap)]
        print(f"  -> Kept {len(selected_cycles)} longest cycles")
        all_cycles.extend(selected_cycles)

    return G, all_cycles

def format_module_cycles_json(cycles, G):
    output = {"cycles": []}

    for i, cycle in enumerate(cycles):
        nodes = []
        edges = []

        for module in cycle:
            nodes.append({
                "id": module,
                "type": "module",
                "name": module
            })

        for idx in range(len(cycle)):
            src = cycle[idx]
            tgt = cycle[(idx + 1) % len(cycle)]
            if G.has_edge(src, tgt):
                edges.append({
                    "source": src,
                    "target": tgt,
                    "relation": "module_dep"
                })

        output["cycles"].append({
            "id": f"mod_cycle_{i}",
            "summary": f"Module-level cycle between {len(cycle)} modules",
            "nodes": nodes,
            "edges": edges,
            "definitions": []
        })

    return output

def run_pipeline(input_path, output_path):
    _, edges = load_sdsm_module_json(input_path)
    G, cycles = find_cycles_by_scc(edges)
    result = format_module_cycles_json(cycles, G)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nModule-level cycles saved to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python parse_module_cycles.py input.json output.json")
        sys.exit(1)

    run_pipeline(sys.argv[1], sys.argv[2])
