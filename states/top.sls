base:
  'roles:base:true':
    - match: pillar
    - roles.base

  'roles:docker:true':
    - match: pillar
    - roles.docker

  'roles:nvidia:true':
    - match: pillar
    - roles.nvidia

  'roles:llm_vllm:true':
    - match: pillar
    - roles.llm_vllm
