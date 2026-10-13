# The Lost Temple game logic

AI-assisted Roblox/Luau game project. These selected modules show round
lifecycle rules, progression, malformed-save handling and entitlement isolation.
They add game-state modeling to the web/backend examples in this portfolio.

[Round](src/Round.luau) tracks who joined, survived and earned rewards.
[Progress](src/Progress.luau) cleans and merges saves while enforcing earned
unlock prerequisites. [Catalog](src/Catalog.luau) defines the progression items.

With the official Luau CLI, from this directory:

```bash
luau tests/round.spec.luau tests/progress.spec.luau
```

Both suites passed on 13 October 2026. The round suite covers 16 lifecycle
cases including duplicate events, stale waves, eliminated players and reward
idempotency. Progress tests cover stale/concurrent merge order, corrupt data,
quest dependencies and preventing saved records from granting paid privileges.

The full project's local trap, chest, navigation and expedition tests also
passed that day. Those modules and Studio fixtures are outside this snapshot.
No new Studio, multiplayer or physical-device playtest was performed. Local
logic tests do not prove live publishing, engagement, revenue or game balance.

[Portfolio](../../README.md).
