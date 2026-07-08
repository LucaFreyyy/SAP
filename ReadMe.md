# Super Auto Pets Engine (sap-engine)

A Python implementation of a Super Auto Pets clone — Turtle Pack, Versus Mode.

## Project overview

This project implements the full game engine for a SAP clone:

- **`sap_engine/models.py`** — All data classes: `PetInstance`, `PlayerState`, `GameState`, `ShopState`, `ShopOffer`, enums for `Phase`, `BattleOutcome`, `TriggerType`.
- **`sap_engine/registry.py`** — Parses `sap_wiki/` text files into `DataRegistry` (pets, foods, tokens).
- **`sap_engine/rng.py`** — Seeded RNG wrapper (`SeededRNG`) for reproducibility.
- **`sap_engine/triggers.py`** — `TriggerEngine`: all pet ability and food perk logic. Organised per trigger type (SOT, EOT, Buy, Sell, SOB, Faint, Hurt, Knock Out, Friend Summoned, After Attack).
- **`sap_engine/paths.py`** — Tier lists, shop layout, file paths, helper functions.
- **`sap_engine/cpu/shop.py`** — `ShopEngine`: buy pet/food, sell, roll, freeze, merge.
- **`sap_engine/cpu/battle.py`** — `BattleEngine`: full combat loop with compacting, perks, faint/hurt chain handling.
- **`sap_engine/cpu/game.py`** — `CpuGameEngine`: top-level orchestrator.
- **`sap_engine/gpu/`** — GPU-accelerated batch simulator (stub, Phase 5).
- **`sap_engine/ui/`** — Pygame UI (Phase 4).
- **`sap_wiki/`** — Reference data (pets/foods/tokens summaries, scraped wiki dump).
- **`tests/`** — pytest suite.

## Team layout convention

```
index 0 = slot 1 = BACK of team
index 4 = slot 5 = FRONT of team (the attacker)
"ahead"  = higher index (toward the attacker)
"behind" = lower index (toward the back)
Compact: living pets slide toward index 4 before each combat step.
```

## Running tests

```bash
python -m pytest tests/ -v
```

No secrets or external services required. Dependencies: `pygame>=2.5` (already installed).

## Roadmap (Workflow.txt)

- Phase 1–2 ✅ Core data, shop/battle logic, unit tests
- Phase 3 — Heuristic AI (`ShopAI`)
- Phase 4 — Pygame CPU UI (skeleton exists in `sap_engine/ui/`)
- Phase 5 — GPU-accelerated batch simulator (`sap_engine/gpu/`)
- Phase 6 — AI evolution / RL integration

## User preferences

- Correct game rules come from `sap_wiki/` (general_rules.txt, pets_summary.txt, foods_summary.txt, tokens_summary.txt).
- Keep existing project structure; do not migrate or restructure.
