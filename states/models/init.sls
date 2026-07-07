{% set models = salt['pillar.get']('models', {}) %}
{% set path = models.get('path', '/opt/models') %}

model-storage-directory:
  file.directory:
    - name: {{ path }}
    - user: {{ models.get('owner', 'root') }}
    - group: {{ models.get('group', 'root') }}
    - mode: '{{ models.get('mode', '0755') }}'
    - makedirs: True
