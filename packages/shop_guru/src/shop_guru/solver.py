# ruff: noqa: E501

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


CORE_SOLVER_TOOLS = [
    "mcp__playwright__browser_navigate(url)",
    "mcp__playwright__browser_click(target)",
    "mcp__playwright__browser_type(target, text)",
    "mcp__playwright__browser_hover(target)",
    "mcp__playwright__browser_select_option(target, values)",
    "mcp__playwright__browser_press_key(key)",
    "mcp__playwright__browser_wait_for(time|text|textGone)",
    "mcp__playwright__browser_navigate_back()",
    "mcp__playwright__browser_tabs(action='new', url?)",
    "mcp__playwright__browser_tabs(action='close', index?)",
    "mcp__playwright__browser_tabs(action='select', index)",
    "mcp__playwright__browser_tabs(action='list')",
]


def core_tools() -> str:
    return "\n".join(f"- `{tool}`" for tool in CORE_SOLVER_TOOLS)


base_prompt = """You are a UI assistant capable of solving tasks on websites.

Use the Playwright MCP browser tools to interact with the website. Start from
the browser state provided by the MCP browser tools.

{solver_prompt}

{program_evaluation_evidence_prompt}

# Task
{task}

Start solving the task by going to {start_url}.
"""


solver_prompt = """# Solving the task

Solve the given task using only the core Playwright MCP tools listed below.

## Core Solver Tools

You may use only these Playwright MCP tool shapes while taking actions on the webpage:
{core_tools}

Use `mcp__playwright__browser_snapshot` for observations and to save snapshot artifacts.
Use `mcp__playwright__browser_close` only after writing the final answer.
Use `mcp__playwright__browser_evaluate` only in the final program_evaluation evidence phase, if one is provided below.

## Solver Constraints

- Do not use `browser_run_code_unsafe`, JavaScript execution,
  storage/cookie commands, file upload, file download, PDF export, request mocking,
  tracing, or direct filesystem/database inspection.
- Do not use `browser_evaluate` while solving the task. It is allowed only in
  the final program_evaluation evidence phase, if one is provided below.
- Do not navigate to any other website other than {website_url}.
- Use `browser_snapshot` for observations and the listed core tools for interaction.
- Return only the final answer required by the task after saving the required
  artifacts and closing the Playwright browser.
- The task should be solved only using the web UI, not by directly using APIs.
- Use at most {max_steps} steps. If you need more steps to complete the task, report the task
  as infeasible.

Start solving by navigating to {start_url}. Use `mcp__playwright__browser_snapshot(filename="{snapshot_dir}/1_snapshot.yaml")`
for this first snapshot so it is saved directly to the required artifact path.

The task must be solved as a numbered sequence of steps. Each step has exactly one action.
Snapshot tool calls are observations only and never count as actions.
For Step N:
1. Begin with the snapshot for Step N with
   `mcp__playwright__browser_snapshot(filename="{snapshot_dir}/<N>_snapshot.yaml")`
2. Choose exactly one action using only information available in the Step N snapshot.
3. Perform exactly one core solver tool call as the Step N action. All core solver tool calls count as actions,
   including tab switching, waits, navigation commands, calculator interactions, and commands that fail or do
   not visibly change the page.
4. After the action, take a new snapshot with
   `mcp__playwright__browser_snapshot(filename="{snapshot_dir}/<N+1>_snapshot.yaml")`.
   This new snapshot is the snapshot for Step N+1.

## Restriction on direct URL navigation

Use direct URL navigation commands very sparingly. This applies to both
`mcp__playwright__browser_navigate(url=...)` and `mcp__playwright__browser_tabs(action="new", url=...)`.
For a Step N, the only acceptable direct URL navigation uses are
- If there's no way to complete the task or your intermediate goal without using any other commands
- When a useful url is encountered in Step N's snapshot or any snapshots before Step N

Finally, after you have found the answer:
1. Do not navigate away from the page where you find the answer
2. If a program_evaluation evidence phase is provided below, run it before writing the final answer JSON file.
3. Write exactly one JSON object to {final_answer_path}. This is an `answer.json` file, not a Markdown file.
   Do not wrap it in Markdown fences, do not include comments, and do not include any text before or after the JSON.
   The JSON object must have this shape:
   ```
   {{
     "url": "<url of the final page>",
     "final_answer": "<final_answer>",
     "program_evaluation_results": []
   }}
   ```
   Be concise in `final_answer`; no need for excess explanations. If the task mentions a specific format, follow it.
4. If a program_evaluation evidence phase is provided, set `program_evaluation_results` to the exact results array
   requested by that phase. If no program_evaluation evidence phase is provided, use an empty array.
5. Close the Playwright browser with `mcp__playwright__browser_close`.

## Task Infeasibility

If a task is infeasible, write exactly one JSON object to the answer JSON file at {final_answer_path} with this shape:
```
{{
  "url": "<url of the page where infeasibility was determined, or empty string if unavailable>",
  "final_answer": "N/A",
  "reason": "<reason>",
  "program_evaluation_results": []
}}
```
"""


