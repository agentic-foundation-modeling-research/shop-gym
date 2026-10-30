Point-in-time review reports: self-contained HTML pages that the team reads
together to review a design or a plan before or during the work.

A report is a snapshot. We do not update it after the review. The lasting
design of a shipped feature goes to `docs/specs/`, hard-to-reverse decisions
go to `docs/adr/`, and domain terms go to `GLOSSARY.md`.

Open a report in a browser. Each one is a single file with inline CSS and JS;
only the web fonts load from the network.

Rules for a new report:

- Name it `YYYY-MM-DD-<slug>.html`, with the date of the review.
- Keep it self-contained: no build step, no local assets.
- Do not name real merchants or include their URLs. Use `__SHOP__` or a
  placeholder.
- Add a row to the index below.

## Index

| Date | Report | Topic |
| ---- | ------ | ----- |
| 2026-10-29 | [2026-10-29-task-generation-review.html](2026-10-29-task-generation-review.html) | Task generation (BFS + explore): the graph algorithm and its verification, the Task record with five example Tasks, the first trial on 1 SandboxShop + 1 Live storefront, the 21-ticket plan, and open questions. |
