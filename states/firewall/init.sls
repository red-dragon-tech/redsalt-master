{% set firewall = salt['pillar.get']('firewall', {}) %}
{% set dynamic = salt['pillar.get']('firewall_dynamic', {}) %}

include:
  - firewall.refresh

ufw-package:
  pkg.installed:
    - name: ufw

redsalt-ufw-apply-script:
  file.managed:
    - name: /usr/local/sbin/redsalt-apply-ufw
    - source: salt://firewall/files/redsalt-apply-ufw.py.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0755'
    - context:
        firewall: {{ firewall | json }}
        firewall_dynamic: {{ dynamic | json }}
    - require:
      - pkg: ufw-package

redsalt-ufw-apply:
  cmd.run:
    - name: /usr/local/sbin/redsalt-apply-ufw
    - stateful: True
    - require:
      - file: redsalt-ufw-apply-script
