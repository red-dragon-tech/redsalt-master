package_updates:
  # salt = highstate pkg.uptodate; native = distro updater only.
  manager: salt
  enabled: false
  refresh: true
  debian_dist_upgrade: false
  native_unattended: false
  automatic_reboot: false
