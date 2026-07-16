roles:
  base: true
  docker: true
  nvidia: true
  llm_vllm: true
  salt_master: false

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
  host: 0.0.0.0
  model: /models/model
  served_model_name: local-model
  gpu_count: all
  gpu_memory_utilization: 0.90
  max_model_len: 32768
  tensor_parallel_size: 1
  enable_prefix_caching: true
  trust_remote_code: false
  extra_args: []
  compose_dir: /opt/redsalt/vllm
  env_file: /etc/redsalt/vllm.env
  hf_cache: /var/cache/huggingface
