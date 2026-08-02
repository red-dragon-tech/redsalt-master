restic_backup:
  enabled: false
  package: restic
  env_file: /etc/restic/backup.env
  password_file: /etc/restic/password
  includes_file: /etc/restic/includes
  excludes_file: /etc/restic/excludes
  script_path: /usr/local/sbin/rdt-restic-backup
  log_dir: /var/log/restic
  log_file: /var/log/restic/backup.log
  lock_file: /run/lock/rdt-restic-backup.lock
  timer_name: rdt-restic-backup
  repository_prefix: salt-restic
  tags: []
  schedule: '*-*-* 03:00:00'
  randomized_delay: 2h
  accuracy: 15m
  retention:
    daily: 14
    weekly: 8
    monthly: 12
  check_read_data_subset: 1/20
  max_snapshot_age_hours: 30
  includes:
    - /etc
    - /root
    - /home
    - /opt
    - /usr/local
    - /var/lib
    - /var/spool/cron
  excludes:
    - /proc
    - /sys
    - /dev
    - /run
    - /tmp
    - /var/tmp
    - /var/cache
    - /var/log/*.log
    - /var/lib/docker/overlay2
    - /var/lib/containerd
    - /var/lib/kubelet
    - lost+found
    - '*.cache'
