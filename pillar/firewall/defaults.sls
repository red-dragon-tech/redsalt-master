firewall:
  enabled: true
  manage_ufw: true
  reset_unmanaged: true
  default_incoming: deny
  default_outgoing: allow
  ssh:
    port: 22
    # Fallback only. The active Darth SSH source is maintained in
    # firewall_dynamic:darth_ssh_sources from pillar/generated/darth_ssh_source.sls.
    allowed_sources:
      - 47.41.97.147/32
  salt:
    # Salt's standard ZeroMQ master ports. Keep this list restricted to Salt master IPs.
    master_ports:
      - 4505
      - 4506
    master_sources:
      - 104.250.111.198/32
  dynamic_update:
    enabled: true
    master_minion_id: mgmt.rdt.dev
    source_url: https://raw.githubusercontent.com/red-dragon-tech/redsalt-master/prd/pillar/generated/darth_ssh_source.sls
    generated_pillar_path: /srv/redsalt-master/pillar/generated/darth_ssh_source.sls
    apply_target: '*'
    interval: 5min
