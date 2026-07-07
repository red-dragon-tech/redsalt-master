# Security

## Plain pillar boundary

This repository uses plain pillar because that was the requested starting point. Plain pillar is suitable for non-secret desired state such as role assignments, ports, image tags, and runtime flags.

Do **not** commit:

- Hugging Face tokens
- API keys
- SSH private keys
- Password hashes unless intentionally managed and reviewed
- Registry credentials
- TLS private keys

## Secret migration options

When secrets are needed, prefer one of these patterns:

1. Salt GPG renderer for encrypted pillar values.
2. SOPS-rendered pillar in CI/CD or on the Salt master.
3. Vault or another `ext_pillar` backend.
4. Host-local files provisioned outside this repo and referenced by path.

## Network exposure

vLLM is an OpenAI-compatible API and should not be exposed directly to the public internet without authentication, TLS, rate limits, and logging. Bind or firewall service ports to LAN/VPN by default.

## Grains and targeting

Do not use grains as an authorization boundary. Grains are minion-controlled. Use pillar for intended roles and keep sensitive policy on the master side.
