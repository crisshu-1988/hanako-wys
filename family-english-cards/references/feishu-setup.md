# Feishu Setup

The recommended setup uses a Feishu custom app bot so the card can include playable OPUS audio. A group custom-bot webhook can send text cards but cannot upload the audio files used by the card audio component.

## Create the Feishu app

1. Open the Feishu Open Platform developer console.
2. Create a custom app named `亲子英语卡片`.
3. Enable the bot capability.
4. Add these permissions:
   - `im:message:send_as_bot`
   - `im:resource`
   - `im:chat:readonly`（用于自动列出机器人所在的群聊）
5. Create and publish a version. If the organization requires approval, complete that approval.
6. Add the bot to an **internal Feishu group** or make it available to the user who will receive messages. A daily learning group containing only the user is sufficient.
7. Copy the App ID and App Secret.
8. Under **Events and Callbacks > Mode of event/callback subscription**, select **Receive events/callbacks through persistent connection**.
9. Under **Callbacks**, subscribe to `card.action.trigger`.
10. Save and publish a new app version so the callback configuration takes effect.

The local listener must already be running before step 8 can be saved. Install it with:

```bash
python3 scripts/schedule.py install
```

## External groups

An app bot cannot normally be added directly to an external group. The app must enable **External Sharing** in **App Release > Version Management and Release > Create Version**, and the account must complete enterprise verification or personal identity verification. Publish the version and wait for approval before adding the bot. If **Associated Organization App Sharing** is enabled, External Sharing cannot be enabled at the same time.

For this daily vocabulary task, an internal group is recommended because it avoids identity verification, external-sharing review, and external-group API restrictions.

The user must supply the `chat_id` of the group that contains the bot. Keep the App Secret and chat ID in the local config only.

## Configure locally

Run:

```bash
python3 scripts/daily.py configure
```

The desktop shortcut `~/Desktop/配置亲子英语飞书.command` runs the same setup and keeps the App Secret hidden while typing.

The configuration is written to:

```text
${CODEX_HOME:-$HOME/.codex}/family-english-cards/config.json
```

Set file permissions to `600`. Do not send the App Secret through chat, paste it into a task, or put it in a commit.

## Webhook fallback

A Feishu group custom-bot webhook can be configured for text-only cards. This mode intentionally omits playable audio. Use it only if a custom app bot cannot be created.

## Troubleshooting

- `tenant_access_token` failure: verify App ID and App Secret, app status, and bot capability.
- Permission failure while sending: verify `im:message:send_as_bot` and that the bot belongs to the target chat.
- Audio upload failure: verify `im:resource`, OPUS format, duration, and that upload and send use the same app.
- Card rejected: use Feishu 7.49 or later and keep the JSON 2.0 schema intact.
- No 22:00 delivery: run `python3 scripts/schedule.py status`, then inspect the log path printed by that command.
