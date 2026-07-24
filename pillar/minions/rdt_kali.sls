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
