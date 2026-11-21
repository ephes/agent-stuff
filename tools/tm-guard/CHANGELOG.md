# tm-guard changelog

## Unreleased

- Preserve exact byte and file counts in reports and progress tracking.
  Reject fractional counts.
- Treat status with an invalid `Running` flag as unreadable. Accept
  plist booleans and the legacy integers 0 and 1.

- Sync ownership records before releasing the `tmutil` gate and report
  publication failures as probe errors. Persist progress state durably.
- Report an unknown start or kill time for live ownership records with
  unreadable timestamps and keep further probes blocked.

- New tool: a five-minute Time Machine stall probe for the Studio
  (LaunchAgent `de.wersdoerfer.tm-guard`, chezmoi). Records whether `tmutil
  status` answers within 120 s (a child killed by its own PID when it does
  not; one that still does not exit blocks further `tmutil` runs and is
  reported as `hung`), phase and progress, whether automatic backups are on
  (off is a normal state), and the newest band write in the bundle on
  fractal (read-only SSH), and counts how long a running backup went
  without any progress. Reported to macmini (`obs_ctl.py timemachine`) for
  Nyxmon's "Studio Time Machine progress" check: warning after 2 hours
  without progress, critical after 6 hours, when `tmutil` does not answer or
  when the probe falls silent. Follow-up of the stall of 2026-11-19/20.
