{% set cfg = salt['pillar.get']('restic_backup', {}) %}
{% set enabled = cfg.get('enabled', False) %}
{% set env_file = cfg.get('env_file', '/etc/restic/backup.env') %}
{% set password_file = cfg.get('password_file', '/etc/restic/password') %}
{% set includes_file = cfg.get('includes_file', '/etc/restic/includes') %}
{% set excludes_file = cfg.get('excludes_file', '/etc/restic/excludes') %}
{% set script_path = cfg.get('script_path', '/usr/local/sbin/rdt-restic-backup') %}
{% set timer_name = cfg.get('timer_name', 'rdt-restic-backup') %}
{% set service_unit = '/etc/systemd/system/' ~ timer_name ~ '.service' %}
{% set timer_unit = '/etc/systemd/system/' ~ timer_name ~ '.timer' %}

restic-backup-packages:
  pkg.installed:
    - pkgs:
      - {{ cfg.get('package', 'restic') }}
      - util-linux

restic-backup-config-dir:
  file.directory:
    - name: /etc/restic
    - user: root
    - group: root
    - mode: '0700'
    - makedirs: True

restic-backup-log-dir:
  file.directory:
    - name: {{ cfg.get('log_dir', '/var/log/restic') }}
    - user: root
    - group: root
    - mode: '0700'
    - makedirs: True

restic-backup-env-file-placeholder:
  file.managed:
    - name: {{ env_file }}
    - user: root
    - group: root
    - mode: '0600'
    - replace: False
    - contents: |
        # Provision manually; do not commit secrets to Salt pillar.
        # Required variables:
        # export B2_ACCOUNT_ID='...'
        # export B2_ACCOUNT_KEY='...'
        # export RESTIC_REPOSITORY='b2:<bucket>:salt-restic/<minion-id>'
    - require:
      - file: restic-backup-config-dir

restic-backup-password-file-placeholder:
  file.managed:
    - name: {{ password_file }}
    - user: root
    - group: root
    - mode: '0600'
    - replace: False
    - contents: |
        REPLACE_WITH_UNIQUE_RESTIC_PASSWORD_FOR_THIS_HOST
    - require:
      - file: restic-backup-config-dir

restic-backup-includes-file:
  file.managed:
    - name: {{ includes_file }}
    - user: root
    - group: root
    - mode: '0644'
    - contents: |
{% for item in cfg.get('includes', []) %}
        {{ item }}
{% endfor %}
    - require:
      - file: restic-backup-config-dir

restic-backup-excludes-file:
  file.managed:
    - name: {{ excludes_file }}
    - user: root
    - group: root
    - mode: '0644'
    - contents: |
{% for item in cfg.get('excludes', []) %}
        {{ item }}
{% endfor %}
    - require:
      - file: restic-backup-config-dir

restic-backup-script:
  file.managed:
    - name: {{ script_path }}
    - source: salt://restic_backup/files/rdt-restic-backup.sh.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0755'
    - context:
        env_file: {{ env_file | json }}
        password_file: {{ password_file | json }}
        includes_file: {{ includes_file | json }}
        excludes_file: {{ excludes_file | json }}
        log_file: {{ cfg.get('log_file', '/var/log/restic/backup.log') | json }}
        lock_file: {{ cfg.get('lock_file', '/run/lock/rdt-restic-backup.lock') | json }}
        retention: {{ cfg.get('retention', {}) | json }}
        check_read_data_subset: {{ cfg.get('check_read_data_subset', '1/20') | json }}
        max_snapshot_age_hours: {{ cfg.get('max_snapshot_age_hours', 30) | json }}
        tags: {{ cfg.get('tags', []) | json }}
    - require:
      - pkg: restic-backup-packages
      - file: restic-backup-config-dir
      - file: restic-backup-log-dir

restic-backup-service-unit:
  file.managed:
    - name: {{ service_unit }}
    - source: salt://restic_backup/files/restic-backup.service.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - context:
        script_path: {{ script_path | json }}
    - require:
      - file: restic-backup-script

restic-backup-timer-unit:
  file.managed:
    - name: {{ timer_unit }}
    - source: salt://restic_backup/files/restic-backup.timer.j2
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'
    - context:
        schedule: {{ cfg.get('schedule', '*-*-* 03:00:00') | json }}
        randomized_delay: {{ cfg.get('randomized_delay', '2h') | json }}
        accuracy: {{ cfg.get('accuracy', '15m') | json }}
    - require:
      - file: restic-backup-service-unit

restic-backup-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: restic-backup-service-unit
      - file: restic-backup-timer-unit

{% if enabled %}
restic-backup-timer-enabled:
  service.running:
    - name: {{ timer_name }}.timer
    - enable: True
    - require:
      - cmd: restic-backup-systemd-reload
      - file: restic-backup-env-file-placeholder
      - file: restic-backup-password-file-placeholder
{% else %}
restic-backup-timer-disabled:
  service.dead:
    - name: {{ timer_name }}.timer
    - enable: False
    - require:
      - cmd: restic-backup-systemd-reload
{% endif %}
