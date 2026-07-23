import logging
import json
import os
import time
import subprocess
from pathlib import Path

import requests

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


base_prompt = """I am trying to collect a dataset to train a better web browser agent
that can perform actions for users in a web browser. To do this, thoroughly
explore this webpage - {start_url} - and propose concrete, realistic tasks that a human
is likely to perform on this website, {website_url}, nicknamed {website_nickname}. Along with proposing tasks, you should also propose
verification criteria that can evaluate if an agent executed the task correctly.

Be specific enough that each task is self-contained. The web agent may start
from a different web page and may not have the current page context to
understand the task. Avoid vague tasks like "Add item to cart" or "Find a
gift." Instead, provide concrete user constraints, budgets, categories,
preferences, or decision criteria. Prefer tasks like "Find a gold ring under
£40 that would work as a subtle everyday gift, then add the least expensive
suitable option to cart" or "Use the personalization guide to determine what
details matter before ordering, then find a personalized necklace option and
report the required choices." Avoid making every task name the exact final
product or page, because that turns the task into instruction following instead
of shopping problem solving.

As you are exploring the page, you may find it helpful to click on buttons, links, and other elements on the page to see if they reveal
any additional information or options that could lead to new tasks. You can also hover over elements to see if they provide any tooltips
or additional context.

Use the Playwright MCP browser tools to interact with the website. Start from the browser state provided by the MCP browser tools.

# Task types

Generate DETERMINISTIC tasks with factual, verifiable answers. Focus on these types:
1. Information Seeking: The user wants to obtain certain information from the webpage (e.g., product details, comparisons, descriptions)
3. Data Aggregation: Calculate totals, counts, or combine numerical data
4. Sequential Lookup: Use information from one page to find related details on the other
5. Site Navigation: The user wants to navigate to a specific page.
6. Content Modification: The user wants to modify the content of a webpage or configuration (e.g., adding to cart or wishlist)

{task_quality_prompt}

{verification_prompt}

{tool_prompt}

{existing_tasks_prompt}

{format_prompt}

Maintain a progress log in {log_path} and refer to it to avoid repetitive exploration.

Start exploring by going to {start_url}. After you're done exploring the page, have written all task JSON files you can,
and have verified every program_evaluation task individually, close the Playwright browser session and stop.
"""


existing_tasks_prompt = """# Existing tasks

Before writing new tasks, inspect the existing task files in {task_list_dir}.
Use them to avoid duplicates or near-duplicates in goal, required action, and
target product/page.

Existing tasks are JSON files. Treat each file as one completed benchmark task.
Continue numbering from the highest existing task_id instead of overwriting or
renumbering existing files."""


