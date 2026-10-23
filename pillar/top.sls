base:
  '*':
    - common.defaults
    - firewall.defaults
    - generated.darth_ssh_source
    - package_updates.defaults
    - roles.defaults
    - restic_backup.defaults

  'example-vllm-node':
    - minions.example-vllm-node

  'mgmt.rdt.dev':
    - minions.mgmt_rdt_dev

  'rdt-kali':
    - minions.rdt_kali
