"""
trustai/cli.py
`trustai` command line for the governance API. Every command prints JSON (pipe it to jq) and exits non-zero on
API errors (1) or connection errors (2).

  trustai agents list [--status S] [--search Q]
  trustai agents get AGENT_ID | evidence AGENT_ID | status AGENT_ID onboarded|evaluated [--reason R]
  trustai agents policies AGENT_ID POLICY_ID [POLICY_ID ...]
  trustai policies list [--search Q] [--tag T] | recommend --agent AGENT_ID
  trustai guardrails list | evaluate GUARDRAIL_ID --text T [--phase P] [--target AGENT_ID]
  trustai enforce --agent AGENT_ID --text T [--phase input|output|tool_call:name]
  trustai metrics pii|prompt_manipulation|toxicity|secrets|adherence --text T [--policy P]
  trustai risk assess --agent AGENT_ID --facts facts.json
  trustai evaluations create --agent AGENT_ID [--prompts-file F] [--generate N] [--wait]
  trustai evaluations get EVALUATION_ID [--iterations] | wait EVALUATION_ID
  trustai gateway gate|deploy|revoke AGENT_ID [--model M] [--allow-conditional]
  trustai optimize AGENT_ID [--name N]
  trustai overview | events [--agent AGENT_ID] [--type T]
Configuration: --url / TRUSTAI_GOVERNANCE_URL and --api-key / TRUSTAI_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from trustai.govern.client import GovernClient, TrustAIAPIError, TrustAIConnectionError


def _load_prompts(path: str) -> list[dict[str, Any]]:
    """Read labelled prompts (list, or {"prompts"|"custom_prompts": [...]})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("custom_prompts") or data.get("prompts") or []
    return [p for p in items if isinstance(p, dict) and p.get("prompt")]


