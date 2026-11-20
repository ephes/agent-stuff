# tm-guard changelog

## Unreleased

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
