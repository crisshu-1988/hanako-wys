# Weekly Generation

Generate seven items each Sunday and place them in the user bank only after checking:

1. The concept is graduate-level rather than a general slogan.
2. The fable preserves the concept's causal structure.
3. The concept name is absent from the story.
4. All four options are plausible and only one is correct.
5. The source is a real canonical paper, book, or institutional publication.
6. Child-development items distinguish, where relevant, implications for ages 1, 3, and 5.

Recommended weekly mix follows the weekday rotation:

- AI personal agent
- Household economics
- Child development
- Repeat in that order

Prefer durable concepts over news-driven topics. Store the generated batch as data only; do not include credentials or user answer history.

## Merge and Verify

Save the generated batch as an `items` array in a temporary JSON file, then run:

```bash
python3 scripts/add_bank.py --file /path/to/batch.json
```

The merger rejects duplicates, invalid domains, malformed options, leaked concept names, and stories outside 700–1200 characters. It writes only to the private `${CODEX_HOME:-$HOME/.codex}/concept-fables/bank.json`; it never exposes or changes Feishu credentials.
