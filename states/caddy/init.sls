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

caddy-rdt-llm-auth-snippet:
  cmd.run:
    - name: |
        set -eu
        key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
        umask 027
        printf '@authorized header Authorization "Bearer %s"\n' "$key" > /etc/caddy/rdt-llm-auth.caddy
        chown root:caddy /etc/caddy/rdt-llm-auth.caddy
        chmod 0640 /etc/caddy/rdt-llm-auth.caddy
    - unless: test -s /etc/caddy/rdt-llm-auth.caddy
    - require:
      - pkg: caddy-package

caddy-rdt-llm-auth-snippet-permissions:
  file.managed:
    - name: /etc/caddy/rdt-llm-auth.caddy
    - user: root
    - group: caddy
    - mode: '0640'
    - replace: False
    - require:
      - cmd: caddy-rdt-llm-auth-snippet

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
      - file: caddy-rdt-llm-auth-snippet-permissions

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
      - file: caddy-rdt-llm-auth-snippet-permissions
    - require:
      - file: caddyfile
      - file: caddy-rdt-llm-auth-snippet-permissions

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
      - file: caddy-rdt-llm-auth-snippet-permissions
{% endif %}
