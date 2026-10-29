# The Build loop runs on the developer's host, without a sandbox

The build agent's `run_command` is `sh -c` on the developer's machine. It starts in the run directory but is not confined to it, and the storefront and backend the agent writes run on the same machine as Sidecars. Shop generation has one developer, who runs it locally on Shop Manuals they made, so a sandbox costs more than it protects today. Two host-side limits apply instead. Every command and Sidecar gets an allowlisted environment (`commandEnv()`), so API keys and tokens in the developer's shell do not reach agent-run code. `runCommand` kills a command's whole process group when it exits or times out, so nothing the agent starts outlives its call.

## Considered Options

- A Build sandbox: one container per run (rootless Podman) with the run directory mounted and the shop's services inside. It confines files, network and processes, and the Verifiers would test the shop on the runtime that hosts it. It also adds a container engine, an image and lifecycle commands to every developer setup.
- Path checks in the file tools only (refuse paths and symlinks that leave the run directory): no gain while `run_command` can read any file.

## Consequences

- The agent can read and write every file the developer can, the repository `.env` and `~/.npmrc` too, and it can reach any network host. Run Shop generation only on your own machine, on inputs you trust.
- A process that starts its own session (`setsid`, a daemonizing server) escapes the process-group kill.
- The Verifiers run the shop on the host's Node and pnpm, not on the runtime that hosts it, so a shop can pass the Build loop and still fail where it is deployed.
- Revisit this decision when Shop generation runs on shared machines, in CI, or for people other than the developer who made the Shop Manuals.