task_quality_prompt = """# Task quality bar

Write goals as shopper intents, not solver instructions. The goal should state
what the shopper wants to accomplish, not the route an agent should take. Do
not tell the agent which collection, search query, filter, sort option, header
promotion, footer link, or intermediate page to use unless that source is part
of the user's real shopping need. Hide the intended solution route in the
verification criteria, not in the goal. Use vocabulary suitable for E-Commerce
websites such as collections, products.

The goal is to generate benchmark tasks that test problem solving and navigation,
not just instruction following. Prefer tasks where the agent must infer,
compare, filter, recover, or choose based on information discovered on the
website.

A strong task should combine two or more of:
- navigating through menus, collections, product pages, search, filters, or
  policy/help pages;
- comparing products, collections, variants, prices, policies, or
  product details;
- satisfying constraints such as price, material, size, color, recipient,
  personalization support, delivery/return constraints, or sale
  status;
- looking up information before taking a later navigation or cart action;
- recovering from a broad, ambiguous, or unhelpful search/filter path by
  refining the query, changing filters, clearing filters, or using navigation;
- choosing a suitable product from a category without the task naming the exact
  final product.

  
## Patterns to Avoid
- Avoid making the task too easy. Do not overproduce tasks where the final answer
  is visible after one navigation step, or where the goal names the exact final
  product/page to click. At most one in five tasks should be atomic exact-search,
  exact-navigation, or direct fact lookup tasks. Most tasks should require three
  or more meaningful browser actions.

- Do not create multi-cart-edit tasks that require adding multiple candidate
  products and then removing or reducing the number of items in the cart contents.
  Simple single-product cart tasks and single-product quantity tasks are allowed
  when they are part of a richer problem-solving journey and can be verified reliably.
  Tasks that require adding multiple carts to the product and increasing the quantity are
  allowed.

- Avoid open-ended comparisons, subjective evaluations, or "determine which is better" tasks
  that do not have a clear comparison criteria.

- IMPORTANT: Do not construct tasks based on reviews, as they are unreliable. Do not ask
  for review details in the task.

Prefer concrete constraints with hidden resolution:
- Too hinty: "Use the Engraved Gifts collection rather than an exact product
  search, compare the charm products under the budget, and navigate to the
  product page for the cheapest suitable option."
- Better: "Find the cheapest engravable charm under £25 and stop on its product
  page."
- Too hinty: "Use the site search for the broad query zodiac. From the live
  product suggestions, choose the least expensive product suggestion that is
  marked as personalisable."
- Better: "Find the least expensive personalisable zodiac-themed product and
  report its name and price."
- Too easy: "Navigate to the refund policy page."
- Better: "You are returns-cautious. Determine whether personalized jewelry has
  any special return caveats, then find a suitable non-final-sale gift product
  under the stated budget and report the product you would choose."
- Too easy: "Add the small gold slim stacking ring to the cart."
- Better: "You want the least expensive gold ring available. Find the matching
  product and add it to the cart with any required valid options."
- Too easy: "Report the price of Slim Stacking Ring."
- Better: "Compare the regular price and installment text for two stacking-ring
  candidates, then report which one has the lower upfront price and what payment
  options are shown for it."

# Reusable task templates

Use these templates generically across websites, adapting only to UI and data
that actually exist on the explored site:

1. Constraint satisfaction:
   "Find a product in <category> that satisfies <price/material/variant/use-case>
   constraints, then report it or add it to cart."

2. Policy-informed shopping:
   "Read <policy/guide/FAQ> first, then make a shopping decision that depends on
   that information."

3. Comparison:
   "Compare at least two candidate products or collections, then choose the one
   that best satisfies explicit constraints."

4. Search/filter recovery:
   "Start from a broad or ambiguous shopper need, then complete the goal after
   resolving ambiguity or irrelevant results."

5. Navigation memory:
   "Use information from one area of the site, then apply it to a later product
   choice or answer."

6. Ambiguous buyer language:
   "Use natural shopper wording such as gift-ready, personalized, under a budget,
   easy to return, matching set, travel-friendly, or beginner-friendly, and require
   the agent to map that language to the site's taxonomy and product details."
"""


verification_prompt = """# Verification criteria for tasks

The tasks should be verifiable through rule based verifiers. The verifiers can be:

## String Comparisons
- must_include: the answer should include some key strings from the ground truth
- fuzzy_match: the answer should be factually the same as ground truth, but paraphrasing is allowed

## program_evaluation
- program_evaluation: WebArena-style locator checks used to query one precise value from the website and compare it
  against explicit ground truth. This can be used to check the state of the website at any URL.
- The core function of this evaluation is to verify the state or contents of a webpage with simple, repeatable DOM
  queries. Do not write arbitrary JavaScript programs, functions, blocks, loops, object-returning scripts, or
  multi-assertion code.
- If the agent is to be evaluated for the contents of the last page it visits, the URL where the content is to be
  evaluated should be set as "last".
- Each program_evaluation criterion must contain exactly one side-effect-free JavaScript locator expression. The
  locator should query a single DOM value such as textContent, innerText, value, checked, selectedIndex, href,
  location.pathname, or the length of a querySelectorAll result.
- Use multiple program_evaluation criteria when verifying multiple facts. Prefer several small locator checks over
  one large program. This makes Playwright execution and failure diagnosis reliable.
- The locator result will be compared as content against required_contents. Use one of:
  - exact_match: the locator result must exactly match the provided string after string conversion.
  - must_include: the locator result must include every listed string after string conversion.

## Notes on verification
- Multiple verification criteria can be chained together for verifying a task.
- The evaluation should be thorough. For example, if the task is to add certain products to cart, the
  cart should contain only those product and nothing else.
- The verification of Content Modification tasks may need navigation to a different webpage within the same website.
  For example, a task that requires adding a product to the cart or wishlist may need program_evaluation on the cart page.
- For every task that uses program_evaluation, run an evaluation phase for that individual task before writing the task file:
  navigate to the evaluation URL, execute the proposed locator expression with the browser evaluation tool,
  confirm that it executes without errors, and confirm that its result satisfies required_contents.
  Only write the task file after this per-task verification succeeds.
- The URLs proposed during evaluation should not be tied to a specific host name, as the hostname where the websites
  are hosted can change (for e.g., 34.56.78.34 can change to 108.56.78.56). Replace the {website_url},
  which will be a prefix in all the URLs, with {website_nickname}.
"""


