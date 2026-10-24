# RDT Kali shared security workstation baseline.
# Keep this conservative: manage OS/workstation hygiene and shared conventions,
# not offensive-security evidence, target artifacts, or per-user experiments.
roles:
  base: true
  docker: false
  nvidia: false
  llm_vllm: false
  salt_master: false
  kali_workstation: true
  restic_backup: true

package_updates:
  # Kali rolling updates are scheduled from the Salt master, never from an
  # ordinary highstate. Keep Debian dependency-changing distribution upgrades
  # and unattended native APT updates disabled.
  manager: salt
  enabled: true
  scheduled: true
  # Leave blank until an operator approves the hash of the exact planned diff.
  approved_preview_sha256: ''
  refresh: true
  debian_dist_upgrade: false
  native_unattended: false
  automatic_reboot: false
  cadence_days: 7
  stale_after_days: 9
  window_days:
    - Sat
  window_start: '02:00'
  window_end: '05:00'
  timezone: America/Chicago
  require_idle: true
  max_upgrades: 750
  timeout_seconds: 3600

restic_backup:
  enabled: false
  tags:
    - rdt-kali
    - kali-workstation
  includes:
    - /etc
    - /root
    - /home
    - /opt
    - /usr/local
    - /var/lib
    - /var/spool/cron
    # Reviewed Kali evidence/artifact paths belong here when created.
    # Keep reconstructable tool caches and large wordlists excluded by default.
  excludes:
    - /proc
    - /sys
    - /dev
    - /run
    - /tmp
    - /var/tmp
    - /var/cache
    - /var/log/*.log
    - /var/lib/docker/overlay2
    - /var/lib/containerd
    - /var/lib/kubelet
    - /usr/share/wordlists
    - /opt/shared/kali-linux/.git
    - lost+found
    - '*.cache'

common:
  timezone: America/Chicago
  packages:
    - ca-certificates
    - curl
    - git
    - gnupg
    - lsb-release
    - ncdu
    - python3
    - python3-venv
    - tmux
    - ufw
    - vim
  managed_directories:
    - /opt/redsalt
    - /etc/redsalt
    - /opt/shared

firewall_dynamic:
  # Override the global public-only Darth source for this LAN workstation so
  # the active Hermes host can still SSH after UFW is managed.
  darth_ssh_sources:
    - 10.10.10.184/32
    - 47.41.97.147/32

firewall:
  salt:
    # rdt-kali is on the same private LAN as the Hermes/Kali operator path.
    # Salt minion traffic is outbound to the master; these rules govern inbound
    # Salt ports on the minion and remain tightly scoped.
    master_sources:
      - 10.10.10.0/24
      - 104.250.111.198/32

kali_workstation:
  shared_root: /opt/shared
  shared_repos:
    - path: /opt/shared/kali-linux
      owner: darthai
      group: users
      mode: '2775'
      safe_directory_users:
        - darthai
        - hacknbone
  shell_helpers:
    - user: darthai
      home: /home/darthai
    - user: hacknbone
      home: /home/hacknbone
