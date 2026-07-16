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

## Salt master production sync

The management minion `mgmt.rdt.dev` has the `salt_master` role in `pillar/minions/mgmt.rdt.dev.sls`. That role manages `redsalt-master-sync.timer`, which runs every minute and:

1. fetches `origin/prd` into `/srv/redsalt-master`
2. fast-forwards the checkout when the production commit changes
3. runs `scripts/validate.py`
4. runs `salt-run fileserver.update`
5. refreshes pillar data for all minions
6. applies highstate to all minions

The timer records the last successfully applied production SHA in `/var/lib/redsalt/last-prd-apply.sha`, so unchanged ticks are no-ops. Logs are written to `/var/log/redsalt-master-sync.log`.

Inspect or force a sync:

```bash
systemctl list-timers redsalt-master-sync.timer --all
systemctl status redsalt-master-sync.service
systemctl start redsalt-master-sync.service
tail -200 /var/log/redsalt-master-sync.log
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

## SSH access checks

The base role manages the `darthai` account and its `authorized_keys` entries from `managed_users` pillar. After applying highstate, verify on a managed minion:

```bash
id darthai
sudo -u darthai test -d /home/darthai/.ssh
sudo test -f /home/darthai/.ssh/authorized_keys
```

## Firewall operations

The base role manages UFW through `states/firewall/init.sls`. It intentionally resets unmanaged UFW rules when `firewall:reset_unmanaged` is true so broad allow rules do not survive highstate.

Default managed policy:

- deny incoming traffic by default
- allow outgoing traffic by default
- allow `22/tcp` only from Darth's current public `/32`
- allow Salt ports `4505/tcp` and `4506/tcp` only from configured Salt master `/32` sources

Preview/apply firewall only:

```bash
salt '<minion-id>' state.apply firewall test=True
salt '<minion-id>' state.apply firewall
```

On the Salt master, the `redsalt-firewall-refresh.timer` maintains Darth's dynamic SSH source by pulling `pillar/generated/darth_ssh_source.sls` from the production GitHub branch over HTTPS and then applying the firewall state if the source changed:

```bash
systemctl status redsalt-firewall-refresh.timer
systemctl start redsalt-firewall-refresh.service
journalctl -u redsalt-firewall-refresh.service -n 100 --no-pager
```

Manual emergency update on the Salt master:

```bash
install -d -m 0755 /srv/redsalt-master/pillar/generated
cat > /srv/redsalt-master/pillar/generated/darth_ssh_source.sls <<'EOF'
firewall_dynamic:
  darth_ssh_sources:
    - X.X.X.X/32
EOF
salt-run fileserver.update
salt '*' saltutil.refresh_pillar
salt '*' state.apply firewall
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
