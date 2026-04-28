Task: $task_description

Trajectory:
$anonymized_trajectory

Score this trajectory on the three quality dimensions. You MUST cite
specific screenshot indices or snapshot lines as evidence for every
factual claim.

Respond as JSON only, with the following shape:

{
  "ratings": {
    "visual_coherence": 1..5,
    "copy_realism": 1..5,
    "error_plausibility": 1..5
  },
  "evidence": [
    {
      "ref": "screenshot_07" | "snapshot_12:L34",
      "claim": "..."
    }
  ],
  "rationale": "..."
}
