import dash
from dash import dcc, html, Input, Output, State, ctx, MATCH, ALL
import dash_cytoscape as cyto
import json
import os
from collections import defaultdict

# Load the JSON cycles file
with open("cyclesTensorflow.json") as f:
    data = json.load(f)

# Try to extract a root path from the first file-based node
def get_project_root():
    for cycle in data["cycles"]:
        for node in cycle["nodes"]:
            if "file_path" in node:
                norm_path = os.path.normpath(node["file_path"])
                parts = norm_path.split(os.sep)
                if "tensorflow" in parts:
                    idx = parts.index("tensorflow")
                    return os.sep.join(parts[:idx])
    return ""

PROJECT_ROOT = get_project_root()

# --- Build edge frequency map for ranking ---
edge_frequency = defaultdict(int)
for cycle in data["cycles"]:
    for edge in cycle["edges"]:
        edge_key = (edge["source"], edge["target"])
        edge_frequency[edge_key] += 1

app = dash.Dash(__name__)
app.title = "Cycle Visualizer"

def render_cycle(cycle):
    elements = []

    for node in cycle["nodes"]:
        label = node.get("name", node["id"])
        elements.append({
            "data": {"id": node["id"], "label": label},
            "classes": node.get("type", "default")
        })

    for edge in cycle["edges"]:
        edge_data = {
            "source": edge["source"],
            "target": edge["target"],
            "label": edge.get("relation", "")
        }
        edge_classes = ""
        if edge_frequency[(edge["source"], edge["target"])] > 1:
            edge_classes = "suspicious-edge"
        elements.append({
            "data": edge_data,
            "classes": edge_classes
        })

    return elements

def get_filtered_sorted_options(cycles, min_nodes, max_nodes, ascending, ignored_nodes):
    filtered = [
        c for c in cycles
        if min_nodes <= len(c["nodes"]) <= max_nodes and
        not any(node["id"] in ignored_nodes for node in c["nodes"])
    ]
    sorted_cycles = sorted(filtered, key=lambda c: len(c["nodes"]), reverse=not ascending)
    return [{"label": c["summary"], "value": c["id"]} for c in sorted_cycles]

def short_display_id(node_id):
    return node_id.replace(PROJECT_ROOT + os.sep, "") if PROJECT_ROOT and node_id.startswith(PROJECT_ROOT) else node_id

app.layout = html.Div([
    html.Button("☰", id="toggle-panel", n_clicks=0, style={"margin": "10px", "zIndex": 9999, "position": "fixed"}),

    html.Div(id="side-panel", children=[
        html.H4("Cycle Controls"),
        html.Label("Min nodes:"),
        dcc.Input(id="min-nodes", type="number", value=0, debounce=True, style={"width": "100%"}),
        html.Label("Max nodes:"),
        dcc.Input(id="max-nodes", type="number", value=9999, debounce=True, style={"width": "100%"}),
        html.Br(),
        html.Button("🔃 Toggle Order", id="toggle-order", n_clicks=0, style={"marginTop": "10px"}),
        html.Div(id="order-label", style={"margin": "5px 0"}),
        html.Label("Ignored Nodes:"),
        html.Div(id="ignored-nodes", style={"maxHeight": "150px", "overflowY": "auto", "fontSize": "12px", "border": "1px solid #ccc", "padding": "5px", "marginBottom": "10px"}),
        html.Label("Select Cycle:"),
        dcc.Dropdown(id="cycle-select"),
        html.Hr(),
        html.H4("Graph Metrics"),
        html.Div(id="metrics-display", style={"fontSize": "12px", "maxHeight": "200px", "overflowY": "auto"}),
    ], style={
        "position": "fixed",
        "top": "50px",
        "left": "10px",
        "width": "300px",
        "padding": "15px",
        "backgroundColor": "#f0f0f0",
        "border": "1px solid #ccc",
        "zIndex": 9998,
        "display": "block",
        "boxShadow": "0 0 10px rgba(0,0,0,0.2)"
    }),

    cyto.Cytoscape(
        id="cytoscape",
        layout={"name": "circle"},
        style={
            "position": "absolute",
            "top": "0px",
            "left": "0px",
            "width": "100vw",
            "height": "100vh"
        },
        elements=[],
        stylesheet=[
            {"selector": 'node', "style": {"label": "data(label)", "background-color": "#28a4c9"}},
            {"selector": '.function', "style": {"shape": "ellipse", "background-color": "#61bffc"}},
            {"selector": '.module', "style": {"shape": "rectangle", "background-color": "#fca061"}},
            {"selector": '.suspicious-edge', "style": {"line-color": "red", "line-style": "dashed", "target-arrow-color": "red"}},
            {"selector": 'edge', "style": {"curve-style": "bezier", "target-arrow-shape": "triangle", "label": "data(label)"}}
        ]
    ),

    dcc.Store(id="ignored-nodes-store", data=[])
], style={"overflow": "hidden", "height": "100vh"})

