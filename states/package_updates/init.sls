{% set cfg = salt['pillar.get']('package_updates', {}) %}
{% set enabled = cfg.get('enabled', False) %}
{% set manager = cfg.get('manager', 'salt') %}
{% set os_family = grains.get('os_family', '') %}

{% if enabled and manager not in ['salt', 'native'] %}
package-updates-invalid-manager:
  test.fail_without_changes:
    - name: package_updates manager must be exactly salt or native.
{% endif %}

{% if enabled and manager == 'salt' %}
package-updates-system-uptodate:
  pkg.uptodate:
    - refresh: {{ cfg.get('refresh', True) }}
{% if os_family == 'Debian' %}
    - dist_upgrade: {{ cfg.get('debian_dist_upgrade', False) }}
{% endif %}
{% endif %}

{% if enabled and cfg.get('automatic_reboot', False) %}
package-updates-reboot-checker:
  file.managed:
    - name: /usr/local/sbin/redsalt-reboot-if-required
    - source: salt://package_updates/files/redsalt-reboot-if-required.py
    - user: root
    - group: root
    - mode: '0755'

package-updates-reboot-service:
  file.managed:
    - name: /etc/systemd/system/redsalt-reboot-if-required.service
    - contents: |
        [Unit]
        Description=Reboot after package updates when required
        [Service]
        Type=oneshot
        ExecStart=/usr/local/sbin/redsalt-reboot-if-required
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: package-updates-reboot-checker

package-updates-reboot-timer:
  file.managed:
    - name: /etc/systemd/system/redsalt-reboot-if-required.timer
    - contents: |
        [Unit]
        Description=Check for a required reboot after package maintenance
        [Timer]
        OnCalendar=*-*-* {{ cfg.get('reboot_time', '06:00') }}:00
        Persistent=false
        [Install]
        WantedBy=timers.target
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - file: package-updates-reboot-service

package-updates-reboot-systemd-reload:
  cmd.run:
    - name: systemctl daemon-reload
    - onchanges:
      - file: package-updates-reboot-service
      - file: package-updates-reboot-timer

package-updates-reboot-timer-enabled:
  service.running:
    - name: redsalt-reboot-if-required.timer
    - enable: True
    - require:
      - cmd: package-updates-reboot-systemd-reload
{% endif %}

{% if enabled and manager == 'native' and cfg.get('native_unattended', False) and os_family == 'Debian' %}
package-updates-unattended-package:
  pkg.installed:
    - name: unattended-upgrades

package-updates-unattended-periodic:
  file.managed:
    - name: /etc/apt/apt.conf.d/52redsalt-auto-upgrades
    - contents: |
        APT::Periodic::Update-Package-Lists "1";
        APT::Periodic::Unattended-Upgrade "1";
    - user: root
    - group: root
    - mode: '0644'
    - require:
      - pkg: package-updates-unattended-package

package-updates-unattended-policy:
  file.managed:
    - name: /etc/apt/apt.conf.d/52redsalt-unattended-upgrades
    - contents: |
{% if cfg.get('unattended_upgrade_origins', []) %}
        Unattended-Upgrade::Allowed-Origins {
{% for origin in cfg.get('unattended_upgrade_origins', []) %}
            "{{ origin }}";
{% endfor %}
        };
{% endif %}
        Unattended-Upgrade::Automatic-Reboot "false";
        Unattended-Upgrade::Automatic-Reboot-Time "06:00";
    - user: root
    - group: root
    - mode: '0644'

package-updates-apt-daily-timer:
  service.running:
    - name: apt-daily.timer
    - enable: True
    - require:
      - pkg: package-updates-unattended-package

package-updates-apt-daily-upgrade-timer:
  service.running:
    - name: apt-daily-upgrade.timer
    - enable: True
    - require:
      - pkg: package-updates-unattended-package
{% elif enabled and manager == 'native' and cfg.get('native_unattended', False) and os_family == 'RedHat' and grains.get('os', '') != 'Fedora' %}
package-updates-dnf-automatic-package:
  pkg.installed:
    - name: dnf-automatic

package-updates-dnf-automatic-policy:
  ini.options_present:
    - name: /etc/dnf/automatic.conf
    - sections:
        commands:
          upgrade_type: {{ cfg.get('dnf_upgrade_type', 'default') }}
          download_updates: "{{ 'yes' if cfg.get('download_updates', True) else 'no' }}"
          apply_updates: 'yes'
    - require:
      - pkg: package-updates-dnf-automatic-package

package-updates-dnf-automatic-install-timer:
  service.running:
    - name: dnf-automatic-install.timer
    - enable: True
    - require:
      - pkg: package-updates-dnf-automatic-package
      - ini: package-updates-dnf-automatic-policy
{% elif enabled and manager == 'native' and cfg.get('native_unattended', False) and grains.get('os', '') == 'Fedora' %}
package-updates-dnf5-automatic-package:
  pkg.installed:
    - name: dnf5-plugin-automatic

package-updates-dnf5-automatic-policy:
  ini.options_present:
    - name: /etc/dnf/automatic.conf
    - sections:
        commands:
          upgrade_type: {{ cfg.get('dnf_upgrade_type', 'default') }}
          download_updates: "{{ 'yes' if cfg.get('download_updates', True) else 'no' }}"
          apply_updates: 'yes'
    - require:
      - pkg: package-updates-dnf5-automatic-package

package-updates-dnf5-automatic-timer:
  service.running:
    - name: dnf5-automatic.timer
    - enable: True
    - require:
      - pkg: package-updates-dnf5-automatic-package
      - ini: package-updates-dnf5-automatic-policy
{% elif enabled and manager == 'native' and cfg.get('native_unattended', False) and os_family == 'Suse' %}
package-updates-native-suse-unsupported:
  test.fail_without_changes:
    - name: Native SUSE automatic updates are not enabled by this state because transactional-update may reboot outside the approved maintenance window. Use Salt manager.
{% elif enabled and manager == 'native' and cfg.get('native_unattended', False) %}
package-updates-native-platform-unsupported:
  test.fail_without_changes:
    - name: Native unattended updates are unsupported for this OS family. Use manager salt or add a reviewed distro-specific policy.
{% endif %}
