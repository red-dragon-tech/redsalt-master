# Promptfoo MCP red-team workstation deployment

The `kali_workstation` role has an opt-in Promptfoo integration for the authorized Kali workstation. Host pillar in `pillar/minions/rdt_kali.sls` enables the integration and defines its repo/project paths, owner/group and initial target placeholder.

## What highstate does

With `kali_workstation:promptfoo_mcp_redteam:enabled: true`, highstate:

1. Installs the distribution's `nodejs` and `npm` packages; Kali/Debian's npm package supplies `npx`.
2. Creates the project directory with mode `0750`, owned by `darthai:users` by default.
3. Invokes the tracked `/opt/shared/kali-linux/scripts/setup/promptfoo_mcp_redteam.py init` helper as the project owner. The helper is expected to be available from the tracked Kali repository.
4. Runs the helper's read-only prerequisite/config-file check.

The default project directory is `/opt/promptfoo-mcp-redteam`; it is owned by `darthai:users` with mode `0750`, and it remains outside shared backups/repo tracking. The helper preserves existing project files. Salt checks for all expected scaffold files before deciding initialization is already complete, so missing individual files can be filled without overwriting an operator's existing ROE or Promptfoo configuration. A one-time init failure is surfaced by highstate rather than silently ignored. Runtime providers and `npx` downloads need outbound package-registry access.

## What highstate does not do

- It does not clone, fetch, or update `hacknbone/kali-linux`; repository promotion/sync remains a separately approved workflow.
- It does not run `promptfoo redteam run`, invoke active red-team tools, perform target testing, or start the MCP server.
- It does not configure an OpenAI/Anthropic/Promptfoo API credential. Never put provider keys in Git or plaintext pillar.
- It does not expose an MCP listener over HTTP. Configure the consuming MCP client separately and keep the transport local stdio.
- It does not set an approved test target; the scaffold deliberately starts with `https://REPLACE-WITH-AUTHORIZED-MCP-ENDPOINT.example/mcp`.

The distro Node.js version may differ from Promptfoo's current red-team quickstart minimum (`>=22.22.0`). Check the installed runtime before use; do not silently install Node from an unreviewed third-party repository. If Kali's packaged runtime is too old, make the runtime source/version a separately reviewed choice before changing this state.

## Authorization and engagement setup

Before any active test, the system owner and operator must complete `ROE.md` in the local project, record written approval, exact target, test window, exclusions, permitted plugins/actions, test identities, limits/stop conditions, and evidence handling, and configure the exact same single endpoint in `promptfooconfig.yaml`. The helper's CLI runner has additional explicit-authorization and exact-target checks, but does not prove the validity/currentness of the approval. Direct Promptfoo MCP `redteam_run` tool calls are active tests and do not pass through that CLI gate; only connect a client when the operator has an approved process to control tool invocation.

Install provider/model credentials using an approved host-local secret mechanism or secure environment injection. Do not add them to pillar, project files, state logs, or this repository. Decide whether Promptfoo's optional hosted attack-generation/grading services are acceptable for the engagement before configuring providers.

## Validate and preview

From the master repository root:

```bash
make validate
make test
salt 'rdt-kali' test.ping
salt 'rdt-kali' pillar.items
salt 'rdt-kali' state.show_highstate
salt 'rdt-kali' state.apply kali_workstation test=True
salt 'rdt-kali' state.apply test=True
```

Inspect the exact rendered plan for package changes, project directory, and commands. Confirm the repo helper exists at `/opt/shared/kali-linux/scripts/setup/promptfoo_mcp_redteam.py` and the minion is connected before preview. Test mode is preview only; it does not install packages or create the workspace.

After separate review/approval to converge, apply only to `rdt-kali`, then verify `node --version`, `npm --version`, `npx --version`, and run the helper `check` as the owner. Verify no scan or MCP service was started. This documentation does not authorize a live state apply or red-team engagement.
