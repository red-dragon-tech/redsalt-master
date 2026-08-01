redsalt-highstate-convergence-script:
  file.managed:
    - name: /usr/local/sbin/redsalt-highstate-convergence
    - source: salt://redsalt_highstate_convergence/files/redsalt-highstate-convergence.py
    - user: root
    - group: root
    - mode: '0755'

redsalt-highstate-convergence-state-dir:
  file.directory:
    - name: /var/lib/redsalt/highstate-status
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

redsalt-highstate-convergence-log-file:
  file.managed:
    - name: /var/log/redsalt-highstate-convergence.log
    - user: root
    - group: root
    - mode: '0644'
    - replace: False

redsalt-highstate-convergence-service:
  file.managed:
    - name: /etc/systemd/system/redsalt-highstate-convergence.service
    - contents: |
        [Unit]
        Description=Run recurring RedSalt highstate convergence
        Wants=network-online.target
        After=network-online.target salt-master.service salt-minion.service
        Conflicts=redsalt-master-sync.service

        [Service]
        Type=oneshot
        ExecStart=/usr/local/sbin/redsalt-highstate-convergence
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-highstate-convergence-script
      - file: redsalt-highstate-convergence-state-dir

redsalt-highstate-convergence-timer:
  file.managed:
    - name: /etc/systemd/system/redsalt-highstate-convergence.timer
    - contents: |
        [Unit]
        Description=Run daily RedSalt highstate convergence

        [Timer]
        OnCalendar=*-*-* 04:20:00
        RandomizedDelaySec=45min
        Persistent=true
        AccuracySec=5min

        [Install]
        WantedBy=timers.target
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-highstate-convergence-service

redsalt-highstate-convergence-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: redsalt-highstate-convergence-service
      - file: redsalt-highstate-convergence-timer

redsalt-highstate-convergence-timer-enabled:
  service.running:
    - name: redsalt-highstate-convergence.timer
    - enable: True
    - require:
      - cmd: redsalt-highstate-convergence-systemd-reload
