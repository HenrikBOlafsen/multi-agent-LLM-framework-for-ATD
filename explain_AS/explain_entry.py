#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from agent_setup import LLMClient, log_section, log_line, Ansi
from explain_cycle_minimal import build_minimal_prompt, cycle_chain_str, TEMPLATE as BASE_TEMPLATE
from orchestrators import ORCHESTRATORS
from orchestrators.base import CycleContext


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_cycle_in_catalog(catalog: dict, cycle_id: str) -> dict:
    for scc in (catalog.get("sccs") or []):
        for cyc in (scc.get("cycles") or []):
            if str(cyc.get("id")) == str(cycle_id):
                return cyc
    raise KeyError(f"cycle_id '{cycle_id}' not found in cycle_catalog.json")


def _mode_params(params_json: Optional[str]) -> Dict[str, Any]:
    if params_json:
        return json.loads(params_json)
    env = os.environ.get("ATD_MODE_PARAMS_JSON", "").strip()
    return json.loads(env) if env else {}


def _need_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(
            f"Missing required env var {name}. "
            f"This should be provided by the pipeline (from pipeline.yaml)."
        )
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--src-root", required=True)
    ap.add_argument("--scc-report", required=True)
    ap.add_argument("--cycle-id", required=True)
    ap.add_argument("--out-prompt", required=True)
    ap.add_argument("--params-json", default=None)
    ap.add_argument("--cycle-catalog", default=None, help="Path to cycle_catalog.json (required; preferred source)")
    args = ap.parse_args()

    params = _mode_params(args.params_json)

    orch_id = str(params.get("orchestrator", "v1_four_agents"))
    prompt_variant = str(params.get("refactor_prompt_variant", "default"))
    temperature = float(params.get("temperature", 0.1))
    max_tokens = int(params.get("max_tokens", 16384))

    if orch_id == "minimal":
        orch_cls = None
    else:
        orch_cls = ORCHESTRATORS.get(orch_id)
        if orch_cls is None:
            raise SystemExit(
                f"Unknown orchestrator '{orch_id}'. Known: {sorted(ORCHESTRATORS.keys())} or 'minimal'."
            )

    repo_root = Path(args.repo_root).resolve()
    report_path = Path(args.scc_report).resolve()
    out_prompt = Path(args.out_prompt).resolve()

    catalog_path = Path(args.cycle_catalog).resolve() if args.cycle_catalog else None
    if catalog_path is None:
        catalog_path = (report_path.parent / "cycle_catalog.json").resolve()

    if not catalog_path.exists():
        raise SystemExit(
            f"Missing cycle_catalog.json at: {catalog_path}\n"
            "Provide it via --cycle-catalog or generate it in baseline results."
        )

    catalog = _load_json(catalog_path)
    cycle = _find_cycle_in_catalog(catalog, args.cycle_id)

    nodes = [str(n) for n in (cycle.get("nodes") or [])]
    if not nodes:
        raise SystemExit(f"Cycle '{args.cycle_id}' has no nodes in cycle_catalog.json")

    size = int(cycle.get("length") or len(nodes))
    chain = cycle_chain_str(nodes)
    base = BASE_TEMPLATE.format(size=size, chain=chain)

    log_section("Explain entry", "cyan")
    log_line(f"orchestrator           : {orch_id}", Ansi.DIM)
    log_line(f"refactor_prompt_variant: {prompt_variant}", Ansi.DIM)
    log_line(f"cycle_catalog          : {str(catalog_path)}", Ansi.DIM)

    explain_dir = out_prompt.parent
    explain_dir.mkdir(parents=True, exist_ok=True)

    usage_path = explain_dir / "llm_usage.json"
    trace_path = explain_dir / "transcript.jsonl"

    # Enable transcript logging for multi-agent orchestrators
    if orch_cls is not None:
        os.environ["ATD_TRACE_PATH"] = str(trace_path)

    if orch_cls is None:
        final = build_minimal_prompt(cycle).rstrip() + "\n"
    else:
        llm_url = _need_env("LLM_URL")
        api_key = _need_env("LLM_API_KEY")
        model = _need_env("LLM_MODEL")

        client = LLMClient(llm_url, api_key, model, temperature=temperature, max_tokens=max_tokens)
        orch = orch_cls(client)
        ctx = CycleContext(repo_root=str(repo_root), src_root=str(args.src_root), cycle=cycle)

        refactor_part = orch.run(ctx, refactor_prompt_variant=prompt_variant)
        final = (f"{base}\n\n{refactor_part}".strip() + "\n")

        payload = {
            "model": model,
            "accumulated_usage": client.get_accumulated_usage(),
            "last_call_usage": client.get_last_usage(),
        }
        usage_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    out_prompt.write_text(final, encoding="utf-8")
    print(final)


if __name__ == "__main__":
    main()
