# coord-watchdog changelog

## Unreleased

- New check `swap-high`: swap in use above `SWAP_THRESHOLD_GB` (16) for
  `SWAP_SUSTAIN_MIN` (15 minutes), read from `sysctl -n vm.swapusage`. The
  Studio swapped 71 GB on 2026-11-08 while load peaked at 897; the load check
  alone does not show memory exhaustion. An unreadable reading never opens
  the finding and keeps an open one open.
- New tool: deterministic five-minute check of the coordination pipeline
  (Codex feeder, queue and `automerge.off` age; stuck and unacknowledged
  Katharina workers; `work usage status` freshness; the coordinator heartbeat
  `coordination/coordinator.heartbeat`; sustained machine load). Each finding
  escalates once: an optional message command (none exists for the desktop
  app yet), after 15 minutes one bounded headless Claude diagnosis run (Opus,
  15-minute limit, may only restart a dead feeder through `coord-watchdog
  restart-feeder`, which detaches it with `BACKLOG_MAX=20 BACKLOG_HOURS=48`), then a notification to
  `watchdog/notifications.log`, herdr and the work-app item `coord-watchdog`.
  Installed on the Studio as the LaunchAgent `de.wersdoerfer.coord-watchdog`
  (chezmoi).
