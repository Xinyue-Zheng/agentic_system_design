"""
claude_runner.py — runs Claude Code as the agent instead of API calls

Two modes set by PIPELINE_MODE environment variable:
  PIPELINE_MODE=claudecode  — uses `claude --print` (no API key needed)
  PIPELINE_MODE=api         — uses anthropic.Anthropic() (needs API key)

Default is claudecode — the right default when inside Claude Code terminal.

To switch modes:
  export PIPELINE_MODE=claudecode   # use Claude Code (default)
  export PIPELINE_MODE=api          # use API directly
"""

import os
import json
import subprocess
import tempfile
import time
from pathlib import Path


PIPELINE_MODE = os.environ.get("PIPELINE_MODE", "claudecode").lower()


def run_agent(
    stage_id: str,
    system: str,
    user: str,
    output_path: Path,
    model: str = "claude-opus-4-5",
    max_retries: int = 3,
) -> tuple:
    """
    Runs one agent call.
    Returns (json_str, system, user) — system+user kept for correction loops.
    """
    if PIPELINE_MODE == "claudecode":
        return _run_claude_code(stage_id, system, user, output_path, max_retries)
    else:
        return _run_api(stage_id, system, user, output_path, model, max_retries)


def run_correction(
    stage_id: str,
    system: str,
    original_user: str,
    original_response: str,
    correction_message: str,
    output_path: Path,
    model: str = "claude-opus-4-5",
) -> str:
    """
    Sends a correction message to the agent showing its original output
    and the specific error found. Used by Pydantic gate and Stage 5A/5B
    self-correction loops.
    Returns corrected json_str.
    """
    if PIPELINE_MODE == "claudecode":
        return _run_correction_claude_code(
            stage_id, system, original_user,
            original_response, correction_message, output_path
        )
    else:
        return _run_correction_api(
            stage_id, system, original_user,
            original_response, correction_message, output_path, model
        )


# ── Claude Code mode ──────────────────────────────────────────────────────────

def _run_claude_code(stage_id, system, user, output_path, max_retries):
    """
    Uses `claude --print` subprocess — no API key needed.
    Claude Code handles authentication and model access.
    """
    full_prompt = f"<system>\n{system}\n</system>\n\n{user}"

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [{stage_id}] running via Claude Code"
                  + (f" (attempt {attempt})" if attempt > 1 else "") + "...")
            t = time.time()

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as f:
                f.write(full_prompt)
                prompt_path = f.name

            result = subprocess.run(
                ["claude", "--print"],
                stdin=open(prompt_path),
                capture_output=True,
                text=True,
                timeout=600,
            )
            Path(prompt_path).unlink(missing_ok=True)

            if result.returncode != 0:
                raise RuntimeError(f"claude --print failed: {result.stderr[:200]}")

            raw = result.stdout
            print(f"  [{stage_id}] response received ({time.time()-t:.1f}s)")

            json_str = _extract_json(raw, stage_id)
            output_path.write_text(json_str)
            print(f"  [{stage_id}] output written -> {output_path.name}")
            return json_str, system, user

        except Exception as e:
            if attempt == max_retries:
                raise RuntimeError(f"[{stage_id}] failed after {max_retries} attempts: {e}")
            wait = 2 ** attempt
            print(f"  [{stage_id}] error: {e} — retrying in {wait}s...")
            time.sleep(wait)


def _run_correction_claude_code(
    stage_id, system, original_user,
    original_response, correction_message, output_path
):
    """Sends correction turn via claude --print multi-turn format."""
    full_prompt = f"""<system>
{system}
</system>

<user>
{original_user}
</user>

<assistant>
{original_response}
</assistant>

<user>
{correction_message}
</user>"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(full_prompt)
        prompt_path = f.name

    result = subprocess.run(
        ["claude", "--print"],
        stdin=open(prompt_path),
        capture_output=True, text=True, timeout=120,
    )
    Path(prompt_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(f"correction failed: {result.stderr[:200]}")

    json_str = _extract_json(result.stdout, stage_id)
    output_path.write_text(json_str)
    return json_str


# ── API mode ──────────────────────────────────────────────────────────────────

def _run_api(stage_id, system, user, output_path, model, max_retries):
    """Uses Anthropic API directly. Requires ANTHROPIC_API_KEY."""
    import anthropic
    client = anthropic.Anthropic()

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [{stage_id}] calling API"
                  + (f" (attempt {attempt})" if attempt > 1 else "") + "...")
            t = time.time()

            response = client.messages.create(
                model=model,
                max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )

            raw = response.content[0].text
            print(f"  [{stage_id}] response received ({time.time()-t:.1f}s)")

            json_str = _extract_json(raw, stage_id)
            output_path.write_text(json_str)
            print(f"  [{stage_id}] output written -> {output_path.name}")
            return json_str, system, user

        except Exception as e:
            if attempt == max_retries:
                raise RuntimeError(f"[{stage_id}] failed after {max_retries} attempts: {e}")
            wait = 2 ** attempt
            print(f"  [{stage_id}] error: {e} — retrying in {wait}s...")
            time.sleep(wait)


def _run_correction_api(
    stage_id, system, original_user,
    original_response, correction_message, output_path, model
):
    """Sends correction turn via API multi-turn messages."""
    import anthropic
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system,
        messages=[
            {"role": "user",      "content": original_user},
            {"role": "assistant", "content": original_response},
            {"role": "user",      "content": correction_message},
        ],
    )
    json_str = _extract_json(response.content[0].text, stage_id)
    output_path.write_text(json_str)
    return json_str


# ── Shared ────────────────────────────────────────────────────────────────────

def _extract_json(text: str, stage_id: str) -> str:
    import re
    matches = list(re.finditer(r'\{[\s\S]*\}', text))
    if not matches:
        raise RuntimeError(f"[{stage_id}] No JSON found in response.")
    json_str = matches[-1].group(0)
    json.loads(json_str)
    return json_str