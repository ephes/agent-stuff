#!/usr/bin/env python3
"""Fake `codex` for harness tests. It receives the production argv, reads the
prompt from stdin, prints `codex exec --json` events, writes the final message
to the `-o` path, and writes a session record under $CODEX_HOME/sessions the
way Codex does. The mode comes from FAKE_CODEX_MODE:

  clean, issues            complete a turn with that verdict
  wrong_model, wrong_effort, reroute, no_turn_context, no_record
                           complete CLEAN, but the session record disagrees
  spawn_record             CLEAN, but the record holds a collaboration call
  spawn_stream             CLEAN, but the event stream shows a collab call
  unlisted_tool            CLEAN, but the record holds an unlisted tool
  subagent_meta            CLEAN, but the record is a subagent thread
  capacity                 error events, then turn.failed, exit 1
  error_exit               an error event, then exit 1 without a turn
  crash                    exit 3 without any event
  hang                     thread.started, then silence forever
  posthang                 CLEAN, then never exit
  orphan                   CLEAN, exit 0, but leave a sleeping child behind
  silent_recording         print nothing for FAKE_CODEX_SILENCE seconds while
                           the session record grows, then CLEAN
  exit_after_turn          CLEAN, final message written, then exit 2
  exit_143_after_turn      the same with status 143, which looks like SIGTERM
  bad_json, clean_with_findings, issues_without_findings
                           complete a turn with a malformed final message
"""
import json
import os
import subprocess
import sys
import time
import uuid

MODEL, EFFORT = "gpt-6-sol", "medium"


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def arg_after(flag):
    argv = sys.argv[1:]
    return argv[argv.index(flag) + 1] if flag in argv else None


def main():
    mode = os.environ.get("FAKE_CODEX_MODE", "clean")
    home = os.environ["CODEX_HOME"]
    if os.path.realpath(home) == os.path.realpath(os.path.expanduser("~/.codex")):
        sys.stderr.write("fake codex refuses to write into the real CODEX_HOME\n")
        sys.exit(9)
    prompt = sys.stdin.read()
    with open(os.path.join(home, "last-stdin.txt"), "w") as fh:
        fh.write(prompt)
    with open(os.path.join(home, "last-argv.json"), "w") as fh:
        json.dump(sys.argv[1:], fh)
    with open(os.path.join(home, "last-env.json"), "w") as fh:
        json.dump(dict(os.environ), fh)
    out_path = arg_after("-o")
    # Report the effort the harness asked for, as Codex does; wrong_effort
    # reports another one.
    effort = EFFORT
    for i, arg in enumerate(sys.argv[:-1]):
        if arg == "-c" and sys.argv[i + 1].startswith("model_reasoning_effort="):
            effort = json.loads(sys.argv[i + 1].split("=", 1)[1])

    if mode == "crash":
        sys.exit(3)
    thread_id = str(uuid.uuid4())
    emit({"type": "thread.started", "thread_id": thread_id})
    emit({"type": "turn.started"})
    if mode == "hang":
        time.sleep(3600)
    if mode == "capacity":
        emit({"type": "error", "message": "Reconnecting... 1/2"})
        emit({"type": "turn.failed",
              "error": {"message": "Selected model is at capacity. Please try a different model."}})
        sys.exit(1)
    if mode == "error_exit":
        emit({"type": "error", "message": "stream disconnected before completion"})
        sys.exit(1)

    day = os.path.join(home, "sessions", "2026", "09", "23")
    os.makedirs(day, exist_ok=True)
    record_path = os.path.join(day, f"rollout-2026-09-23T10-00-00-{thread_id}.jsonl")
    records = []
    source = "exec"
    if mode == "subagent_meta":
        source = {"subagent": {"thread_spawn": {"parent_thread_id": "x"}}}
    records.append({"type": "session_meta",
                    "payload": {"cli_version": "0.156.1", "source": source}})
    if mode != "no_turn_context":
        records.append({"type": "turn_context", "payload": {
            "model": "gpt-5.6-sol" if mode == "wrong_model" else MODEL,
            "effort": "low" if mode == "wrong_effort" else effort}})
    records.append({"type": "response_item", "payload": {
        "type": "custom_tool_call", "name": "exec",
        "input": "text('reroute is just a word in reviewed code')"}})
    if mode == "reroute":
        records.append({"type": "event_msg", "payload": {
            "type": "model_reroute", "from_model": MODEL, "to_model": "gpt-5.6-sol"}})
    if mode == "spawn_record":
        records.append({"type": "response_item", "payload": {
            "type": "function_call", "name": "spawn_agent",
            "namespace": "collaboration", "arguments": "{}"}})
    if mode == "unlisted_tool":
        records.append({"type": "response_item", "payload": {
            "type": "function_call", "name": "web_search", "arguments": "{}"}})

    def write_record():
        with open(record_path, "w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    if mode != "no_record":
        write_record()
    if mode == "silent_recording":
        silence = float(os.environ.get("FAKE_CODEX_SILENCE", "3"))
        end = time.time() + silence
        while time.time() < end:
            time.sleep(0.2)
            records.append({"type": "response_item", "payload": {"type": "reasoning"}})
            write_record()
    if mode == "spawn_stream":
        emit({"type": "item.completed", "item": {
            "id": "item_9", "type": "collab_tool_call", "tool": "spawn_agent"}})

    final = {"verdict": "CLEAN", "findings": []}
    if mode == "issues":
        final = {"verdict": "ISSUES", "findings": [
            {"severity": "Warning", "path": "a.py", "message": "tidy this"}]}
    text = json.dumps(final)
    if mode == "bad_json":
        text = "Looks fine to me.\nREVIEW: CLEAN"
    elif mode == "clean_with_findings":
        text = json.dumps({"verdict": "CLEAN", "findings": [
            {"severity": "Critical", "path": "a.py", "message": "broken"}]})
    elif mode == "issues_without_findings":
        text = json.dumps({"verdict": "ISSUES", "findings": []})
    emit({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": text}})
    if out_path:
        with open(out_path, "w") as fh:
            fh.write(text)
    emit({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
    if mode == "posthang":
        time.sleep(3600)
    if mode == "exit_after_turn":
        sys.exit(2)
    if mode == "exit_143_after_turn":
        sys.exit(143)
    if mode == "orphan":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
        with open(os.path.join(home, "orphan.pid"), "w") as fh:
            fh.write(str(child.pid))
    sys.exit(0)


if __name__ == "__main__":
    main()
