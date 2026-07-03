{% set nvidia = salt['pillar.get']('nvidia', {}) %}
{% set driver = nvidia.get('driver', {}) %}
{% set toolkit = nvidia.get('container_toolkit', {}) %}
{% set arch = grains.get('osarch', 'amd64') %}
{% set repo_arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(arch, arch) %}

include:
  - docker

nvidia-keyring-dir:
  file.directory:
    - name: /etc/apt/keyrings
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

# Public vendor key; replace skip_verify with a pinned source_hash in regulated environments.
nvidia-container-toolkit-key:
  file.managed:
    - name: /etc/apt/keyrings/nvidia-container-toolkit.asc
    - source: https://nvidia.github.io/libnvidia-container/gpgkey
    - skip_verify: True
    - mode: '0644'
    - require:
      - file: nvidia-keyring-dir

nvidia-container-toolkit-repo:
  pkgrepo.managed:
    - humanname: NVIDIA libnvidia-container stable
    - name: deb [signed-by=/etc/apt/keyrings/nvidia-container-toolkit.asc] https://nvidia.github.io/libnvidia-container/stable/deb/{{ repo_arch }} /
    - file: /etc/apt/sources.list.d/nvidia-container-toolkit.list
    - clean_file: True
    - require:
      - file: nvidia-container-toolkit-key

{% if driver.get('install', False) %}
nvidia-driver-package:
  pkg.installed:
    - name: {{ driver.get('package', 'nvidia-driver-550') }}
    - refresh: True
{% endif %}

nvidia-container-toolkit-package:
  pkg.installed:
    - name: {{ toolkit.get('package', 'nvidia-container-toolkit') }}
    - refresh: True
    - require:
      - pkgrepo: nvidia-container-toolkit-repo

nvidia-docker-runtime-configured:
  cmd.run:
    - name: nvidia-ctk runtime configure --runtime=docker
    - onchanges:
      - pkg: nvidia-container-toolkit-package
    - require:
      - pkg: nvidia-container-toolkit-package

nvidia-docker-service-running:
  service.running:
    - name: docker
    - enable: True
    - watch:
      - cmd: nvidia-docker-runtime-configured
