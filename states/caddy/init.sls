{% set caddy = salt['pillar.get']('caddy', {}) %}
{% set enabled = caddy.get('enabled', False) %}
{% set service_name = caddy.get('service_name', 'caddy') %}

{% if enabled %}
caddy-package:
  pkg.installed:
    - name: caddy

caddy-config-directory:
  file.directory:
    - name: /etc/caddy
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True
    - require:
      - pkg: caddy-package

caddy-systemd-dropin-directory:
  file.directory:
    - name: /etc/systemd/system/{{ service_name }}.service.d
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True
    - require:
      - pkg: caddy-package

caddy-old-redsalt-env-dropin-absent:
  file.absent:
    - name: /etc/systemd/system/{{ service_name }}.service.d/redsalt-env.conf

caddy-old-rdt-llm-api-key-env-absent:
  file.absent:
    - name: /etc/caddy/rdt-llm.env

caddy-rdt-llm-auth-snippet-absent:
  file.absent:
    - name: /etc/caddy/rdt-llm-auth.caddy

caddyfile:
  file.managed:
    - name: /etc/caddy/Caddyfile
    - source: salt://caddy/files/Caddyfile.j2
    - template: jinja
    - user: root
    - group: caddy
    - mode: '0640'
    - context:
        caddy: {{ caddy | json }}
    - require:
      - file: caddy-config-directory

caddy-systemd-daemon-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: caddy-old-redsalt-env-dropin-absent

caddy-config-validate:
  cmd.run:
    - name: caddy validate --config /etc/caddy/Caddyfile
    - onchanges:
      - file: caddyfile
      - file: caddy-rdt-llm-auth-snippet-absent
    - require:
      - file: caddyfile
      - file: caddy-rdt-llm-auth-snippet-absent

caddy-service:
  service.running:
    - name: {{ service_name }}
    - enable: True
    - require:
      - pkg: caddy-package
      - file: caddyfile
      - cmd: caddy-systemd-daemon-reload
    - watch:
      - file: caddyfile
      - file: caddy-old-redsalt-env-dropin-absent
      - file: caddy-old-rdt-llm-api-key-env-absent
      - file: caddy-rdt-llm-auth-snippet-absent
{% endif %}
