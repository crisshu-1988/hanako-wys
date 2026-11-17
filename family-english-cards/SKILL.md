---
name: family-english-cards
description: Create and deliver daily English vocabulary cards for IELTS preparation, prioritizing phrases used with children at home, with IPA, Chinese meaning, bilingual examples, pronunciation audio, active recall, and spaced review.
---

# Family English Cards

Use this skill for the user's daily English learning, vocabulary review, family-context phrase creation, or Feishu card delivery.

## Defaults

- Teach 10 new phrases per day.
- Review all due items first, then add 10 new items.
- Prioritize phrases that can be used naturally at home with a child.
- Keep every card to: phrase, IPA, Chinese meaning, English example, Chinese translation, audio.
- Optimize for active production, not passive recognition.
- Prefer IELTS-usable chunks that remain natural in family conversation.
- Use American English by default; accept British English without marking it wrong.
- Use feedback-driven intervals: good recall advances while hard recall returns sooner.
- Failed items reappear once at the end of the current session, then return the next day.
- Do not add more than 10 new items in one day.

## Daily Workflow

Build the next session:

```bash
python3 scripts/flow.py run
```

The interactive bot sends one question at a time, records `会 / 模糊 / 不会`, updates the current card, and automatically sends the next question.

The learning-center card can reopen the current English item without resetting progress:

```bash
python3 scripts/flow.py open
python3 scripts/flow.py invalidate
```

`open` increments the card view so older English cards become stale; `invalidate` only expires the current view when switching to another stream.

The session generator:

1. Reads `data/family_core.json`.
2. Reads personal progress from `${CODEX_HOME:-$HOME/.codex}/family-english-cards/state.json`.
3. Selects due reviews before new items.
4. Writes a Markdown session and an OPUS audio file per item.
5. Sends a Feishu interactive card when Feishu is configured.

Never claim that a Feishu message was delivered unless the API returns success. If configuration or delivery fails, report the exact log path.

## Learner Interaction

When the learner supplies a rating:

- `会`: recall was correct, quick, and unaided.
- `模糊`: correct but slow, uncertain, or hint-dependent.
- `不会`: wrong or unavailable after a hint.

Record the rating with:

```bash
python3 scripts/flow.py callback --date YYYY-MM-DD --item-id <item-id> --action rate --turn <turn> --rating <会|模糊|不会>
```

Do not equate seeing a card with mastering it. A daily push marks an interval as delivered, not mastered.

At the end of a study exchange, ask the learner to choose three phrases and use them with their child in a real exchange. Correct only errors that affect meaning or naturalness.

## Adding Content

Keep the initial bank family-first and IELTS-useful. New items must follow `references/data-format.md`. Avoid rare idioms, baby talk, abstract exam vocabulary that cannot occur naturally at home, and phrases that are unnatural in ordinary family speech.

When the learner requests a specific scene, add 10–20 entries that cover a coherent routine such as morning, meals, homework, chores, outdoor safety, emotions, bedtime, or weekends.

## Feishu Setup

Read `references/feishu-setup.md` before asking for credentials or changing delivery mode. For scheduled personal delivery, recommend an internal group containing the user; external groups require separately enabled External Sharing and identity verification.

Store credentials only in:

```text
${CODEX_HOME:-$HOME/.codex}/family-english-cards/config.json
```

Never put App Secret or a webhook URL in the skill folder, chat output, logs, or source control.

## Scheduled Delivery

Install or refresh the macOS 22:00 schedule with:

```bash
python3 scripts/schedule.py install
```

Check it with:

```bash
python3 scripts/schedule.py status
```

The scheduled job is local to this Mac. It cannot run while the Mac is powered off. If the Mac is asleep at 22:00, launchd normally starts the missed job after wake.

## Files

- `data/family_core.json`: curated family-first phrase bank.
- `references/data-format.md`: card schema and quality rules.
- `references/feishu-setup.md`: one-time Feishu bot setup.
- `scripts/flow.py`: interactive session state, rating logic, and delivery.
- `scripts/daily.py`: legacy/session utility functions, audio generation, and configuration commands.
- `scripts/interactive_bot.js`: the single shared Feishu long-connection callback listener for English, concept fables, and the learning center.
- `scripts/feishu.py`: Feishu API delivery.
- `scripts/schedule.py`: macOS launchd schedule and listener management.
