"""
run.py — entry point with mode and model selection

MODES:
  api          Run full harness via Anthropic API directly (needs ANTHROPIC_API_KEY)
  claude-code  Print instructions for Claude Code terminal

MODELS (api mode only):
  opus    claude-opus-4-5      most capable, slower
  sonnet  claude-sonnet-4-5    balanced
  haiku   claude-haiku-4-5     fastest, cheapest

EXAMPLES:
  # Full run via API using Opus (default)
  python run.py "USID_00 shutdown 2025-03-18 20:00 to 2025-03-21 20:00"

  # Choose a different model
  python run.py "USID_00 shutdown 2025-03-18 20:00 to 2025-03-21 20:00" --model sonnet

  # Re-run from Stage 3 after fixing a failure
  python run.py "USID_00 shutdown 2025-03-18 20:00 to 2025-03-21 20:00" --from-stage 3

  # Get Claude Code instructions instead of running directly
  python run.py "USID_00 shutdown 2025-03-18 20:00 to 2025-03-21 20:00" --mode claude-code
"""

import sys
import re
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

AVAILABLE_MODELS = {
    "opus":   "claude-opus-4-5",
    "sonnet": "claude-sonnet-4-5",
    "haiku":  "claude-haiku-4-5-20251001",
}


def parse_trigger(text: str):
    usid = re.search(r'USID_\w+', text, re.IGNORECASE)
    if usid:
        usid = usid.group(0).upper()
    else:
        print("ERROR: Could not find USID in trigger.")
        sys.exit(1)

    times = re.findall(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', text)

    if len(times) == 1:
        date_match = re.search(r'\d{4}-\d{2}-\d{2}', text)
        short_times = re.findall(r'\b(\d{2}:\d{2})\b', text)
        if date_match and len(short_times) >= 2:
            date = date_match.group(0)
            times = [f"{date} {short_times[0]}", f"{date} {short_times[1]}"]

    if len(times) < 2:
        print("ERROR: Could not parse two times.")
        sys.exit(1)

    return usid, times[0], times[1]


def run_claude_code_mode(target_usid, start, end, from_stage, model, workspace):
    print("\n" + "=" * 60)
    print(" Claude Code mode")
    print("=" * 60)
    print("\nType this in Claude Code terminal:\n")
    print(f'  read AGENTS.md then analyse: {target_usid} shutdown {start} to {end}')
    print("\nOr run directly via bash:\n")
    cmd = f'python {workspace}/run.py "{target_usid} shutdown {start} to {end}"'
    cmd += f" --mode api --model {model}"
    if from_stage > 1:
        cmd += f" --from-stage {from_stage}"
    print(f"  {cmd}")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="USID Outage Impact Assessment")
    parser.add_argument("trigger", nargs="?", help="Natural language trigger")
    parser.add_argument(
        "--mode", choices=["api", "claude-code"], default="api",
        help="api: run harness directly | claude-code: print Claude Code instructions (default: api)"
    )
    parser.add_argument(
        "--model", choices=list(AVAILABLE_MODELS.keys()), default="opus",
        help="Claude model: opus | sonnet | haiku (default: opus)"
    )
    parser.add_argument(
        "--from-stage", type=int, default=1, choices=[1, 2, 3, 4],
        help="Re-run from this stage after a failure (default: 1)"
    )
    parser.add_argument(
        "--workspace", default="/workspace",
        help="Workspace root directory (default: /workspace)"
    )

    args = parser.parse_args()

    trigger = args.trigger
    if not trigger:
        trigger = input("Enter trigger: ").strip()

    target_usid, start, end = parse_trigger(trigger)
    workspace = Path(args.workspace)

    print(f"\n  USID:     {target_usid}")
    print(f"  Shutdown: {start} -> {end}")
    print(f"  Mode:     {args.mode}")
    if args.mode == "api":
        print(f"  Model:    {args.model} ({AVAILABLE_MODELS[args.model]})")
    if args.from_stage > 1:
        print(f"  From:     Stage {args.from_stage}")
    print()

    if args.mode == "claude-code":
        run_claude_code_mode(target_usid, start, end,
                             args.from_stage, args.model, workspace)
        sys.exit(0)

    from pipeline import run_pipeline

    preprocessing_path = workspace / "results" / target_usid / "preprocessing_stats.json"
    result_dir = workspace / "results" / target_usid

    asyncio.run(run_pipeline(
        target_usid=target_usid,
        shutdown_start=start,
        shutdown_end=end,
        preprocessing_path=preprocessing_path,
        result_dir=result_dir,
        start_from_stage=args.from_stage,
        model=AVAILABLE_MODELS[args.model],
    ))