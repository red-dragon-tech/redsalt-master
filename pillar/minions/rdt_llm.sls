roles:
  base: true
  docker: true
  nvidia: true
  llm_vllm: true
  salt_master: false
  restic_backup: true

restic_backup:
  enabled: false
  tags:
    - rdt-llm
    - llm-vllm
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
    - /opt/models
    - /var/cache/huggingface
    - lost+found
    - '*.cache'

models:
  path: /opt/models
  owner: root
  group: root
  mode: '0755'

nvidia:
  driver:
    install: true
    package: nvidia-driver-595-open
  container_toolkit:
    package: nvidia-container-toolkit

vllm:
  image: vllm/vllm-openai:latest
  service_name: vllm-openai
  port: 8000
  bind_host: 127.0.0.1
  host: 0.0.0.0
  model: Qwen/Qwen3.5-Coder-32B-Instruct-FP8
  served_model_name: qwen3.5-coder-32b-instruct-fp8
  gpu_count: all
  gpu_memory_utilization: 0.92
  max_model_len: 64000
  tensor_parallel_size: 1
  enable_prefix_caching: true
  trust_remote_code: false
  env_vars:
    VLLM_ALLOW_LONG_MAX_MODEL_LEN: '1'
  extra_args:
    - --kv-cache-dtype
    - fp8
    - --hf-overrides
    - '{"rope_parameters":{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768}}'
    - --enable-auto-tool-choice
    - --tool-parser-plugin
    - /opt/redsalt/vllm/qwen25_coder_tool_parser.py
    - --tool-call-parser
    - qwen
    - --chat-template
    - /opt/redsalt/vllm/qwen25_coder_tool_chat_template.jinja
  compose_dir: /opt/redsalt/vllm
  env_file: /etc/redsalt/vllm.env
  hf_cache: /var/cache/huggingface
  triton_cache: /var/cache/triton

firewall:
  web:
    public_tcp_ports:
      - 80
      - 443

caddy:
  enabled: true
  service_name: caddy
  acme_email: jason.lang@rdt.dev
  servers:
    - host: llm.ai.rdt.dev
      upstream: 127.0.0.1:8000
      encode: true
      require_bearer_token: true
    - host: ai.redspectre.rdt.dev
      upstream: 127.0.0.1:8000
      encode: true
      require_bearer_token: true
