# Architecture

## State and pillar roots

This repo separates desired state from desired data:

- `states/` contains reusable Salt states, templates, and role composition.
- `pillar/` contains plain YAML data such as role booleans and vLLM settings.

The example Salt master config in `salt-master.d/redsalt-roots.conf.example` points `file_roots` at `states/` and `pillar_roots` at `pillar/`.

## Role model

`states/top.sls` targets pillar booleans rather than hostnames:

```yaml
'roles:llm_vllm:true':
  - match: pillar
  - roles.llm_vllm
```

This lets operators move hosts between roles by changing pillar only.

## Host layout

Managed vLLM hosts use deterministic paths:

| Path | Purpose |
| --- | --- |
| `/opt/models` | Operator-managed model files, mounted read-only in the vLLM container |
| `/var/cache/huggingface` | Hugging Face cache persistence |
| `/opt/redsalt/vllm/docker-compose.yml` | Generated Compose file |
| `/etc/redsalt/vllm.env` | Generated non-secret runtime environment |
| `/etc/systemd/system/vllm-openai.service` | Systemd wrapper around Docker Compose |

## vLLM deployment flow

1. `roles.base` converges base packages and system directories.
2. `roles.base` creates managed local users and authorized SSH keys from pillar, including the `darthai` automation user.
3. `roles.docker` installs Docker Engine and Compose from Docker's official Ubuntu repo.
4. `roles.nvidia` installs NVIDIA Container Toolkit and configures Docker's NVIDIA runtime.
5. `roles.llm_vllm` writes vLLM Compose/systemd files, creates model/cache directories, and starts the service.
