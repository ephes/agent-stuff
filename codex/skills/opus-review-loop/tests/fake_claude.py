#!/usr/bin/env python3
"""Fake `claude --output-format stream-json` for runner tests. Modes via argv[1]:
  clean      -> emit a CLEAN result and exit 0
  issues     -> emit an ISSUES result and exit 0
  hang       -> emit one event then sleep forever (stall)
  crash      -> print a malformed line then exit 1 (no result)
  posthang   -> emit a CLEAN result then sleep forever (exit hang)
  provider_error -> emit an error result then exit 1
"""
import json
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
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "total_cost_usd": 0.01,
        "terminal_reason": "completed",
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
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


if __name__ == "__main__":
    main()
