roles:
  base: true
  salt_master: true
  restic_backup: true

package_updates:
  manager: salt
  enabled: true
  refresh: true
  debian_dist_upgrade: false
  latest_packages:
    - fwupd
  native_unattended: false
  automatic_reboot: true
  reboot_time: '06:00'
  unattended_upgrade_origins: []
  download_updates: true

restic_backup:
  enabled: false
  tags:
    - mgmt.rdt.dev
    - salt-master
