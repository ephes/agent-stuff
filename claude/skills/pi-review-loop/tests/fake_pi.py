#!/usr/bin/env python3
"""Fake `pi` for runner tests. Modes via argv[1]:
  clean      -> emit a CLEAN agent_end and exit 0
  issues     -> emit an ISSUES agent_end and exit 0
  hang       -> emit one event then sleep forever (stall)
  crash      -> print a malformed line then exit 1 (no agent_end)
  posthang   -> emit a CLEAN agent_end then sleep forever (M3 exit hang)
  provider_error -> emit a failed auto_retry then exit 1 (M2 provider give-up)
"""
import json
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def agent_end(text):
    return {"type": "agent_end", "messages": [
        {"role": "assistant", "content": [{"type": "text", "text": text}]},
    ]}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    emit({"type": "agent_start"})
    if mode == "clean":
        emit(agent_end("REVIEW: CLEAN"))
    elif mode == "issues":
        emit(agent_end("REVIEW: ISSUES\n1. [Warning] a.py: tidy this"))
    elif mode == "hang":
        emit({"type": "message_update"})
        time.sleep(3600)
    elif mode == "crash":
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()
        sys.exit(1)
    elif mode == "posthang":
        emit(agent_end("REVIEW: CLEAN"))
        time.sleep(3600)
    elif mode == "provider_error":
        emit({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 1, "delayMs": 0})
        emit({"type": "auto_retry_end", "success": False, "attempt": 1,
              "finalError": "529 overloaded"})
        sys.exit(1)


if __name__ == "__main__":
    main()
