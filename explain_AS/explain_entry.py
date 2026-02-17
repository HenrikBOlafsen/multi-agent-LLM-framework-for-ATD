#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from agent_setup import LLMClient, log_section, log_line, Ansi
from explain_cycle_minimal import build_minimal_prompt, cycle_chain_str, TEMPLATE as BASE_TEMPLATE
from orchestrators import ORCHESTRATORS
from orchestrators.base import CycleContext

LLM_BLOCKED_EXIT_CODE = 42


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
        raise SystemExit(f"Missing required env var {name}. This should be provided by the pipeline.")
    return v


def _need_env_int(name: str) -> int:
    s = _need_env(name)
    try:
        v = int(s)
    except Exception:
        raise SystemExit(f"Env var {name} must be an int (got: {s!r})")
    if v <= 0:
        raise SystemExit(f"Env var {name} must be > 0 (got: {v})")
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--src-root", required=True)
    ap.add_argument("--scc-report", required=True)
    ap.add_argument("--cycle-id", required=True)
    ap.add_argument("--out-prompt", required=True)
    ap.add_argument("--params-json", default=None)
    ap.add_argument("--cycle-catalog", default=None)
    args = ap.parse_args()

    params = _mode_params(args.params_json)
    orch_id = str(params.get("orchestrator", "v1_four_agents"))
    prompt_variant = str(params.get("refactor_prompt_variant", "default"))
    temperature = float(params.get("temperature", 0.1))
    max_tokens = int(params.get("max_tokens", 16384))

    orch_cls = None if orch_id == "minimal" else ORCHESTRATORS.get(orch_id)
    if orch_id != "minimal" and orch_cls is None:
        raise SystemExit(f"Unknown orchestrator '{orch_id}'. Known: {sorted(ORCHESTRATORS.keys())} or 'minimal'.")

    repo_root = Path(args.repo_root).resolve()
    report_path = Path(args.scc_report).resolve()
    out_prompt = Path(args.out_prompt).resolve()

    catalog_path = (
        Path(args.cycle_catalog).resolve()
        if args.cycle_catalog
        else (report_path.parent / "cycle_catalog.json").resolve()
    )
    if not catalog_path.exists():
        raise SystemExit(f"Missing cycle_catalog.json at: {catalog_path}")

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

    out_prompt.parent.mkdir(parents=True, exist_ok=True)

    try:
        if orch_cls is None:
            final = build_minimal_prompt(cycle).rstrip() + "\n"
        else:
            llm_url = _need_env("LLM_URL")
            api_key = _need_env("LLM_API_KEY")
            model = _need_env("LLM_MODEL")
            context_length = _need_env_int("LLM_CONTEXT_LENGTH")

            os.environ["ATD_TRACE_PATH"] = str(out_prompt.parent / "transcript.jsonl")

            client = LLMClient(
                llm_url,
                api_key,
                model,
                context_length=context_length,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            orch = orch_cls(client)
            ctx = CycleContext(repo_root=str(repo_root), src_root=str(args.src_root), cycle=cycle)

            refactor_part = orch.run(ctx, refactor_prompt_variant=prompt_variant)
            final = (f"{base}\n\n{refactor_part}".strip() + "\n")

            (out_prompt.parent / "llm_usage.json").write_text(
                json.dumps(
                    {
                        "model": model,
                        "context_length": context_length,
                        "accumulated_usage": client.get_accumulated_usage(),
                        "last_call_usage": client.get_last_usage(),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

        out_prompt.write_text(final, encoding="utf-8")
        print(final)

    except requests.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", None)

        # "Request rejected" class: includes token/context too large.
        if status in (400, 413, 422):
            raise SystemExit(1)

        # misconfig / auth / wrong endpoint -> fail
        if status in (401, 403, 404):
            raise SystemExit(1)

        # anything else (usually 5xx) -> blocked
        raise SystemExit(LLM_BLOCKED_EXIT_CODE)

    except requests.RequestException:
        # timeout, connection refused, DNS, etc. => blocked
        raise SystemExit(LLM_BLOCKED_EXIT_CODE)


if __name__ == "__main__":
    main()
