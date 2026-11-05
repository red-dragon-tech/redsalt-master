{% set cfg = salt['pillar.get']('kali_workstation', {}) %}
{% set shared_root = cfg.get('shared_root', '/opt/shared') %}
{% set shared_repos = cfg.get('shared_repos', []) %}
{% set shell_helpers = cfg.get('shell_helpers', []) %}
{% set promptfoo = cfg.get('promptfoo_mcp_redteam', {}) %}
{% set repos_by_path = {} %}
{% for repo in shared_repos %}
{% if repo.get('path') %}
{% set _ = repos_by_path.update({repo.get('path'): repo}) %}
{% endif %}
{% endfor %}

kali-shared-root:
  file.directory:
    - name: {{ shared_root }}
    - user: root
    - group: users
    - mode: '2775'
    - makedirs: True

{% for repo in shared_repos %}
{% set repo_index = loop.index %}
{% set repo_path = repo.get('path') %}
{% set repo_owner = repo.get('owner', 'root') %}
{% set repo_group = repo.get('group', 'users') %}
{% set safe_users = repo.get('safe_directory_users', []) %}
{% if repo_path %}
kali-shared-repo-dir-{{ repo_index }}:
  file.directory:
    - name: {{ repo_path }}
    - user: {{ repo_owner }}
    - group: {{ repo_group }}
    - mode: {{ repo.get('mode', '2775') | json }}
    - makedirs: True
    - require:
      - file: kali-shared-root

kali-shared-repo-git-shared-{{ repo_index }}:
  cmd.run:
    - name: git -C {{ repo_path | json }} config core.sharedRepository group
    - runas: {{ repo_owner }}
    - onlyif: test -d {{ repo_path }}/.git
    - require:
      - file: kali-shared-repo-dir-{{ repo_index }}

{% for user in safe_users %}
kali-git-safe-directory-{{ repo_index }}-{{ user }}:
  cmd.run:
    - name: git config --global --add safe.directory {{ repo_path | json }}
    - runas: {{ user }}
    - unless: git config --global --get-all safe.directory | grep -Fx {{ repo_path | json }}
    - onlyif: test -d {{ repo_path }}/.git
    - require:
      - file: kali-shared-repo-dir-{{ repo_index }}
{% endfor %}
{% endif %}
{% endfor %}

{% if promptfoo.get('enabled', False) %}
{% set promptfoo_repo = promptfoo.get('repo_path', '/opt/shared/kali-linux') %}
{% set promptfoo_project = promptfoo.get('project_path', '/opt/promptfoo-mcp-redteam') %}
{% set project_repo_config = repos_by_path.get(promptfoo_project, {}) %}
{% set promptfoo_owner = project_repo_config.get('owner', promptfoo.get('owner', 'darthai')) %}
{% set promptfoo_group = project_repo_config.get('group', promptfoo.get('group', 'users')) %}
{% set promptfoo_mode = project_repo_config.get('mode', '0750') %}
{% set promptfoo_helper = promptfoo_repo ~ '/scripts/setup/promptfoo_mcp_redteam.py' %}
{% set promptfoo_target = promptfoo.get('target_url', 'https://REPLACE-WITH-AUTHORIZED-MCP-ENDPOINT.example/mcp') %}
{% set repo_config = repos_by_path.get(promptfoo_repo, {}) %}
{% set promptfoo_repo_owner = repo_config.get('owner', promptfoo.get('repo_owner', 'darthai')) %}
kali-promptfoo-redteam-node-runtime:
  pkg.installed:
    - pkgs:
      - nodejs
      - npm

kali-promptfoo-redteam-project-directory:
  file.directory:
    - name: {{ promptfoo_project }}
    - user: {{ promptfoo_owner | json }}
    - group: {{ promptfoo_group | json }}
    - mode: {{ promptfoo_mode | json }}
    - makedirs: True
    - require:
      - pkg: kali-promptfoo-redteam-node-runtime

