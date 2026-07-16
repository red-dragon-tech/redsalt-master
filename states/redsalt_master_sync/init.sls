redsalt-master-sync-script:
  file.managed:
    - name: /usr/local/sbin/redsalt-sync-prd
    - source: salt://redsalt_master_sync/files/redsalt-sync-prd.sh
    - user: root
    - group: root
    - mode: '0755'

redsalt-master-sync-service:
  file.managed:
    - name: /etc/systemd/system/redsalt-master-sync.service
    - contents: |
        [Unit]
        Description=Sync redsalt-master prd branch and apply Salt highstate
        Wants=network-online.target
        After=network-online.target salt-master.service

        [Service]
        Type=oneshot
        ExecStart=/usr/local/sbin/redsalt-sync-prd
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-master-sync-script

redsalt-master-sync-timer:
  file.managed:
    - name: /etc/systemd/system/redsalt-master-sync.timer
    - contents: |
        [Unit]
        Description=Run redsalt-master prd sync frequently

        [Timer]
        OnBootSec=30s
        OnUnitActiveSec=1min
        AccuracySec=10s
        Persistent=true

        [Install]
        WantedBy=timers.target
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-master-sync-service

redsalt-master-sync-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: redsalt-master-sync-service
      - file: redsalt-master-sync-timer

redsalt-master-sync-timer-enabled:
  service.running:
    - name: redsalt-master-sync.timer
    - enable: True
    - require:
      - cmd: redsalt-master-sync-systemd-reload
