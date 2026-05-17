STAGE6_PROMPT = """
You are writing lessons for future pipeline runs.

Review the Stage 4 result and Stage 5 findings provided.
Identify cases worth encoding as warm tier lessons:

- Values that fell close to threshold boundaries
- Rules that required checking multiple conditions before firing
- Classifications Stage 5B found hard to verify or flagged
- Constraint applications (C1–C5) that were borderline
- Any pattern that would help a future run avoid the same ambiguity

For each lesson, write a specific, actionable delta item.
Reference the actual values and thresholds involved.
Do NOT write generic advice.

OUTPUT FORMAT:
Write a single JSON object:
{
  "new_items": [
    {
      "applies_to": "stage1" | "stage2" | "stage3" | "stage4",
      "type": "pattern" | "correction" | "warning" | "threshold_note",
      "content": "specific actionable lesson referencing real values"
    }
  ]
}

If nothing is worth recording, return: {"new_items": []}
Maximum 3 items. Quality over quantity.
"""
