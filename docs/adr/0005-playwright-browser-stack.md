# One Playwright browser stack with aria-snapshot refs, no BrowserGym

v1.0 had three browser stacks: a pi Playwright skill, Playwright MCP and BrowserGym. Now `@shop-gym/browser` is the only one. Each episode gets its own Playwright context, and agents act on element refs from Playwright's native AI aria snapshot (`aria-ref=eN`), not on BrowserGym `bid` attributes. We accepted that results are no longer comparable with BrowserGym or AgentLab agents; other agents plug in through the `AgentUnderTest` interface instead.

## Considered Options

- Assign our own refs by walking the aria tree: not built. Playwright 1.63 has native refs, and our own copy would duplicate the engine's element bookkeeping and drift from it.
