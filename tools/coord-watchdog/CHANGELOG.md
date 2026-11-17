# coord-watchdog changelog

## Unreleased

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
