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

Hosts may specify a narrow `latest_packages` list alongside the general
upgrade state. Salt applies `pkg.latest` only to already-installed packages in
that list (`only_upgrade: true`), allowing APT to resolve required package
dependencies without enabling distribution upgrades. `mgmt.rdt.dev` uses this
for `fwupd` because a regular APT upgrade held back its candidate while that
candidate required installing `libfwupd3` and `libdrm-amdgpu1`. Review the
preview before applying this host policy.

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

## Kali rolling workstation policy

`rdt-kali` (`rdt-kali.core.home.rdt.dev`) is explicitly enrolled in a
master-scheduled Salt-owned update policy. Ordinary daily highstate remains
configuration convergence and does not install the scheduled broad package
set. The management-host timer evaluates only the explicit `managed_minions`
allowlist, which currently contains `rdt-kali`; each target must additionally
return pillar with `enabled: true`, `manager: salt`, and `scheduled: true`.
Native APT unattended updates remain disabled, preventing competing package
manager jobs.

Kali uses `pkg.uptodate` with metadata refresh and Debian `dist_upgrade: false`.
This does not request a full dependency-changing distribution upgrade or
autoremove. A weekly run is due Saturday between 02:00 and 05:00
`America/Chicago`; the master checks policy daily with random delay. Updates
are deferred while `loginctl list-sessions` reports any interactive session;
the idle check is queried from the Kali minion itself, not the master.
The plan is bounded to 750 available upgrades and a 60-minute Salt job. A
larger backlog, missing policy, missed Salt return, failed state, remaining
upgrades, or a reboot-required check that cannot be verified produces an
`ISSUE:` alert. Not a live-apply authorization. Per-minion records and a run
summary are written under
`/var/lib/redsalt/package-updates/`; last success, last attempt, package
counts, failures, reboot status, and stale status are recorded. Success is
considered stale after `stale_after_days: 9`; stale alerts are repeated no more
than daily.

Live package application is separately gated by `approved_preview_sha256`,
which is empty by default. The runner fingerprints the exact test-mode plan;
until that fingerprint is explicitly approved for the named host, the runner
may inspect the available-upgrade count and run Salt test mode, but it will not
execute the mutating package state. Keep the fingerprint empty until the human
reviews the real target-specific preview and approves the maintenance run by
recording the exact 64-character plan fingerprint in minion pillar.

The scheduled state also enforces this gate itself: Salt test mode remains
available for plan review, but a live state apply requires an explicit one-run
Pillar override `scheduled_apply_authorized` that is a valid, nonempty
64-character lowercase hexadecimal fingerprint equal to the configured
approved fingerprint. Empty or malformed values are rejected, including when
both override and configured approval are empty. The master runner passes this
value through the Salt `pillar` state argument only after checking the approved
plan.
It refreshes metadata and re-runs test mode immediately before mutation; if the
host-bound fingerprint differs from the approved preview, it records the new
plan for review and stops without applying packages.

The fingerprint includes the minion ID as well as the canonicalized planned
state changes, so it cannot be replayed as approval on another host. Before
starting preview or mutation, the runner checks the minion's own clock and
requires enough remaining local maintenance-window time for the bounded
operation and verification. If the deadline is too close, it defers without
consuming the failure retry cadence.

There is no automatic package rollback: downgrades and dependency reversal are
not assumed safe or available on Kali rolling. For a failed or service-impacting
update, stop further runs by setting the exact minion's scheduled/update opt-in
off, retain the runner status and Salt job evidence, then recover using the
workstation owner's reviewed recovery image or a verified host backup and
validate Salt/network/operator access before re-enrollment. The Kali pillar
currently keeps its backup role disabled, so verify a usable recovery point
before authorizing the first live update; do not treat the configured backup
scope as proof that a backup exists.

Automatic reboot is explicitly disabled for the shared security workstation.
If the OS requires reboot after patching, the runner records the condition and
alerts for an operator-approved maintenance/reboot action. Test-mode previews
and validation are not authorization to apply the state to a live workstation;
after a reviewed merge, follow the approval and canary procedure in the issue.
The production service change and a live Kali application are separate steps.

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
