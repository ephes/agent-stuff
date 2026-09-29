#!/usr/bin/env python3
"""Fake `pi` for runner tests. Modes via argv[1]:
  clean      -> emit a CLEAN agent_end and exit 0
  issues     -> emit an ISSUES agent_end and exit 0
  hang       -> emit one event then sleep forever (stall)
  crash      -> print a malformed line then exit 1 (no agent_end)
  posthang   -> emit a CLEAN agent_end then sleep forever (M3 exit hang)
  provider_error -> emit a failed auto_retry then exit 1 (M2 provider give-up)
  forbidden_tool -> run an unlisted tool, then CLEAN
  delegate   -> run `pi -p` through bash, then CLEAN

With FAKE_PI_OUT set, it first records what it finds in its working directory
(the repository copy) there, then writes into that copy.
"""
import json
import os
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
    out = os.environ.get("FAKE_PI_OUT")
    if out:
        cwd = os.getcwd()
        files = {}
        for d, _, names in os.walk(cwd):
            if ".git" in os.path.relpath(d, cwd).split(os.sep):
                continue
            for name in names:
                rel = os.path.relpath(os.path.join(d, name), cwd)
                with open(os.path.join(cwd, rel), errors="replace") as fh:
                    files[rel] = fh.read()
        with open(out, "w") as fh:
            json.dump({"cwd": cwd, "files": files,
                       "tmpdir": os.environ.get("TMPDIR")}, fh)
        with open(os.path.join(cwd, "a.py"), "w") as fh:
            fh.write("REVIEWER_WROTE = 1\n")
    emit({"type": "agent_start"})
    if mode == "forbidden_tool":
        emit({"type": "tool_execution_start", "toolCallId": "1",
              "toolName": "subagent", "args": {"task": "review"}})
        mode = "clean"
    elif mode == "delegate":
        emit({"type": "tool_execution_start", "toolCallId": "1",
              "toolName": "bash", "args": {"command": "cd .. && pi -p review"}})
        mode = "clean"
    else:
        emit({"type": "tool_execution_start", "toolCallId": "0",
              "toolName": "bash", "args": {"command": "rg -n pi src"}})
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
