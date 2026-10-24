redsalt-package-updates-script:
  file.managed:
    - name: /usr/local/sbin/redsalt-package-updates
    - source: salt://redsalt_package_updates/files/redsalt-package-updates.py
    - user: root
    - group: root
    - mode: '0755'

redsalt-package-updates-state-dir:
  file.directory:
    - name: /var/lib/redsalt/package-updates
    - user: root
    - group: root
    - mode: '0755'
    - makedirs: True

redsalt-package-updates-log:
  file.managed:
    - name: /var/log/redsalt-package-updates.log
    - user: root
    - group: root
    - mode: '0644'
    - replace: False

redsalt-package-updates-service:
  file.managed:
    - name: /etc/systemd/system/redsalt-package-updates.service
    - contents: |
        [Unit]
        Description=Run explicitly enrolled RedSalt package update checks
        Wants=network-online.target
        After=network-online.target salt-master.service salt-minion.service

        [Service]
        Type=oneshot
        User=root
        Group=root
        WorkingDirectory=/
        Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
        NoNewPrivileges=true
        PrivateTmp=true
        PrivateDevices=true
        ProtectKernelTunables=true
        ProtectKernelModules=true
        ProtectControlGroups=true
        ProtectSystem=full
        ProtectHome=read-only
        ReadWritePaths=/var/lib/redsalt/package-updates /var/log/redsalt-package-updates.log /run
        ExecStart=/usr/local/sbin/redsalt-package-updates
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-package-updates-script
      - file: redsalt-package-updates-state-dir

redsalt-package-updates-timer:
  file.managed:
    - name: /etc/systemd/system/redsalt-package-updates.timer
    - contents: |
        [Unit]
        Description=Check RedSalt package update policies daily

        [Timer]
        OnCalendar=hourly
        RandomizedDelaySec=2min
        Persistent=false
        AccuracySec=5min

        [Install]
        WantedBy=timers.target
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: redsalt-package-updates-service

redsalt-package-updates-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: redsalt-package-updates-service
      - file: redsalt-package-updates-timer

redsalt-package-updates-timer-enabled:
  service.running:
    - name: redsalt-package-updates.timer
    - enable: True
    - require:
      - cmd: redsalt-package-updates-systemd-reload
