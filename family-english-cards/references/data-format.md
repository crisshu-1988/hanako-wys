# Data Format

## Phrase bank

`data/family_core.json` contains:

```json
{
  "version": 1,
  "items": [
    {
      "id": "family-001",
      "phrase": "Rise and shine.",
      "ipa": "/raɪz ənd ʃaɪn/",
      "zh": "起床啦。",
      "example": "Rise and shine! Breakfast is ready.",
      "example_zh": "起床啦！早餐好了。",
      "scene": "morning",
      "level": "A2",
      "tags": ["routine", "greeting"]
    }
  ]
}
```

Required fields:

- `id`: stable unique identifier; never reuse an ID for another phrase.
- `phrase`: natural English word or chunk.
- `ipa`: broad IPA pronunciation for the phrase.
- `zh`: concise Chinese meaning.
- `example`: an English sentence that sounds natural to say to a child.
- `example_zh`: accurate Chinese translation of the example.
- `scene`: one of `morning`, `meals`, `learning`, `chores`, `safety`, `emotions`, `outdoors`, `bedtime`, `family`.
- `level`: `A2`, `B1`, or `B2`.
- `tags`: one or more searchable labels.

## Quality rules

- Prefer reusable chunks such as `put away your toys`, not isolated textbook words with no family context.
- Keep examples short enough to say aloud in one breath.
- Do not force an IELTS connection. Use language whose IELTS value comes from being natural and reusable.
- Use contractions in examples when a parent would normally speak that way.
- Check IPA and sentence stress. Do not invent pronunciation.
- Avoid duplicate meanings and near-identical chunks.
- Use `please` only when it improves the phrase; do not make every sentence sound like a command.

## Personal state

The user's `state.json` is generated outside the skill directory. It tracks introduction and review-delivery dates. It is not a statement of mastery.
