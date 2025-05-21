import json
import os
import networkx as nx
import sys
import heapq
import re

def parse_variable(var_str):
    if "(" in var_str and ")" in var_str:
        path, full_id = var_str.split("(", 1)
        full_id = full_id.rstrip(")")
        file_path = path.strip()
        reconstructed_id = f"{file_path}({full_id})"
        func_name = full_id.split(".")[-1]
        return reconstructed_id, {
            "id": reconstructed_id,
            "type": "function",
            "name": func_name,
            "file_path": file_path,
            "span": None
        }
    return None, None

def is_test_node(path_or_id):
    filename = os.path.basename(path_or_id).lower()
    return bool(re.search(r'(test_.*|.*_test)\.py', filename)) or ".test" in path_or_id.lower()

def load_sdsm_func_graph(path):
    with open(path, "r") as f:
        data = json.load(f)

    index_to_id = {}
    nodes = {}
    for i, var in enumerate(data["variables"]):
        node_id, info = parse_variable(var)
        if node_id and not is_test_node(node_id):
            index_to_id[i] = node_id
            nodes[node_id] = info

    edges = []
    spans = {}

    for cell in data["cells"]:
        src = index_to_id.get(cell["src"])
        tgt = index_to_id.get(cell["dest"])
        if src and tgt:
            if is_test_node(src) or is_test_node(tgt):
                continue
            edges.append((src, tgt))

            for detail in cell.get("details", []):
                if detail["type"] == "Call":
                    for side in ["src", "dest"]:
                        d = detail[side]
                        obj_id, _ = parse_variable(f'{d["file"]}({d["object"]})')
                        if obj_id and not is_test_node(obj_id):
                            spans[obj_id] = {
                                "start_line": d.get("lineNumber", 0),
                                "end_line": d.get("lineNumber", 0) + 1
                            }

    for node_id, span in spans.items():
        if node_id in nodes:
            nodes[node_id]["span"] = span

    return nodes, edges

def build_func_cycle_json(nodes, edges, min_len=2, max_cycles=500, max_cycles_per_scc=1000):
    G = nx.DiGraph()
    G.add_edges_from(edges)

    all_cycles = []
    sccs = sorted(nx.strongly_connected_components(G), key=len, reverse=True)

    for i, scc in enumerate(sccs):
        if len(scc) <= 1:
            continue

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
            if found >= max_cycles_per_scc:
                break

        selected_cycles = [cycle for _, cycle in sorted(cycle_heap)]
        all_cycles.extend(selected_cycles)

    output = {"cycles": []}

    for i, cycle in enumerate(all_cycles):
        cycle_nodes = []
        cycle_edges = []

        for node_id in cycle:
            node = nodes[node_id].copy()
            if not node.get("span"):
                node["span"] = {"start_line": 0, "end_line": 0}
            cycle_nodes.append(node)

        for idx in range(len(cycle)):
            src = cycle[idx]
            tgt = cycle[(idx + 1) % len(cycle)]
            cycle_edges.append({
                "source": src,
                "target": tgt,
                "relation": "function_call"
            })

        output["cycles"].append({
            "id": f"func_cycle_{i}",
            "summary": f"Function-level cycle between {len(cycle)} functions",
            "nodes": cycle_nodes,
            "edges": cycle_edges
        })

    return output

def run_pipeline(input_json, output_json):
    nodes, edges = load_sdsm_func_graph(input_json)
    result = build_func_cycle_json(nodes, edges)
    with open(output_json, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nFunction-level cycle JSON written to: {output_json}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python parse_function_cycles.py input.json output.json")
        sys.exit(1)

    run_pipeline(sys.argv[1], sys.argv[2])
