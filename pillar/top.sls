base:
  '*':
    - common.defaults
    - firewall.defaults
    - generated.darth_ssh_source
    - roles.defaults

  'example-vllm-node':
    - minions.example-vllm-node

  'mgmt.rdt.dev':
    - minions.mgmt_rdt_dev
