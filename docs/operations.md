# Operations

## Validation

Run static checks before pushing or applying Salt:

```bash
make validate
make test
```

The validator checks required files, YAML syntax, Jinja syntax, top-file role mappings, and obvious secret leaks.

## Salt master setup

Copy or adapt:

```text
salt-master.d/redsalt-roots.conf.example
```

Then restart the Salt master:

```bash
systemctl restart salt-master
```

## Rollout workflow

1. Add or update host pillar under `pillar/minions/<minion-id>.sls`.
2. Confirm pillar data:

   ```bash
   salt '<minion-id>' pillar.items
   ```

3. Render highstate:

   ```bash
   salt '<minion-id>' state.show_highstate
   ```

4. Preview changes:

   ```bash
   salt '<minion-id>' state.apply test=True
   ```

5. Apply:

   ```bash
   salt '<minion-id>' state.apply
   ```

## vLLM service checks

On the minion:

```bash
systemctl status vllm-openai.service
journalctl -u vllm-openai.service -n 100 --no-pager
docker compose -f /opt/redsalt/vllm/docker-compose.yml ps
curl -fsS http://127.0.0.1:8000/v1/models
```

## GPU checks

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

## Model management

Place model files or model directories under `/opt/models`. The default vLLM model is `/models/model`, which maps to `/opt/models/model` on the host. Change `vllm:model` in pillar when using a Hugging Face model ID or a different local path.
