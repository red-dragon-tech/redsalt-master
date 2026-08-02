roles:
  base: true
  salt_master: true
  restic_backup: true

restic_backup:
  enabled: false
  tags:
    - mgmt.rdt.dev
    - salt-master