format_prompt = """# Output Format

Output the tasks as a structured JSON file in {task_save_dir} with the name <task_id>.json.

If there are no existing tasks, the task_id should start with 0. If there are existing task files,
the task_id should start with the next integer.

Each task file must contain one task object. The `eval` field is a list of
verification criteria for that specific task. Include as many eval objects as
needed to verify the task thoroughly, but do not include irrelevant evals. A
task may have one eval or multiple evals. For example, an information-seeking
task may need only `string_match`, a navigation task may need only `url_match`,
and an add-to-cart task may need one or more `program_evaluation` checks.

The task file shape is:
```json
{{
    "task_id": <task_id>,
    "goal": <the generated task to be solved by a web agent>,
    "eval": [
        <one or more eval objects chosen from the allowed shapes below>
    ]
}}
```

Allowed eval object shapes:

```json
{{
    "eval_type": "string_match",
    "reference_answer": {{
        "must_include": [
            <string1>,
            <string2>
        ]
    }}
}}
```

```json
{{
    "eval_type": "string_match",
    "reference_answer": {{
        "fuzzy_match": <ground truth answer>
    }}
}}
```

```json
{{
    "eval_type": "program_evaluation",
    "reference_answer": {{
        "url": <URL where the program is to be evaluated>,
        "locator": <side-effect-free JavaScript expression that returns one value>,
        "required_contents": {{
            "exact_match": <string>
        }}
    }}
}}
```

```json
{{
    "eval_type": "program_evaluation",
    "reference_answer": {{
        "url": <URL where the program is to be evaluated>,
        "locator": <side-effect-free JavaScript expression that returns one value>,
        "required_contents": {{
            "must_include": [
                <string1>,
                <string2>
            ]
        }}
    }}
}}
```

Example with multiple evals:

```json
{{
    "task_id": 0,
    "goal": "Add the silver oval pendant necklace to the cart.",
    "eval": [
        {{
            "eval_type": "url_match",
            "reference_answer": {{
                "url": "{website_nickname}/cart"
            }}
        }},
        {{
            "eval_type": "program_evaluation",
            "reference_answer": {{
                "url": "{website_nickname}/cart",
                "locator": "document.body.innerText",
                "required_contents": {{
                    "must_include": [
                        "Oval Pendant Necklace"
                    ]
                }}
            }}
        }},
        {{
            "eval_type": "program_evaluation",
            "reference_answer": {{
                "url": "{website_nickname}/cart",
                "locator": "document.querySelectorAll('table tbody tr').length",
                "required_contents": {{
                    "exact_match": "1"
                }}
            }}
        }}
    ]
}}
```

"""


