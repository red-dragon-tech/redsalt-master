{% set codename = grains.get('oscodename', 'jammy') %}
{% set arch = grains.get('osarch', 'amd64') %}
{% set docker_arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(arch, arch) %}

include:
  - common

docker-keyring-dir:
  file.directory:
    - name: /etc/apt/keyrings
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

# Public vendor key; replace skip_verify with a pinned source_hash in regulated environments.
docker-apt-key:
  file.managed:
    - name: /etc/apt/keyrings/docker.asc
    - source: https://download.docker.com/linux/ubuntu/gpg
    - skip_verify: True
    - mode: '0644'
    - require:
      - file: docker-keyring-dir

docker-apt-repo:
  pkgrepo.managed:
    - humanname: Docker CE stable
    - name: deb [arch={{ docker_arch }} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu {{ codename }} stable
    - file: /etc/apt/sources.list.d/docker.list
    - clean_file: True
    - require:
      - file: docker-apt-key

docker-engine-packages:
  pkg.installed:
    - refresh: True
    - pkgs:
      - docker-ce
      - docker-ce-cli
      - containerd.io
      - docker-buildx-plugin
      - docker-compose-plugin
    - require:
      - pkgrepo: docker-apt-repo

docker-daemon-config:
  file.managed:
    - name: /etc/docker/daemon.json
    - source: salt://docker/files/daemon.json.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - pkg: docker-engine-packages

docker-service:
  service.running:
    - name: docker
    - enable: True
    - require:
      - pkg: docker-engine-packages
    - watch:
      - file: docker-daemon-config
