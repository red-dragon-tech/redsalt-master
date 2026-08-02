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

SSH public keys, such as entries under `managed_users:*:ssh_authorized_keys`, are not secrets and may be committed for intended access management. Never commit the matching private key.

## Secret migration options

When secrets are needed, prefer one of these patterns:

1. Salt GPG renderer for encrypted pillar values.
2. SOPS-rendered pillar in CI/CD or on the Salt master.
3. Vault or another `ext_pillar` backend.
4. Host-local files provisioned outside this repo and referenced by path.

For phase-1 fleet restic backups, use option 4: manual root-only host-local files. Salt may create placeholders and enforce `0600`, but B2 application keys and restic repository passwords must be provisioned out-of-band and must not be committed to plain pillar or GitHub issues.

Restic backup policy decisions:

- Use one unique restic repository password per host.
- Use one non-master B2 application key per host/prefix where practical.
- Permit `deleteFiles` on those scoped keys so `restic forget --prune` works.
- Treat immutable/copy-bucket backups as a later enhancement with separate credentials.

## Network exposure

vLLM is an OpenAI-compatible API and should not be exposed directly to the public internet without authentication, TLS, rate limits, and logging. Bind or firewall service ports to LAN/VPN by default.

## Host firewall baseline

`roles.base` enables UFW and denies inbound traffic by default. The managed allowlist is intentionally narrow:

- SSH (`22/tcp`) only from Darth's current public IPv4 `/32`, supplied by generated pillar.
- Salt standard ports (`4505/tcp`, `4506/tcp`) only from configured Salt master IPv4 `/32` sources.

Do not broaden these CIDRs in committed pillar unless there is an explicit operational requirement. If Darth's public IP changes, update `pillar/generated/darth_ssh_source.sls` in the production branch so the Salt master can pull it outbound and reapply firewall rules without requiring inbound SSH from the new address first.

## Grains and targeting

Do not use grains as an authorization boundary. Grains are minion-controlled. Use pillar for intended roles and keep sensitive policy on the master side.