tool_prompt = """## Core Tools

You may use only these Playwright MCP tool shapes while taking actions on the webpage:
{core_tools}

Use `mcp__playwright__browser_snapshot` for observations.
Use `mcp__playwright__browser_close` only after writing all task JSON files and verifying every program_evaluation task.
Use `mcp__playwright__browser_evaluate` only during the per-task program_evaluation verification phase described below.

## Constraints

- Do not use `browser_run_code_unsafe`, JavaScript execution,
  storage/cookie commands, file upload, file download, PDF export, request mocking,
  tracing, or direct filesystem/database inspection.
- Do not use `browser_evaluate` while exploring for tasks. It is allowed only
  to verify a proposed program_evaluation verifier before writing that individual task file.
- Do not navigate to any other website other than {website_url}.
- Use `browser_snapshot` for observations and the listed core tools for interaction.
- The webpage should be explored only using the web UI, not by directly using APIs.
- The proposed tasks should be solvable only using the web UI, not by directly using APIs.
- Write task JSON files only after their verification criteria are complete. For program_evaluation criteria,
  this means the program has been executed on the relevant URL and its result matched the expected ground truth.

## Restriction on direct URL navigation

Use direct URL navigation commands very sparingly. This applies to both
`mcp__playwright__browser_navigate(url=...)` and `mcp__playwright__browser_tabs(action="new", url=...)`.
The only acceptable direct URL navigation uses are
- Generating the verification criteria.
- Backtracking to a certain page
"""


class Explorer:

    def __init__(
            self,
            exp_dir: str,
            website_url: str,
            start_url: str,
            website_nickname: str,
        ):
        self.website_url = website_url
        self.start_url = start_url
        self.exp_dir = Path(exp_dir)
        self.website_nickname = website_nickname

    def build_prompt(self, _id):
        
        memories_dir = self.exp_dir / "progress_logs"
        memories_dir.mkdir(parents=True, exist_ok=True)

        prompts_dir = self.exp_dir / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)

        log_path = str(memories_dir / f"{_id}.md")
        prompt_file_path = prompts_dir / f"{_id}.md"

        task_config_save_dir = self.exp_dir / "task_configs"
        task_config_save_dir.mkdir(parents=True, exist_ok=True)

        status_dir = self.exp_dir / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{_id}.txt"

        if status_file.exists():
            with open(status_file, "r") as f:
                contents = f.read()
            if "Done" in contents:
                print(f"{_id} complete.")
                return

        task_tool_prompt = tool_prompt.format(
            core_tools=core_tools(),
            website_url=self.website_url,
        )

        task_format_prompt = format_prompt.format(
            task_save_dir=task_config_save_dir,
            website_nickname=self.website_nickname,
        )

        task_verification_prompt = verification_prompt.format(
            website_url=self.website_url,
            website_nickname=self.website_nickname,
        )

        task_existing_tasks_prompt = existing_tasks_prompt.format(
            task_list_dir=task_config_save_dir,
        )

        prompt = base_prompt.format(
            start_url=self.start_url,
            website_url=self.website_url,
            log_path=log_path,
            website_nickname=self.website_nickname,
            task_quality_prompt=task_quality_prompt,
            verification_prompt=task_verification_prompt,
            tool_prompt=task_tool_prompt,
            existing_tasks_prompt=task_existing_tasks_prompt,
            format_prompt=task_format_prompt
        )

        with open(prompt_file_path, "w") as f:
            f.write(prompt)

        return prompt
    
    def explore(self, _id, cwd, timeout=5*60):
        
        prompts_dir = self.exp_dir / "prompts"
        prompt_file_path = prompts_dir / f"{_id}.md"

        with open(prompt_file_path, "r") as f:
            prompt = f.read()

        env = None
        self.invoke_agent(prompt, cwd, timeout=timeout, env=env)

        status_dir = self.exp_dir / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        status_file = status_dir / f"{_id}.txt"

        with open(status_file, "w") as f:
            f.write("Done")

    def invoke_agent(self, prompt, cwd, timeout=5*60, env=None):
        cmd = ["pi", "-nc", "-p", "--provider", "openai", "--model", "gpt-5.5", "--thinking", "medium", prompt]
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode:
            output = result.stderr.strip() or result.stdout.strip()
            message = f"Solver agent failed with exit code {result.returncode}"
            if output:
                message = f"{message}: {output}"
            raise RuntimeError(message)
        
        return result
