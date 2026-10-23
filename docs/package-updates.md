# Package update policy

## Defaults and precedence

`package_updates.defaults` applies to all managed hosts. A per-minion
`package_updates` mapping overrides matching default fields. The supported
manager values are:

- `salt` (default): enabled hosts' highstate runs Salt `pkg.uptodate`; package
  backend/provider is selected from minion grains. This is the recommended
  centralized policy.
- `native`: Salt configures the OS unattended updater only when
  `native_unattended: true`. Do not enable both managers on one host; that can
  contend on the package database lock and make maintenance timing ambiguous.

The shipped global defaults leave package updates disabled until a host opts
in, preserving existing fleet behavior. The `mgmt.rdt.dev` host override opts
that system into Salt updates and refreshes package metadata. On Debian-family
hosts the Salt state passes `dist_upgrade: false` explicitly, avoiding
autoremove/full dependency transitions; the normal provider upgrade path still
updates packages in place. It does not enable a competing native updater.
Other hosts remain unchanged until they receive an explicit host override.

## OS handling

- Debian/Ubuntu/Kali: Salt package provider; `dist_upgrade` is opt-in. Native
  mode installs `unattended-upgrades`, enables daily APT list refresh and
  unattended-upgrade timers, and leaves allowed-origin policy to the
  distribution defaults. APT-only reboot policy is written as a drop-in.
- RHEL-family: Salt selects YUM/DNF provider. Native mode configures
  `dnf-automatic` and its install timer; all upgrades are the native-mode
  default, configurable to security-only using a host-specific setting.
- Fedora 41+: Salt selects DNF provider. Native mode uses the `dnf5-plugin-automatic`
  package and `dnf5-automatic.timer`; Fedora's unified timer/config semantics
  differ from older DNF4 timer units.
- SUSE: Salt selects Zypper provider. Native auto-update is deliberately
  rejected by this state because transactional-update may trigger a reboot
  outside the approved maintenance window. Add a reviewed policy per SUSE
  release before enabling native mode.
- Other families: use Salt manager only after verifying the installed Salt
  package provider supports that OS. Unsupported native combinations do not
  silently fall back to a different package manager.

Native updater branches install the distro package for the helper when
available; if a minimal image does not offer that package, opt for the Salt
manager or adjust only after validating that OS's supported tooling.

## Reboots

Automatic reboot is disabled by default. If an operator opts a host in, Salt
manages a once-daily systemd check at the configured host-local time (06:00 on
`mgmt.rdt.dev`). The timer does not catch up after downtime, preventing an
unexpected reboot at startup. The helper
reboots only when a recognized OS signal says a reboot is needed: Debian's
reboot-required marker, RPM-family `needs-restarting -r`, or a pending
rpm-ostree deployment. It does not reboot on an unknown check result. Validate
the detector for each distribution before enabling this policy. Native APT
automatic reboot is explicitly disabled; opt-in hosts use the controlled
reboot-check timer instead. The
`mgmt.rdt.dev` host override enables a 06:00 UTC check explicitly; do not infer
that all hosts inherit a reboot authorization.

## Rollout/verification

Review `salt '<id>' state.show_highstate`, `salt '<id>' state.apply
package_updates test=True`, and `salt '<id>' pkg.list_upgrades` before real
application. Check the native timer only when `manager: native` is explicitly
selected. Updates take effect only after an approved production promotion and
subsequent highstate; adding this policy to a branch does not immediately
change a live host.

Enable an individual host by adding this mapping to its pillar; keep automatic
reboot disabled unless the owner explicitly approves a maintenance window:

```yaml
package_updates:
  manager: salt
  enabled: true
  refresh: true
  debian_dist_upgrade: false
  native_unattended: false
  automatic_reboot: false
```
