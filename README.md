# hanako-wys
wys-hanako- personality



Two independent daily learning streams delivered through one Feishu app and one long-connection listener:

- **Family English Cards** at 22:00: active-recall vocabulary, audio, and spaced review.
- **Concept Fables** at 20:30: Chinese fable, four-choice concept quiz, and detailed explanation.
- **Learning Center**: a pinned card that opens either stream without resetting the other one.

## Architecture

Each stream has its own private state directory under `${CODEX_HOME:-$HOME/.codex}`. The pinned learning-center message is patched in place so pinning survives status updates.

One listener owns all callbacks:

```text
family-english-cards/scripts/interactive_bot.js
```

Callback values are routed by `module`:

```json
{"module":"english"}
{"module":"concept_fable"}
{"module":"hub","action":"open","target":"english"}
```

Old English cards without `module` default to the English route for backward compatibility. New cards include a `view_id`; switching streams increments the source view so an older card becomes stale rather than mutating the newly active stream.

## Local Setup

1. Install Node dependencies for the listener:

   ```bash
   cd family-english-cards/vendor
   npm ci
   ```

2. Create `${CODEX_HOME:-$HOME/.codex}/family-english-cards/config.json` from `family-english-cards/config.example.json`. Keep the App Secret outside source control.

3. Install both schedules:

   ```bash
   python3 family-english-cards/scripts/schedule.py install
   python3 concept-fables/scripts/schedule.py install
   ```

4. Run the offline regression test:

   ```bash
   python3 learning-hub/scripts/smoke_test.py
   ```

## Private Data

This repository intentionally excludes Feishu credentials, learning state, sessions, answer history, audio, logs, generated batches, `node_modules`, and the bundled ffmpeg binary. The private content bank lives at `${CODEX_HOME:-$HOME/.codex}/concept-fables/bank.json`; only the curated seed bank is versioned.
