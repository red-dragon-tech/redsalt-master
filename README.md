# redsalt-master

Production-oriented Salt state and pillar repository for managing Ubuntu Linux systems and NVIDIA GPU hosts that serve local LLMs with Docker and vLLM.

## Scope

This repository is intentionally role-driven and standards-based:

- **Target OS:** Ubuntu
- **Configuration engine:** Salt state tree + plain pillar
- **Container runtime:** Docker Engine + Docker Compose plugin
- **GPU stack:** NVIDIA Container Toolkit, with optional driver package management
- **LLM runtime:** vLLM OpenAI-compatible server
- **Model path:** `/opt/models`, mounted into containers as `/models:ro`
- **Secrets:** no real secrets are committed; use plain pillar placeholders only until GPG/SOPS/Vault/ext_pillar is introduced
- **Baseline access:** `roles.base` creates the `darthai` SSH user with Darth's public key from plain pillar

## Repository layout

```text
.
├── docs/                  # Architecture, operations, security notes
├── pillar/                # Plain pillar data and example minion role assignment
├── salt-master.d/         # Example Salt master roots configuration
├── scripts/               # Static validation helpers
├── states/                # Salt state tree
└── tests/                 # Repo-local validation tests
```

## Roles

Hosts opt in through pillar booleans:

```yaml
roles:
  base: true
  docker: true
  nvidia: true
  llm_vllm: true
```

Role composition states live in `states/roles/` and keep `states/top.sls` small.

## Managed SSH access

The base role includes `states/users/init.sls`, which reads `managed_users` from pillar. The default pillar creates a `darthai` user with key-only SSH access using Darth's Ed25519 public key. Public SSH keys are intentionally non-secret; do not commit private keys or password hashes.

## Quick start

Validate the repository without a running Salt master:

```bash
python3 scripts/validate.py
python3 -m pytest tests -q
```

Configure a Salt master to use this checkout by adapting:

```text
salt-master.d/redsalt-roots.conf.example
```

Preview a highstate for a target minion:

```bash
salt 'example-vllm-node' state.show_highstate
salt 'example-vllm-node' state.apply test=True
```

Apply after review:

```bash
salt 'example-vllm-node' state.apply
```

## Example vLLM defaults

The example pillar at `pillar/minions/example-vllm-node.sls` deploys:

- Docker Engine from Docker's official Ubuntu apt repository
- NVIDIA Container Toolkit from NVIDIA's official apt repository
- `/opt/models` model storage
- vLLM container image `vllm/vllm-openai:latest`
- OpenAI-compatible API on port `8000`
- Systemd wrapper service `vllm-openai.service`

## Security notes

Plain pillar is acceptable for non-secret role and service defaults, but do **not** commit tokens, passwords, private keys, or vendor API keys. See `docs/security.md` for migration options.
