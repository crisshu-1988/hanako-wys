---
name: concept-fables
description: Create and deliver Chinese fable-based daily learning cards for graduate-level concepts in AI personal agents, household economics, and child development, with a mystery question, localized answer feedback, and a detailed explanation.
---

# Concept Fables

Use this skill when the user asks for a concept fable, a talk-track learning piece, or the daily 20:30 concept learning flow.

## Defaults

- Deliver one story per day.
- Rotate domains by date: AI personal agent, household economics, child development.
- Keep the story in Chinese and do not reveal the concept name before the quiz.
- Target a graduate-level concept while keeping the narrative accessible.
- Make the concept inferable just before the ending, not stated explicitly in the story.
- Use four plausible quiz options.
- After an answer, show the correct concept, definition, fable-to-concept mapping, practical example, talk-track sentence, and source.
- Localize only the correct/incorrect toast. The story and explanation remain Chinese.

## Card Flow

1. **Story page:** title, domain label, full story, `开始答题` button, and `切换至英语` button.
2. **Quiz page:** one question and four answer buttons.
3. **Result page:** localized toast, correct answer, explanation, source, and a `切换至英语` button.

All page transitions happen by updating the same Feishu message in place. Use idempotent message UUIDs and preserve stale-card rejection through a `view_id`.

## Content Rules

- A fable is an indirect model, not a proof. It must preserve the concept's causal structure without pretending to be empirical evidence.
- Use named characters and concrete actions rather than explaining terminology inside the story.
- Avoid a story where the answer is arbitrary: every important story element should map to the concept.
- Verify canonical sources. Do not invent paper titles, authors, URLs, or findings.
- Avoid repeating a concept within 90 days when enough bank material remains.
- Child-development examples must distinguish implications for ages 1, 3, and 5 where relevant.

## Commands

```bash
python3 scripts/flow.py run
python3 scripts/flow.py open --date YYYY-MM-DD
python3 scripts/flow.py status
```

## Files

- `data/seed_bank.json`: curated starter stories.
- `references/content-schema.md`: story and quiz schema.
- `references/weekly-generation.md`: weekly replenishment and source-verification prompt.
- `scripts/flow.py`: session state and card generation.
- `scripts/add_bank.py`: validates and merges a weekly generated batch without overwriting the bank.
- `scripts/schedule.py`: 20:30 macOS launchd schedule.

## Shared Learning Center

The concept-fable card and the English card share one Feishu callback listener owned by
`family-english-cards/scripts/interactive_bot.js`. Never start a second WebSocket listener.
The pinned learning-center card lives under `${CODEX_HOME:-$HOME/.codex}/learning-hub` and
opens either stream through `module: "hub"` callbacks.

Open or invalidate the current card view:

```bash
python3 scripts/flow.py open --date YYYY-MM-DD
python3 scripts/flow.py invalidate --date YYYY-MM-DD
```

`open` sends the current page under a new view id. `invalidate` expires the old view when the
learner switches to the other stream.
