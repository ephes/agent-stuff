#!/usr/bin/env python3
"""Fake `claude --output-format stream-json` for runner tests. Modes via argv[1]:
  clean      -> emit a CLEAN result and exit 0
  issues     -> emit an ISSUES result and exit 0
  hang       -> emit one event then sleep forever (stall)
  crash      -> print a malformed line then exit 1 (no result)
  crash_whitespace -> write only whitespace to stderr then exit 1
  posthang   -> emit a CLEAN result then sleep forever (exit hang)
  provider_error -> emit an error result then exit 1
  forbidden_tool -> emit a forbidden Agent tool event before a CLEAN result
  forbidden_provider_error -> emit forbidden Agent and a provider error together
  out_of_scope_read -> read /etc/hosts (not denied) before returning CLEAN
  out_of_scope_denied -> request /etc/hosts, get a permission denial, return CLEAN
  missing_structured -> emit a success result without structured output
  stdin_empty -> return CLEAN only when stdin is empty
  stdin_prompt -> return CLEAN only when stdin contains "review prompt"

With FAKE_CLAUDE_OUT set, it first records what it finds in its working
directory (the repository copy) there, then writes into that copy.
"""
import json
import os
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def assistant(text):
    return {"type": "assistant", "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
    }}


def result(text):
    if text == "REVIEW: CLEAN":
        structured = {"verdict": "CLEAN", "findings": []}
    else:
        structured = {
            "verdict": "ISSUES",
            "findings": [{"severity": "Warning", "path": "a.py",
                          "message": "tidy this"}],
        }
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "structured_output": structured,
        "total_cost_usd": 0.01,
        "terminal_reason": "completed",
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    out = os.environ.get("FAKE_CLAUDE_OUT")
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
                       "git_config_global": os.environ.get("GIT_CONFIG_GLOBAL")},
                      fh)
        with open(os.path.join(cwd, "a.py"), "w") as fh:
            fh.write("REVIEWER_WROTE = 1\n")
    emit({"type": "system", "subtype": "init"})
    if mode == "clean":
        emit(assistant("REVIEW: CLEAN"))
        emit(result("REVIEW: CLEAN"))
    elif mode == "issues":
        text = "REVIEW: ISSUES\n1. [Warning] a.py: tidy this"
        emit(assistant(text))
        emit(result(text))
    elif mode == "hang":
        emit({"type": "assistant", "message": {"role": "assistant", "content": []}})
        time.sleep(3600)
    elif mode == "crash":
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()
        sys.exit(1)
    elif mode == "crash_whitespace":
        sys.stderr.write("\n")
        sys.stderr.flush()
        sys.exit(1)
    elif mode == "posthang":
        emit(result("REVIEW: CLEAN"))
        time.sleep(3600)
    elif mode == "provider_error":
        emit({
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "api_error_status": "529 overloaded",
            "terminal_reason": "api_error",
        })
        sys.exit(1)
    elif mode == "forbidden_tool":
        emit(assistant("checking"))
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Agent", "input": {"prompt": "review"}}
        ]}})
        emit(result("REVIEW: CLEAN"))
    elif mode == "forbidden_provider_error":
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Agent", "input": {"prompt": "review"}}
        ]}})
        emit({
            "type": "result", "subtype": "error", "is_error": True,
            "api_error_status": "529 overloaded", "terminal_reason": "api_error",
        })
    elif mode in ("out_of_scope_read", "out_of_scope_denied"):
        emit({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_oos", "name": "Read",
             "input": {"file_path": "/etc/hosts"}}
        ]}})
        if mode == "out_of_scope_denied":
            answer = {"is_error": True, "content": (
                "Permission to use Read has been denied because Claude Code "
                "is running in don't ask mode.")}
        else:
            answer = {"content": "127.0.0.1 localhost"}
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_oos", **answer}
        ]}})
        emit(result("REVIEW: CLEAN"))
    elif mode == "missing_structured":
        emit({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "REVIEW: CLEAN", "total_cost_usd": 0.01,
        })
    elif mode == "stdin_empty":
        text = "REVIEW: CLEAN" if sys.stdin.read() == "" else "REVIEW: ISSUES\n1. [Warning] stdin: inherited unexpected input"
        emit(result(text))
    elif mode == "stdin_prompt":
        text = "REVIEW: CLEAN" if "review prompt" in sys.stdin.read() else "REVIEW: ISSUES\n1. [Warning] stdin: prompt missing"
        emit(result(text))


if __name__ == "__main__":
    main()
