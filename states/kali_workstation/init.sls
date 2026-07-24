{% set cfg = salt['pillar.get']('kali_workstation', {}) %}
{% set shared_root = cfg.get('shared_root', '/opt/shared') %}
{% set shared_repos = cfg.get('shared_repos', []) %}
{% set shell_helpers = cfg.get('shell_helpers', []) %}

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
    - onlyif: test -d {{ repo_path | json }}/.git
    - require:
      - file: kali-shared-repo-dir-{{ repo_index }}

{% for user in safe_users %}
kali-git-safe-directory-{{ repo_index }}-{{ user }}:
  cmd.run:
    - name: git config --global --add safe.directory {{ repo_path | json }}
    - runas: {{ user }}
    - unless: git config --global --get-all safe.directory | grep -Fx {{ repo_path | json }}
    - require:
      - file: kali-shared-repo-dir-{{ repo_index }}
{% endfor %}
{% endif %}
{% endfor %}

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
