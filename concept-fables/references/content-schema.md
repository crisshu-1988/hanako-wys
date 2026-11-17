# Content Schema

Each bank item contains:

```json
{
  "id": "ai-pomdp-001",
  "domain": "ai_agent",
  "domain_label": "AI Personal Agent",
  "concept": "部分可观测马尔可夫决策过程（POMDP）",
  "title": "雾港的守灯人",
  "story": "Chinese fable text",
  "question": "这则寓言最可能在讲哪个概念？",
  "options": [
    {"id": "A", "text": "选项一", "correct": false},
    {"id": "B", "text": "选项二", "correct": true},
    {"id": "C", "text": "选项三", "correct": false},
    {"id": "D", "text": "选项四", "correct": false}
  ],
  "definition": "Exact but accessible Chinese definition.",
  "mapping": ["Story element -> concept element."],
  "application": "A real-world example.",
  "talk_track": "One reusable sentence for conversation.",
  "source": "Canonical source citation."
}
```

Requirements:

- Exactly four options.
- Exactly one correct option.
- The concept name must not appear in `title` or `story`.
- `story` should be approximately 700–1200 Chinese characters.
- `definition`, `mapping`, `application`, and `talk_track` enter the output only after the learner answers.
- Domain values: `ai_agent`, `household_economics`, `child_development`.
