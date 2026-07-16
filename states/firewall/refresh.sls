{% set fw = salt['pillar.get']('firewall:dynamic_update', {}) %}
{% set master_minion_id = fw.get('master_minion_id', 'mgmt.rdt.dev') %}
{% set enabled = fw.get('enabled', False) and grains.get('id') == master_minion_id %}

{% if enabled %}
redsalt-firewall-refresh-script:
  file.managed:
    - name: /usr/local/sbin/redsalt-refresh-darth-firewall-source
    - source: salt://firewall/files/redsalt-refresh-darth-firewall-source.py.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0755'
    - context:
        update_config: {{ fw | json }}

redsalt-firewall-refresh-service:
  file.managed:
    - name: /etc/systemd/system/redsalt-firewall-refresh.service
    - contents: |
        [Unit]
        Description=Refresh Darth SSH source pillar and re-apply redsalt firewall
        Wants=network-online.target
        After=network-online.target salt-master.service

        [Service]
        Type=oneshot
        ExecStart=/usr/local/sbin/redsalt-refresh-darth-firewall-source
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-firewall-refresh-script

redsalt-firewall-refresh-timer:
  file.managed:
    - name: /etc/systemd/system/redsalt-firewall-refresh.timer
    - contents: |
        [Unit]
        Description=Run redsalt firewall refresh periodically

        [Timer]
        OnBootSec=2min
        OnUnitActiveSec={{ fw.get('interval', '5min') }}
        AccuracySec=30s
        Persistent=true

        [Install]
        WantedBy=timers.target
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-firewall-refresh-service

redsalt-firewall-refresh-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: redsalt-firewall-refresh-service
      - file: redsalt-firewall-refresh-timer

redsalt-firewall-refresh-timer-enabled:
  service.running:
    - name: redsalt-firewall-refresh.timer
    - enable: True
    - require:
      - cmd: redsalt-firewall-refresh-systemd-reload
{% endif %}
