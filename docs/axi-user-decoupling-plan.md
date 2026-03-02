# Plan: AxiUser Decoupling from Discord User

## Current State

`AxiUser` lives in `user_handler.py` and directly wraps a `discord.abc.User` object:
- `isinstance(uid, User)` check in constructor
- `send()` method delegates to Discord User
- `parse(mention=True)` accesses `self.uid.mention` (Discord-specific attribute)
- `parse(mention=False)` calls `str(self.uid)` (Discord User string representation)

**Already achieved**: The pure layer (match_handler, ladder_handler, game classes) does NOT import
user_handler or AxiUser. Objects are passed in by discord_handler. Tests use FakeUser.

**Remaining implicit coupling**: ladder_handler calls `opp.parse(mention=True)`, which only works
because AxiUser.uid is a Discord User with `.mention`. The pure layer assumes things about the
AxiUser object that only hold for Discord Users.

## Strategy: Pure AxiUser + Discord Adapter

Make AxiUser a plain data class (no Discord imports). The Discord adapter (`user_handler.get_user`)
extracts display name and mention string at construction time.

### New file: `axi/axi_user.py`

```python
class AxiUser:
    def __init__(self, uid_id, display_name, mention_str=None):
        self.uid = type('Uid', (), {'id': uid_id})()
        self._display_name = display_name
        self._mention = mention_str or display_name

    def parse(self, mention=False):
        return self._mention if mention else self._display_name

    def __str__(self):
        return self.parse()

    def __repr__(self):
        return self.parse()
```

### Changes

| File | Change |
|---|---|
| `axi/axi_user.py` | **New.** Pure AxiUser class — no Discord imports. |
| `axi/handlers/user_handler.py` | Import AxiUser from `axi.axi_user`. Remove `from discord.abc import User`. `get_user()` extracts `uid.id`, display name, mention string from Discord User before constructing AxiUser. |
| `axi/handlers/discord_handler.py` | Line 368: `await p.uid.send(...)` → `discord_user = bot.get_user(p.uid.id); await discord_user.send(...)` (AxiUser.uid no longer has `.send()`). |
| `tests/conftest.py` | FakeUser already matches the pure AxiUser interface (`.uid.id`, `parse()`, `str()`). No changes needed. |

### What gets removed from AxiUser

- `from discord.abc import User` — no longer needed
- `isinstance(uid, User)` check — accepts pre-extracted data
- `send()` method — pure layer never calls it; discord_handler uses `bot.get_user()`

### Verification

1. All 56 existing tests pass (FakeUser already matches the pure interface)
2. `axi/axi_user.py` has zero Discord imports
3. ladder_handler's `parse(mention=True)` calls work via stored mention string
4. discord_handler's spectator notification works via `bot.get_user()`
