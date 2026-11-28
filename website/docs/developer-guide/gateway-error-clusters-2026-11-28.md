---
title: "Gateway Error Clusters: 2026-11-28"
description: "Engineering record for streaming tool-call argument loss and checkpoint root failures"
---

# Gateway error clusters: 2026-11-28

This note records the evidence and repairs for two runtime defect clusters observed through the
gateway. The source investigation reports lived outside the repository in an operator scratch
directory; this document is the self-contained engineering record.

## Evidence summary

The log review found 109 malformed streamed tool-call argument events:

- 41 calls had lost their header and the beginning of their argument JSON. The logged tool name was
  `?`; each surviving fragment began inside a value but generally retained its closing JSON. This
  is the signature of losing the first OpenAI-style tool-call delta, which normally carries the
  call ID, function name, and first argument bytes together.
- 61 `skill_manage` calls retained their name but ended at the identical fragment
  `{"operations":`. This is tail loss, not header loss, and is not fixed here. It needs raw stream
  capture in a separate follow-up to distinguish model output, provider parsing, and transport
  termination.
- Seven other named calls (`write_file`, `patch`, and `search_files`) also had tail-loss shapes.
  The existing truncation retry remains the intended recovery for that class.

No malformed call from this window was invoked with a substituted empty object. The stream
assembler discarded it and retried, but the only durable warning misleadingly described `{}`
replacement and could include argument content. The retry itself was absent from durable logs.

The checkpoint review found 16 failures: ten attempts to snapshot all of `/tmp`, where unrelated
permissions and nested repositories made `git add -A` fail, and six attempts against nonexistent
project subdirectories. Registry timestamps tied those errors to one `/tmp` project registration
and six registrations created before their directories existed.

## Streaming root cause and repair

The chat-completions stream loop temporarily holds text that could be an echoed SSE frame or the
router timeout sentinel. Its hold-back branch ended with `continue`, so a provider chunk containing
both held-back text and the first `delta.tool_calls` entry never fed that tool entry into the
accumulator. Whitespace made this particularly likely because whitespace-only text counted as a
possible prefix of every sentinel. Later argument-only deltas then produced an empty function name
and JSON missing its opening bytes.

The loop now continues into tool-call processing for the same chunk, and whitespace-only text is no
longer considered a possible timeout-shim prefix. Regression coverage exercises a header mixed with
whitespace, a header with no content, content in a preceding chunk, and ordinary text mixed with the
header. In each case the function name and complete parsed command must survive.

Observability now distinguishes the two repair sites:

- A nameless accumulated slot with argument bytes emits `tool_call_header_lost` with only slot, ID,
  length, brace shape, and finish reason, and forces discard/retry. Argument content is never logged.
- An unrepairable stream value logs only name and shape because the response will be discarded.
- A malformed historical value keeps the compatibility behavior of applying `{}` to the outgoing
  wire copy, with wording that makes clear persisted history is not rewritten.
- Every truncated-tool-call retry emits `truncated_tool_call_retry` in addition to the transient
  console status.

## Checkpoint root repair

The checkpoint manager now refuses the resolved shared roots `/tmp`, `/var/tmp`, `/dev/shm`, and
the platform `tempfile.gettempdir()`, just as it already refuses `/` and home-directory roots. A
project subdirectory beneath a temp root remains checkpointable.

Checkpoint creation returns before registration when the requested working directory does not
exist. Path ownership resolution first walks a not-yet-created destination up to its nearest
existing ancestor, then performs registered-owner and project-marker discovery. A write such as
`project/deploy/x/config.yaml` therefore belongs to the existing `project` root rather than minting
a nonexistent `deploy/x` project.

Missing-working-directory Git messages are debug-level diagnostics. Actual Git failures include
their working directory, which makes shared-root mistakes visible without logging file contents.
The implementation deliberately does not use `git add --ignore-errors`: it still exits nonzero and
would risk a partial snapshot.

## Verification

Run the focused behavior suites through the repository runner:

```bash
scripts/run_tests.sh \
  tests/agent/test_streaming.py \
  tests/agent/test_router_timeout_shim.py \
  tests/agent/test_streaming_tool_call_repair.py \
  tests/agent/test_repair_tool_call_arguments.py \
  tests/agent/test_truncated_tool_call_boost.py \
  tests/agent/checkpoints/test_checkpoint_manager.py -q
scripts/run_tests.sh tests/agent/test_stall_guards.py -q
```

Operationally, count `tool_call_header_lost`, `tool_call_args_unrepairable`, and
`truncated_tool_call_retry` separately. A recurrence of the exact `skill_manage {"operations":`
tail should trigger raw stream capture and the separate follow-up; it is not evidence that the
mixed-chunk header defect returned.
