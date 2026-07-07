{% set common = salt['pillar.get']('common', {}) %}
{% set packages = common.get('packages', []) %}
{% set managed_dirs = common.get('managed_directories', []) %}

common-base-packages:
  pkg.installed:
    - pkgs: {{ packages | json }}

common-timezone:
  timezone.system:
    - name: {{ common.get('timezone', 'UTC') }}

{% for path in managed_dirs %}
common-directory-{{ loop.index }}:
  file.directory:
    - name: {{ path }}
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True
{% endfor %}
