{% set models = salt['pillar.get']('models', {}) %}
{% set model_path = models.get('path', '/opt/models') %}
{% set vllm = salt['pillar.get']('vllm', {}) %}
{% set compose_dir = vllm.get('compose_dir', '/opt/redsalt/vllm') %}
{% set service_name = vllm.get('service_name', 'vllm-openai') %}
{% set env_file = vllm.get('env_file', '/etc/redsalt/vllm.env') %}
{% set hf_cache = vllm.get('hf_cache', '/var/cache/huggingface') %}
{% set triton_cache = vllm.get('triton_cache', '/var/cache/triton') %}

include:
  - docker
  - models

vllm-compose-directory:
  file.directory:
    - name: {{ compose_dir }}
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

vllm-config-directory:
  file.directory:
    - name: {{ env_file.rsplit('/', 1)[0] }}
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

vllm-hf-cache-directory:
  file.directory:
    - name: {{ hf_cache }}
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

vllm-triton-cache-directory:
  file.directory:
    - name: {{ triton_cache }}
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

vllm-env-file:
  file.managed:
    - name: {{ env_file }}
    - source: salt://vllm/files/vllm.env.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - context:
        vllm: {{ vllm | json }}

vllm-qwen25-coder-tool-parser:
  file.managed:
    - name: {{ compose_dir }}/qwen25_coder_tool_parser.py
    - source: salt://vllm/files/qwen25_coder_tool_parser.py
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: vllm-compose-directory

vllm-qwen25-coder-tool-chat-template:
  file.managed:
    - name: {{ compose_dir }}/qwen25_coder_tool_chat_template.jinja
    - source: salt://vllm/files/qwen25_coder_tool_chat_template.jinja
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: vllm-compose-directory

vllm-triton-cache-cleanup-script:
  file.managed:
    - name: {{ compose_dir }}/clear-corrupt-triton-cache.sh
    - source: salt://vllm/files/clear-corrupt-triton-cache.sh.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0755'
    - context:
        triton_cache: {{ triton_cache | json }}
    - require:
      - file: vllm-compose-directory
      - file: vllm-triton-cache-directory

vllm-compose-file:
  file.managed:
    - name: {{ compose_dir }}/docker-compose.yml
    - source: salt://vllm/files/docker-compose.yml.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - context:
        vllm: {{ vllm | json }}
        model_path: {{ model_path | json }}
        hf_cache: {{ hf_cache | json }}
        triton_cache: {{ triton_cache | json }}
    - require:
      - file: vllm-compose-directory
      - file: vllm-env-file
      - file: model-storage-directory
      - file: vllm-hf-cache-directory
      - file: vllm-triton-cache-directory
      - file: vllm-qwen25-coder-tool-parser
      - file: vllm-qwen25-coder-tool-chat-template

vllm-systemd-unit:
  file.managed:
    - name: /etc/systemd/system/{{ service_name }}.service
    - source: salt://vllm/files/vllm-openai.service.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - context:
        service_name: {{ service_name | json }}
        compose_dir: {{ compose_dir | json }}
        triton_cache_cleanup_script: {{ (compose_dir ~ '/clear-corrupt-triton-cache.sh') | json }}
    - require:
      - file: vllm-compose-file

vllm-systemd-daemon-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: vllm-systemd-unit

vllm-service:
  service.running:
    - name: {{ service_name }}
    - enable: True
    - require:
      - file: vllm-systemd-unit
      - pkg: docker-engine-packages
    - watch:
      - file: vllm-compose-file
      - file: vllm-env-file
      - file: vllm-systemd-unit
      - file: vllm-triton-cache-cleanup-script
      - file: vllm-qwen25-coder-tool-parser
      - file: vllm-qwen25-coder-tool-chat-template