kali-promptfoo-redteam-node-version:
  cmd.run:
    - name: node --version && npm --version && npx --version && node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(Number(!(a>22||a===22&&b>=22)))' && echo 'changed=no comment="Node.js npm and npx satisfy Promptfoo minimum"'
    - stateful: True
    - require:
      - pkg: kali-promptfoo-redteam-node-runtime

kali-promptfoo-redteam-project-init:
  cmd.run:
    - name: python3 {{ promptfoo_helper | json }} init --project-dir {{ promptfoo_project | json }} --target-url {{ promptfoo_target | json }}
    - runas: {{ promptfoo_owner }}
    - unless: test -f {{ promptfoo_project | json }}/promptfooconfig.yaml && test -f {{ promptfoo_project | json }}/ROE.md && test -f {{ promptfoo_project | json }}/mcp-client-config.json && test -x {{ promptfoo_project | json }}/promptfoo-mcp-stdio.sh
    - require:
      - cmd: kali-promptfoo-redteam-node-version
      - file: kali-promptfoo-redteam-project-directory
{% if promptfoo_project in repos_by_path %}
      - file: kali-shared-repo-dir-{{ shared_repos.index(repos_by_path.get(promptfoo_project)) + 1 }}
{% elif promptfoo_repo in repos_by_path %}
      - file: kali-shared-repo-dir-{{ shared_repos.index(repo_config) + 1 }}
{% endif %}

kali-promptfoo-redteam-prerequisite-check:
  cmd.run:
    - name: python3 {{ promptfoo_helper | json }} check --project-dir {{ promptfoo_project | json }} && echo 'changed=no comment="Promptfoo prerequisites verified"'
    - stateful: True
    - runas: {{ promptfoo_owner }}
    - require:
      - cmd: kali-promptfoo-redteam-project-init
{% endif %}

{% for helper in shell_helpers %}
{% set user = helper.get('user') %}
{% set home = helper.get('home', '/home/' ~ user) %}
{% if user %}
kali-home-readme-{{ user }}:
  file.managed:
    - name: {{ home }}/README-kali-linux-repo.txt
    - user: {{ user }}
    - group: {{ user }}
    - mode: '0644'
    - contents: |
        RDT Kali shared workspace

        Shared root: {{ shared_root }}
        Primary repo: /opt/shared/kali-linux

        Shell helpers managed by Salt:
          kali-repo   -> cd /opt/shared/kali-linux
          cdkali      -> cd /opt/shared/kali-linux
          kali-status -> git status for /opt/shared/kali-linux
          kali-pull   -> fast-forward pull for /opt/shared/kali-linux
          kali-files  -> list top-level repo files

{% for shell_file in ['.bashrc', '.zshrc'] %}
kali-shell-helpers-{{ user }}-{{ shell_file }}:
  file.blockreplace:
    - name: {{ home }}/{{ shell_file }}
    - marker_start: '# BEGIN managed by redsalt kali workstation helpers'
    - marker_end: '# END managed by redsalt kali workstation helpers'
    - append_if_not_found: True
    - content: |
        alias kali-repo='cd /opt/shared/kali-linux'
        alias cdkali='cd /opt/shared/kali-linux'
        alias kali-status='git -C /opt/shared/kali-linux status --short --branch'
        alias kali-pull='git -C /opt/shared/kali-linux pull --ff-only'
        alias kali-files='find /opt/shared/kali-linux -maxdepth 2 -type f | sort | sed "s#^#/##" | head -200'

kali-shell-helpers-permissions-{{ user }}-{{ shell_file }}:
  file.managed:
    - name: {{ home }}/{{ shell_file }}
    - user: {{ user }}
    - group: {{ user }}
    - mode: '0644'
    - replace: False
    - require:
      - file: kali-shell-helpers-{{ user }}-{{ shell_file }}
{% endfor %}
{% endif %}
{% endfor %}