program_evaluation_evidence_prompt = """
## Final program_evaluation evidence phase

After solving the user task and while the browser is still on the final page, run these program_evaluation evidence probes.
This phase is the only time you may use `mcp__playwright__browser_evaluate`.

For each probe, in order:
1. If `url` is `last`, run the probe on the final page where you completed the task, without navigating.
   If `url` is not `last`, navigate to that URL first and wait for the page to load.
2. Run the `locator` JavaScript expression and record its returned value as a string. If the expression throws, record an empty string.
3. Do not compare against expected answers yourself. Only record the observed values.

Add the recorded evidence to the `program_evaluation_results` array in the single JSON object written to
the answer JSON file at {final_answer_path}. Do not write a Markdown or fenced JSON block.
`program_evaluation_results` must contain exactly one object for each required probe, in the same order.
For every result object:
- `index` must be the integer index from the required probe.
- `url` must be the probe URL you evaluated. Keep `last` as the literal string `last`.
- `locator` must exactly match the required probe's `locator` string.
- `value` must be the observed locator return value converted to a string. Use `""` for null, undefined, missing elements, or thrown locator errors.

Do not include Markdown, commentary, pass/fail labels, expected values, or extra keys in the result objects.
The expected answer file shape is shown below for readability. Write only the JSON object,
without the surrounding Markdown fence:

```json
{{
  "url": "http://example.test/final-page",
  "final_answer": "DONE",
  "program_evaluation_results": [
    {{
      "index": 0,
      "url": "last",
      "locator": "document.querySelector('example').textContent",
      "value": "observed value"
    }}
  ]
}}
```

The required probes are:

```json
{program_evaluation_probes}
```
"""


def resolve_url(url: str, website_url: str, website_nickname: str) -> str:
    """Resolve an explorer task URL placeholder to the live website URL.

    Args:
        url: URL value from a generated task evaluator.
        website_url: Live storefront origin used for solving.
        website_nickname: Stable nickname placeholder used in task configs.

    Returns:
        A browser-navigable URL, or ``"last"`` for last-page evaluators.

    Raises:
        ValueError: If the URL uses an unsupported relative or placeholder form.
    """
    if url == "last":
        return url
    if url.startswith(website_nickname):
        return f"{website_url.rstrip('/')}{url.removeprefix(website_nickname)}"
    if url.startswith(website_url):
        return url
    raise ValueError(f"Unsupported program_evaluation URL: {url}")


