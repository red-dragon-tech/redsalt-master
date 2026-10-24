{% set cfg = salt['pillar.get']('package_updates', {}) %}
{% set enabled = cfg.get('enabled', False) %}
{% set scheduled = cfg.get('scheduled', False) %}
{% set manager = cfg.get('manager', '') %}
{% set os_family = grains.get('os_family', '') %}
{% set scheduled_apply_authorized = salt['pillar.get']('scheduled_apply_authorized', False) %}
{% set test_mode = opts.get('test', False) %}

{% set approved_hash = cfg.get('approved_preview_sha256', '') %}
{% set approval_valid = approved_hash is string and approved_hash|length == 64 and approved_hash|lower == approved_hash and approved_hash|replace('0', '')|replace('1', '')|replace('2', '')|replace('3', '')|replace('4', '')|replace('5', '')|replace('6', '')|replace('7', '')|replace('8', '')|replace('9', '')|replace('a', '')|replace('b', '')|replace('c', '')|replace('d', '')|replace('e', '')|replace('f', '') == '' %}
{% if enabled and scheduled and manager == 'salt' and (test_mode or (approval_valid and scheduled_apply_authorized == approved_hash)) %}
scheduled_run:
  test.nop:
    - name: package update state is operating under an explicit scheduled policy

package-updates-scheduled-uptodate:
  pkg.uptodate:
    - refresh: true
    - require:
      - test: scheduled_run
{% if os_family == 'Debian' %}
    - dist_upgrade: false
{% endif %}
{% else %}
package-updates-scheduled-policy-rejected:
  test.fail_without_changes:
    - name: scheduled update policy is missing or live exact-plan approval does not match
{% endif %}