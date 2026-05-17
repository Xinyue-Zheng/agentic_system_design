# USID Outage Impact Assessment — Harness v2.0

## How this differs from the old SKILL.md design

### Old design
```
Claude Code reads SKILL.md
→ Claude does everything: orchestration, validation, reasoning
→ Python only used for local_preprocessing.py
→ No validation between stages
→ Stages run sequentially inside one session
→ Same context window for all stages
```

### New design (harness)
```
Python (pipeline.py) orchestrates everything
→ Claude API called for reasoning only
→ Python controls: what runs, when, in what order
→ Pydantic gate validates every stage output
→ Stage 1 + Stage 2 run in parallel (asyncio)
→ Context reset between Stage 3 and Stage 4
→ Stage 5A verifies numbers in pure Python
→ Stage 6 writes lessons to playbook.json
```

## File structure

```
harness/
│
├── pipeline.py              ← THE HARNESS ORCHESTRATOR
│                              Run this instead of SKILL.md
│
├── core/
│   ├── agents_md.py         ← Hot + warm tier loader (kernel)
│   ├── mcp_log.py           ← I/O driver (audit log)
│   ├── deterministic_checks.py  ← Stage 5A (fault detector)
│   └── playbook.py          ← ACE warm tier manager
│
├── schemas/
│   ├── stage1.py            ← Stage 1 Pydantic schema
│   ├── stage2.py            ← Stage 2 Pydantic schema
│   ├── stage3.py            ← Stage 3 Pydantic schema
│   ├── stage4.py            ← Stage 4 Pydantic schema
│   └── stage5.py            ← Stage 5B output schema
│
└── stages/
    ├── stage1_prompt.py     ← Stage 1 agent prompt
    ├── stage2_prompt.py     ← Stage 2 agent prompt
    ├── stage3_prompt.py     ← Stage 3 agent prompt
    ├── stage4_prompt.py     ← Stage 4 agent prompt
    ├── stage5b_prompt.py    ← Adversarial evaluator prompt
    └── stage6_prompt.py     ← ACE reflector prompt

/workspace/
├── AGENTS.md                ← Hot tier (fixed 3GPP rules)
└── context/
    └── playbook.json        ← Warm tier (grows after each PASS)
```

## How to run

### Full pipeline (same as your old SKILL.md trigger)
```bash
python harness/pipeline.py \
    --target-usid USID_00 \
    --shutdown-start "2024-03-15 08:00" \
    --shutdown-end   "2024-03-15 12:00"
```

### Re-run from a specific stage (after fixing a failure)
```bash
python harness/pipeline.py \
    --target-usid USID_00 \
    --shutdown-start "2024-03-15 08:00" \
    --shutdown-end   "2024-03-15 12:00" \
    --from-stage 3
```

## What happens on each type of failure

| Failure point | Cause | What to fix | Re-run command |
|---|---|---|---|
| Gate 1 fails | Stage 1 schema violation | Fix Stage 1 prompt or field format | `--from-stage 1` |
| Gate 2 fails | Stage 2 schema violation | Fix Stage 2 prompt or field format | `--from-stage 2` |
| Gate 3 fails | Stage 3 schema violation | Fix Stage 3 prompt or field format | `--from-stage 3` |
| Gate 4 fails | Stage 4 schema violation | Fix Stage 4 prompt or field format | `--from-stage 4` |
| Stage 5A fails | Numeric fact wrong | Check which stage cited the wrong number, fix its field path instruction | `--from-stage N` |
| Stage 5B fails | Reasoning error | Check which rule was mis-applied, clarify AGENTS.md or stage prompt | `--from-stage N` |

Stage 6 only runs after both Stage 5A and 5B pass.
Playbook is never updated on failure.