def build_parser() -> argparse.ArgumentParser:
    """Argument parser for every command."""
    ap = argparse.ArgumentParser(prog="trustai", description="TrustAI governance CLI",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--url", help="governance base URL (TRUSTAI_GOVERNANCE_URL)")
    ap.add_argument("--api-key", help="project API key with the govern scope (TRUSTAI_API_KEY)")
    sub = ap.add_subparsers(dest="group", required=True)

    agents = sub.add_parser("agents").add_subparsers(dest="cmd", required=True)
    p = agents.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--search")
    for name in ("get", "evidence", "history"):
        agents.add_parser(name).add_argument("agent_id")
    p = agents.add_parser("status")
    p.add_argument("agent_id")
    p.add_argument("status")
    p.add_argument("--reason")
    p = agents.add_parser("policies")
    p.add_argument("agent_id")
    p.add_argument("policy_ids", nargs="+")

    pol = sub.add_parser("policies").add_subparsers(dest="cmd", required=True)
    p = pol.add_parser("list")
    p.add_argument("--search")
    p.add_argument("--tag", action="append")
    pol.add_parser("recommend").add_argument("--agent", required=True)

    gr = sub.add_parser("guardrails").add_subparsers(dest="cmd", required=True)
    gr.add_parser("list")
    p = gr.add_parser("evaluate")
    p.add_argument("guardrail_id")
    p.add_argument("--text", required=True)
    p.add_argument("--phase", default="input")
    p.add_argument("--target")

    p = sub.add_parser("enforce")
    p.add_argument("--agent", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--phase", default="input")

    p = sub.add_parser("metrics")
    p.add_argument("metric")
    p.add_argument("--text", required=True)
    p.add_argument("--policy")
    p.add_argument("--categories", nargs="*")

    risk = sub.add_parser("risk").add_subparsers(dest="cmd", required=True)
    p = risk.add_parser("assess")
    p.add_argument("--agent", required=True)
    p.add_argument("--facts", required=True, help="JSON file with build facts")

    ev = sub.add_parser("evaluations").add_subparsers(dest="cmd", required=True)
    p = ev.add_parser("create")
    p.add_argument("--agent", required=True)
    p.add_argument("--prompts-file")
    p.add_argument("--generate", type=int, default=None)
    p.add_argument("--benign-ratio", type=float, default=0.3)
    p.add_argument("--reuse")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=float, default=900)
    p = ev.add_parser("get")
    p.add_argument("evaluation_id")
    p.add_argument("--iterations", action="store_true")
    p = ev.add_parser("wait")
    p.add_argument("evaluation_id")
    p.add_argument("--timeout", type=float, default=900)

    gw = sub.add_parser("gateway").add_subparsers(dest="cmd", required=True)
    gw.add_parser("models")
    for name in ("gate", "deploy", "revoke"):
        p = gw.add_parser(name)
        p.add_argument("agent_id")
        p.add_argument("--model")
        p.add_argument("--allow-conditional", action="store_true")

    p = sub.add_parser("optimize")
    p.add_argument("agent_id")
    p.add_argument("--name")
    sub.add_parser("overview")
    p = sub.add_parser("events")
    p.add_argument("--agent")
    p.add_argument("--type")
    p.add_argument("--limit", type=int, default=50)
    return ap


def run(a: argparse.Namespace, gov: GovernClient) -> Any:
    """Dispatch one parsed command."""
    g, cmd = a.group, getattr(a, "cmd", None)
    if g == "agents":
        return {"list": lambda: gov.agents.list(status=a.status, search=a.search),
                "get": lambda: gov.agents.get(a.agent_id), "evidence": lambda: gov.agents.evidence(a.agent_id),
                "history": lambda: gov.agents.history(a.agent_id),
                "status": lambda: gov.agents.set_status(a.agent_id, a.status, a.reason),
                "policies": lambda: gov.agents.attach_policies(a.agent_id, a.policy_ids)}[cmd]()
    if g == "policies":
        return gov.guardrails.policies(a.search, a.tag) if cmd == "list" else gov.guardrails.recommend(agent_id=a.agent)
    if g == "guardrails":
        if cmd == "list":
            return gov.guardrails.list()
        return gov.guardrails.evaluate(a.guardrail_id, a.text, phase=a.phase, target_id=a.target)
    if g == "enforce":
        return gov.guardrails.enforce(a.text, phase=a.phase, agent_id=a.agent, source="api")
    if g == "metrics":
        extra = {"policy": a.policy} if a.policy else {}
        if a.categories:
            extra["categories"] = a.categories
        return gov.guardrails.metric(a.metric, a.text, **extra)
    if g == "risk":
        return gov.risk.assess(json.loads(Path(a.facts).read_text(encoding="utf-8")), agent_id=a.agent)
    if g == "evaluations":
        if cmd == "create":
            if a.reuse:
                created = gov.evaluations.create(a.agent, source="reuse", from_evaluation_id=a.reuse)
            elif a.prompts_file:
                custom = _load_prompts(a.prompts_file)
                created = gov.evaluations.create(a.agent, source="mixed" if a.generate else "custom",
                                                 custom_prompts=custom, num_generate=a.generate or 0,
                                                 benign_ratio=a.benign_ratio)
            else:
                created = gov.evaluations.create(a.agent, num_generate=a.generate or 40, benign_ratio=a.benign_ratio)
            return gov.wait(created["id"], timeout=a.timeout) if a.wait else created
        if cmd == "get":
            return gov.evaluations.get(a.evaluation_id, include_iterations=a.iterations)
        return gov.wait(a.evaluation_id, timeout=a.timeout)
    if g == "gateway":
        if cmd == "models":
            return gov.gateway.models()
        if cmd == "gate":
            return gov.gateway.gate(a.agent_id, a.allow_conditional)
        if cmd == "deploy":
            return gov.gateway.deploy(a.agent_id, model=a.model, allow_conditional=a.allow_conditional)
        gov.gateway.revoke(a.agent_id)
        return {"revoked": True, "agent_id": a.agent_id}
    if g == "optimize":
        return gov.agents.optimize(a.agent_id, name=a.name)
    if g == "overview":
        return gov.overview()
    return gov.events(agent_id=a.agent, event_type=a.type, limit=a.limit)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    a = build_parser().parse_args(argv)
    try:
        with GovernClient(base_url=a.url, api_key=a.api_key) as gov:
            out, code = run(a, gov), 0
    except TrustAIConnectionError as exc:
        out, code = {"error": "connection", "detail": str(exc.detail)}, 2
    except TrustAIAPIError as exc:
        out, code = {"error": exc.status_code, "detail": exc.detail}, 1
    except TimeoutError as exc:
        out, code = {"error": "timeout", "detail": str(exc)}, 1
    print(json.dumps(out, indent=2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