def program_evaluation_probes(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return non-answer program-evaluation probes from a generated task."""
    evals = config.get("eval", [])
    if not isinstance(evals, list):
        raise ValueError("Task config field 'eval' must be a list")

    probes: list[dict[str, Any]] = []
    for eval_item in evals:
        if not isinstance(eval_item, dict):
            raise ValueError("Each task eval item must be an object")
        if eval_item.get("eval_type") != "program_evaluation":
            continue

        reference_answer = eval_item.get("reference_answer")
        if not isinstance(reference_answer, dict):
            raise ValueError("program_evaluation eval must include reference_answer")
        probe = {
            "url": reference_answer["url"],
            "locator": reference_answer["locator"],
        }
        probes.append(probe)
    return probes


def build_program_evaluation_evidence_prompt(
    config: dict[str, Any],
    website_url: str,
    website_nickname: str,
    final_answer_path: Path,
) -> str:
    """Build the evidence prompt for program_evaluation task criteria."""
    probes = program_evaluation_probes(config)
    if not probes:
        return ""

    resolved_probes = []
    for index, probe in enumerate(probes):
        resolved_probe = {
            "index": index,
            "url": resolve_url(str(probe["url"]), website_url, website_nickname),
            "locator": probe["locator"],
        }
        resolved_probes.append(resolved_probe)

    return program_evaluation_evidence_prompt.format(
        final_answer_path=final_answer_path,
        program_evaluation_probes=json.dumps(
            resolved_probes,
            indent=2,
            ensure_ascii=False,
        ),
    )


class Solver:
    def __init__(
        self,
        exp_dir: str,
        website_url: str,
        website_nickname: str,
        max_steps: int = 20,
    ):
        self.website_url = website_url
        self.exp_dir = Path(exp_dir)
        self.website_nickname = website_nickname
        self.max_steps = max_steps

    def build_prompt(self, config):
        task_id = config["task_id"]
        start_url = self.website_url
        goal = config["goal"]

        task_dir = self.exp_dir / f"{task_id}"
        task_dir.mkdir(parents=True, exist_ok=True)

        final_answer_path = task_dir / "answer.json"
        snapshot_dir = task_dir / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        task_solver_prompt = solver_prompt.format(
            core_tools=core_tools(),
            website_url=self.website_url,
            start_url=start_url,
            snapshot_dir=snapshot_dir,
            final_answer_path=final_answer_path,
            max_steps=self.max_steps,
        )
        task_prompt = base_prompt.format(
            solver_prompt=task_solver_prompt,
            program_evaluation_evidence_prompt=build_program_evaluation_evidence_prompt(
                config=config,
                website_url=self.website_url,
                website_nickname=self.website_nickname,
                final_answer_path=final_answer_path,
            ),
            task=goal,
            start_url=start_url,
        )
        prompt_save_path = task_dir / "prompt.md"
        with open(prompt_save_path, "w") as f:
            f.write(task_prompt)

        return prompt_save_path

    def solve(self, config, cwd, timeout=5 * 60):
        task_id = config["task_id"]

        task_dir = self.exp_dir / f"{task_id}"

        prompt_path = task_dir / "prompt.md"
        with open(prompt_path) as f:
            prompt = f.read()

        # playwright_mcp_output_dir = task_dir / ".playwright-mcp"
        # playwright_mcp_user_data_dir = task_dir / ".pw-profile"
        # playwright_mcp_output_dir.mkdir(parents=True, exist_ok=True)
        # playwright_mcp_user_data_dir.mkdir(parents=True, exist_ok=True)

        # env = os.environ.copy()
        # env["PLAYWRIGHT_MCP_ISOLATED"] = "1"
        # env["PLAYWRIGHT_MCP_OUTPUT_DIR"] = str(playwright_mcp_output_dir)
        # env["PLAYWRIGHT_MCP_USER_DATA_DIR"] = str(playwright_mcp_user_data_dir)

        env = None
        self.invoke_agent(prompt, cwd, timeout=timeout, env=env)

        return (
            (task_dir / "answer.json").exists()
            and (task_dir / "snapshots").exists()
            and (task_dir / "prompt.md").exists()
        )

    def invoke_agent(self, prompt, cwd, timeout=5 * 60, env=None):
        cmd = [
            "pi",
            "-nc",
            "-p",
            "--provider",
            "openai",
            "--model",
            "gpt-5.5",
            "--thinking",
            "medium",
            prompt,
        ]
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        if result.returncode:
            output = result.stderr.strip() or result.stdout.strip()
            message = f"Solver agent failed with exit code {result.returncode}"
            if output:
                message = f"{message}: {output}"
            raise RuntimeError(message)

        return result
