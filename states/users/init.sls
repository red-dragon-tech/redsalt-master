{% set managed_users = salt['pillar.get']('managed_users', []) %}

{% for account in managed_users %}
{% set username = account.get('name') %}
{% set home = account.get('home', '/home/' ~ username) %}
{% set shell = account.get('shell', '/bin/bash') %}
{% set groups = account.get('groups', []) %}
{% set ssh_keys = account.get('ssh_authorized_keys', []) %}
managed-user-{{ username }}:
  user.present:
    - name: {{ username }}
    - fullname: {{ account.get('fullname', username) | json }}
    - home: {{ home }}
    - shell: {{ shell }}
    - createhome: True
    - usergroup: True
{% if groups %}
    - groups: {{ groups | json }}
{% endif %}

managed-user-ssh-dir-{{ username }}:
  file.directory:
    - name: {{ home }}/.ssh
    - user: {{ username }}
    - group: {{ username }}
    - mode: '0700'
    - makedirs: True
    - require:
      - user: managed-user-{{ username }}

{% for key in ssh_keys %}
{% set key_parts = key.split() %}
managed-user-ssh-key-{{ username }}-{{ loop.index }}:
  ssh_auth.present:
    - user: {{ username }}
    - name: {{ key_parts[1] | json }}
    - enc: {{ key_parts[0] | json }}
{% if key_parts | length > 2 %}
    - comment: {{ key_parts[2:] | join(' ') | json }}
{% endif %}
    - require:
      - file: managed-user-ssh-dir-{{ username }}

{% endfor %}
{% endfor %}
