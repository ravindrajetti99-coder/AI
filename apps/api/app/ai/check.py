"""AI smoke check: `python -m app.ai.check [--live] [--require]`.

Proves each configured provider's key and each tier's model work, without printing secrets.
By default it uses free calls (Anthropic token counting, OpenAI model lookup); `--live` sends one
tiny real request per tier through the production code path (a fraction of a cent). Run it after
deploying or rotating a key. Exit code 1 if a configured provider fails, or with `--require`
if no provider is configured (the platform would run on the offline engines).
"""

import argparse
import sys

from app.ai.providers.clients import get_provider, key_hint
from app.core.config import get_settings, reveal, secrets_dir

TIERS = ("heavy", "standard", "light")


def configuration() -> dict:
    """What is configured, safe to show staff: key hints, never keys."""
    s = get_settings()
    return {
        "primary": s.ai_primary,
        "fallback": s.ai_fallback,
        "keys": {
            "anthropic": key_hint(reveal(s.anthropic_api_key)),
            "anthropic_secondary": key_hint(reveal(s.anthropic_api_key_secondary)),
            "openai": key_hint(reveal(s.openai_api_key)),
        },
        "secrets_dir": secrets_dir() or "",
        "models": {t: get_provider("anthropic").model_for(t) for t in TIERS},
        "effort": {t: get_provider("anthropic").effort_for(t) or "model default" for t in TIERS},
        "prompt_caching": s.ai_prompt_caching,
        "structured_outputs": s.ai_structured_outputs,
        "server_fallbacks": s.anthropic_server_fallbacks,
        "task_overrides": {k: v.model_dump(exclude_none=True) for k, v in s.ai_task_overrides.items()},
        "daily_spend_cap_usd": s.ai_daily_spend_cap_usd,
        "budgets": {"learner": s.ai_daily_token_budget_learner, "staff": s.ai_daily_token_budget_staff},
        "max_input_tokens": s.ai_max_input_tokens,
    }


def run_checks(live: bool = False) -> list[dict]:
    """One row per configured provider and tier (the providers in EDU_AI_PRIMARY / EDU_AI_FALLBACK)."""
    s = get_settings()
    rows = []
    for name in dict.fromkeys([s.ai_primary, s.ai_fallback]):
        provider = get_provider(name) if name != "offline" else None
        if provider is None:
            continue
        if not provider.available():
            rows.append({"provider": name, "tier": "", "model": "", "ok": None, "detail": "no API key configured", "mode": "skipped"})
            continue
        rows.extend(provider.check(tier, live=live) for tier in TIERS)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.check", description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="send one tiny real request per tier")
    parser.add_argument("--require", action="store_true", help="fail when no provider is configured")
    args = parser.parse_args(argv)
    cfg = configuration()
    print(f"primary={cfg['primary']} fallback={cfg['fallback']} keys={cfg['keys']} secrets_dir={cfg['secrets_dir'] or '-'}")
    print(f"caching={cfg['prompt_caching']} structured_outputs={cfg['structured_outputs']} effort={cfg['effort']} spend_cap=${cfg['daily_spend_cap_usd']}")
    rows = run_checks(live=args.live)
    for r in rows:
        mark = {True: "PASS", False: "FAIL", None: "SKIP"}[r["ok"]]
        print(
            f"{mark:4}  {r['provider']:9} {r['tier']:8} {r['model']:20} {r['mode']:14} {r['detail']}"
            + (f"  [{r['request_id']}]" if r.get("request_id") else "")
        )
    configured = [r for r in rows if r["ok"] is not None]
    if not configured:
        print("No AI provider is configured: every AI feature uses the offline engines.")
        return 1 if args.require else 0
    return 0 if all(r["ok"] for r in configured) else 1


if __name__ == "__main__":
    sys.exit(main())
