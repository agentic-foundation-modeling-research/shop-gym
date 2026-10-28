# One TypeScript monorepo, no Python

ShopGym v1.0 was three Python packages and one TypeScript backend. About 2.8k harness lines existed only to start agent CLIs as subprocesses and parse their logs. We rebuilt everything as one pnpm workspace in strict TypeScript, with no Python in the build or runtime path. The agent SDK and Playwright now run in-process, and the backend, pipelines and graders share one set of zod types. The cost is the Python ecosystem: BrowserGym, AgentLab and Ray are no longer available.