@app.callback(
    Output("side-panel", "style"),
    Input("toggle-panel", "n_clicks"),
    State("side-panel", "style")
)
def toggle_side_panel(n_clicks, style):
    if n_clicks % 2 == 1:
        return {**style, "display": "none"}
    return {**style, "display": "block"}

@app.callback(
    Output("cycle-select", "options"),
    Output("order-label", "children"),
    Input("toggle-order", "n_clicks"),
    Input("min-nodes", "value"),
    Input("max-nodes", "value"),
    Input("ignored-nodes-store", "data")
)
def update_dropdown(order_clicks, min_nodes, max_nodes, ignored_nodes):
    ascending = (order_clicks % 2 == 1)
    options = get_filtered_sorted_options(data["cycles"], min_nodes, max_nodes, ascending, ignored_nodes)
    label = f"Ordering: {'Ascending' if ascending else 'Descending'}"
    return options, label

@app.callback(
    Output("cytoscape", "elements"),
    Input("cycle-select", "value")
)
def update_graph(cycle_id):
    cycle = next((c for c in data["cycles"] if c["id"] == cycle_id), None)
    return render_cycle(cycle) if cycle else []

@app.callback(
    Output("ignored-nodes-store", "data"),
    Output("ignored-nodes", "children"),
    Input("cytoscape", "tapNode"),
    Input({"type": "remove", "id": ALL}, "n_clicks"),
    State("ignored-nodes-store", "data")
)
def manage_ignore_list(tap_node, remove_clicks, current_list):
    triggered_id = ctx.triggered_id
    if isinstance(triggered_id, dict) and triggered_id.get("type") == "remove":
        node_id = triggered_id["id"]
        current_list = [n for n in current_list if n != node_id]
    elif tap_node:
        node_id = tap_node["data"]["id"]
        if node_id not in current_list:
            current_list.append(node_id)

    children = [
        html.Div([
            html.Span(short_display_id(n), style={"wordBreak": "break-all"}),
            html.Button("x", id={"type": "remove", "id": n}, n_clicks=0, style={"float": "right", "fontSize": "10px"})
        ]) for n in current_list
    ]
    return current_list, children

@app.callback(
    Output("metrics-display", "children"),
    Input("cycle-select", "options"),
    State("ignored-nodes-store", "data")
)
def update_metrics_display(_, ignored_nodes):
    ignored_nodes = set(ignored_nodes or [])
    all_cycles = [
        c for c in data["cycles"]
        if not any(n["id"] in ignored_nodes for n in c["nodes"])
    ]

    edge_counter = defaultdict(int)
    total_nodes = set()
    #total_edges = 0
    cycle_sizes = []

    for cycle in all_cycles:
        cycle_sizes.append(len(cycle["nodes"]))
        total_nodes.update(n["id"] for n in cycle["nodes"])
        #total_edges += len(cycle["edges"])
        for edge in cycle["edges"]:
            edge_key = (edge["source"], edge["target"])
            edge_counter[edge_key] += 1

    unique_edges = set()
    for cycle in all_cycles:
        for e in cycle["edges"]:
            unique_edges.add((e["source"], e["target"]))
    total_edges_unique = len(unique_edges)

    suspicious_edge_count = sum(1 for count in edge_counter.values() if count > 4)
    top_edges = sorted(edge_counter.items(), key=lambda x: x[1], reverse=True)[:5]

    # Static SCC metrics
    static_metrics = data.get("metrics", {})

    def line(label, value):
        return html.Div(f"{label}: {value}")

    top_edges_display = [
        html.Div(f"{src} → {tgt} (Count: {count})", style={"marginLeft": "10px"})
        for (src, tgt), count in top_edges
    ]

    return [
        html.Div("Graph Metrics (Filtered)", style={"fontWeight": "bold", "marginBottom": "5px"}),
        line("Total cycles", len(all_cycles)),
        line("Total nodes", len(total_nodes)),
        line("Total edges", total_edges_unique),
        line("Min cycle size", min(cycle_sizes) if cycle_sizes else "-"),
        line("Max cycle size", max(cycle_sizes) if cycle_sizes else "-"),
        line("Avg cycle size", round(sum(cycle_sizes) / len(cycle_sizes), 2) if cycle_sizes else "-"),
        line("Suspicious edges (used > 4x)", suspicious_edge_count),
        html.Br(),
        html.Div("Strongly Connected Components", style={"fontWeight": "bold", "marginBottom": "5px"}),
        line("SCC count", static_metrics.get("scc_count", "-")),
        line("Max SCC size", static_metrics.get("max_scc_size", "-")),
        line("Avg SCC size", static_metrics.get("avg_scc_size", "-")),
        html.Br(),
        html.Div("Top recurring edges:", style={"fontWeight": "bold"}),
        *top_edges_display
    ]



if __name__ == '__main__':
    app.run_server(debug=True, dev_tools_hot_reload=False)
