Task: $task_description

Trajectory A:
$anonymized_trajectory_a

Trajectory B:
$anonymized_trajectory_b

Decide which trajectory is from the real Shopify-powered storefront.
You MUST cite specific screenshot indices or snapshot lines as
evidence for every factual claim. If you cannot cite evidence,
output "abstain".

Respond as JSON only, with the following shape:

{
  "pick": "A" | "B" | "abstain",
  "confidence": 0.0..1.0,
  "evidence": [
    {
      "trajectory": "A" | "B",
      "ref": "screenshot_07" | "snapshot_12:L34",
      "claim": "..."
    }
  ],
  "rationale": "..."
}
