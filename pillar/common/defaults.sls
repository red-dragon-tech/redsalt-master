common:
  timezone: UTC
  packages:
    - ca-certificates
    - curl
    - gnupg
    - lsb-release
    - python3
    - python3-venv
  managed_directories:
    - /opt/redsalt
    - /etc/redsalt

managed_users:
  - name: darthai
    fullname: Darth AI
    shell: /bin/bash
    home: /home/darthai
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMKydWK+ac8LWsdujDXLIVTfAo5D1PxMr0+pcUn6Z5sG darth@hermes-agent-rdt-dev-1-remote-management
