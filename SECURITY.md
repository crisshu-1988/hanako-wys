# Security

Never commit:

- Feishu App Secret or webhook credentials
- user sessions or answer history
- generated audio
- runtime logs
- `node_modules`
- bundled binary executables

The listener reads credentials only from:

```text
${CODEX_HOME:-$HOME/.codex}/family-english-cards/config.json
```
