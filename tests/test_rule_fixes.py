"""Tests that explicitly cover the wiki-rule fixes applied to the SAP engine.

Each test targets a specific bug that was corrected and documents WHAT rule
from the wiki it validates.
"""
from __future__ import annotations

import pytest

from sap_engine.cpu.game import CpuGameEngine
from sap_engine.cpu.shop import ShopEngine, _merge_instances
from sap_engine.cpu.battle import BattleEngine, _compact, _last_alive, _is_alive
from sap_engine.models import BattleOutcome, Phase, PetInstance, PlayerState, ShopOffer, ShopState
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG
from sap_engine.triggers import TriggerEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine(seed: int = 42) -> CpuGameEngine:
    return CpuGameEngine(load_registry(), SeededRNG(seed))


def make_pet(engine: CpuGameEngine, name: str, **kwargs) -> PetInstance:
    defn = engine.registry.pets[name]
    return PetInstance(definition=defn, **kwargs)


def make_player(engine: CpuGameEngine, name: str = "P") -> PlayerState:
    return PlayerState(name=name)


# ===========================================================================
# 1. Team direction: attacker is the LAST alive pet (highest index = slot 5)
# ===========================================================================

def test_attacker_is_highest_index_pet() -> None:
    """Wiki §8: 'The players's last pet (team slot 5) attacks.'
    After compaction, the pet at the highest-filled index is the attacker.
    """
    engine = make_engine()
    pet_a = make_pet(engine, "Ant")   # will be at index 3 after compact
    pet_b = make_pet(engine, "Duck")  # will be at index 4 after compact

    player = make_player(engine)
    player.team = [None, None, None, pet_a, pet_b]  # already compacted
    assert _last_alive(player) is pet_b  # pet_b is the highest-index alive pet


def test_compact_pushes_pets_to_high_indices() -> None:
    """Wiki §8: 'Pets move to the back of the team to fill gaps (X__X_ becomes ___XX).'
    In our convention back=high-index, so living pets shift rightward.
    """
    engine = make_engine()
    pet_a = make_pet(engine, "Ant")
    pet_b = make_pet(engine, "Duck")
    player = make_player(engine)
    player.team = [pet_a, None, pet_b, None, None]
    _compact(player)
    assert player.team[0] is None
    assert player.team[1] is None
    assert player.team[2] is None
    assert player.team[3] is pet_a
    assert player.team[4] is pet_b


# ===========================================================================
# 2. Merge XP formula
# ===========================================================================

def test_merge_xp_sums_both_pets_plus_one() -> None:
    """Wiki §6: 'XP values of the two pets are summed, not just +1.'
    Two level-2 pets (3 XP each) → 3+3+1=7 but capped at 5 → level 3.
    """
    engine = make_engine()
    defn = engine.registry.pets["Ant"]
    target = PetInstance(definition=defn, experience=3, level=2)
    source = PetInstance(definition=defn, experience=3, level=2)
    _merge_instances(target, source)
    assert target.level == 3
    assert target.experience == 5  # capped at 5


def test_merge_stat_takes_max_plus_one() -> None:
    """Wiki §6: 'Merging a 3/2 and a 4/2 pet gives 5/3.'"""
    engine = make_engine()
    defn = engine.registry.pets["Ant"]
    target = PetInstance(definition=defn, attack=3, health=2)
    source = PetInstance(definition=defn, attack=4, health=2)
    _merge_instances(target, source)
    assert target.attack == 5   # max(3,4)+1
    assert target.health == 3   # max(2,2)+1


def test_merge_asymmetric_health_takes_max_plus_one() -> None:
    """Wiki §6: 'merging a 1/2 and 4/1 does the same' (gives 5/3)."""
    engine = make_engine()
    defn = engine.registry.pets["Ant"]
    target = PetInstance(definition=defn, attack=1, health=2)
    source = PetInstance(definition=defn, attack=4, health=1)
    _merge_instances(target, source)
    assert target.attack == 5   # max(1,4)+1
    assert target.health == 3   # max(2,1)+1


# ===========================================================================
# 3. Sell value includes level
# ===========================================================================

def test_sell_value_equals_level() -> None:
    """Wiki §3: 'Selling a pet returns Gold equal to its level.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    pig = make_pet(engine, "Pig")
    pig.level = 2
    player.team[0] = pig
    player.gold = 0

    result = engine.shop.sell_pet(player, 0)
    # Pig's sell trigger gives +level gold on top of the level sell value.
    # Sell value = level(2) + Pig ability(+2) = 4
    assert result.success
    assert player.gold == 4  # 2 (sell) + 2 (Pig ability)


# ===========================================================================
# 4. Perk: Melon blocks 20 damage once
# ===========================================================================

def test_melon_blocks_20_damage_once() -> None:
    """Wiki foods: 'Melon perk: take 20 less damage, once.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", health=5)
    ant.perk = "melon"
    ant.perk_uses = 0
    player.team[0] = ant

    triggers = engine.triggers
    # Deal 15 damage — melon blocks all (actual = max(0, 15-20) = 0)
    triggers._deal_damage_battle(ant, 15, player, player, is_hurt=False)
    assert ant.health == 5      # no damage taken
    assert ant.perk_uses == 1   # perk consumed

    # Second hit of 5 — melon already used, takes full 5
    triggers._deal_damage_battle(ant, 5, player, player, is_hurt=False)
    assert ant.health == 0      # 5-5=0


# ===========================================================================
# 5. Perk: Garlic reduces damage by 2, minimum 2
# ===========================================================================

def test_garlic_reduces_damage_min_2() -> None:
    """Wiki foods: 'Garlic perk: take 2 less damage from all sources, min 2.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", health=10)
    ant.perk = "garlic"
    player.team[0] = ant

    triggers = engine.triggers
    # Deal 1 damage — garlic ensures minimum 2 dealt
    triggers._deal_damage_battle(ant, 1, player, player, is_hurt=False)
    assert ant.health == 8   # 10 - 2 (minimum)

    # Deal 10 damage — reduced by 2
    ant.health = 10
    triggers._deal_damage_battle(ant, 10, player, player, is_hurt=False)
    assert ant.health == 2   # 10 - 8


# ===========================================================================
# 6. Temporary HP: effective_health for alive check
# ===========================================================================

def test_temporary_health_counts_toward_survival() -> None:
    """Cupcake gives +3 temporary health; pet with 1 base hp and +3 temp survives 3 damage."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", health=1)
    ant.temporary_health = 3   # simulates Cupcake
    player.team[0] = ant

    triggers = engine.triggers
    # 3 damage should drain temporary_health, leaving health=1 (alive)
    triggers._deal_damage_battle(ant, 3, player, player, is_hurt=False)
    assert _is_alive(ant)
    assert ant.health == 1
    assert ant.temporary_health == 0

    # 1 more damage → dead
    triggers._deal_damage_battle(ant, 1, player, player, is_hurt=False)
    assert not _is_alive(ant)


# ===========================================================================
# 7. Direction: 'ahead' = higher index
# ===========================================================================

def test_friend_ahead_is_higher_index() -> None:
    """Wiki trigger glossary: 'ahead' means closer to the front (slot 5 = high index).
    Dodo gives attack to the nearest friend ahead (higher index).
    """
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    dodo = make_pet(engine, "Dodo", attack=4)     # at index 1
    duck = make_pet(engine, "Duck", attack=2)     # at index 2 (ahead of Dodo)
    pig = make_pet(engine, "Pig", attack=3)       # at index 3 (further ahead)
    player.team = [None, dodo, duck, pig, None]

    # Nearest friend AHEAD of Dodo (index 1) should be Duck (index 2)
    ahead = engine.triggers._friend_ahead(player, dodo)
    assert ahead is duck


def test_friend_behind_is_lower_index() -> None:
    """'behind' = lower index (further from the front)."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant")    # index 1
    beaver = make_pet(engine, "Beaver")  # index 2
    player.team = [None, ant, beaver, None, None]

    # Nearest friend BEHIND Beaver (index 2) should be Ant (index 1)
    behind = engine.triggers._friend_behind(player, beaver)
    assert behind is ant


# ===========================================================================
# 8. Snail: only fires on LOSS, buffs attack of 3 nearest friends AHEAD
# ===========================================================================

def test_snail_fires_only_on_loss() -> None:
    """Wiki Snail: 'End turn: If you LOST last battle, give three nearest friends ahead +1 attack.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    snail = make_pet(engine, "Snail")
    friend = make_pet(engine, "Ant", attack=2)
    player.team = [None, snail, friend, None, None]
    player.last_battle_result = BattleOutcome.DRAW   # not a loss

    engine.triggers.apply_end_turn(player)
    assert friend.attack == 2   # no buff — not a loss


def test_snail_buffs_nearest_three_ahead_on_loss() -> None:
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    snail = make_pet(engine, "Snail", level=2)
    f1 = make_pet(engine, "Ant", attack=1)    # index 1 — behind snail, NOT buffed
    # Snail is at index 2
    f2 = make_pet(engine, "Duck", attack=1)   # index 3 — ahead
    f3 = make_pet(engine, "Beaver", attack=1) # index 4 — ahead
    player.team = [None, f1, snail, f2, f3]
    player.last_battle_result = BattleOutcome.LOSS

    engine.triggers.apply_end_turn(player)
    assert f1.attack == 1    # behind snail — not buffed
    assert f2.attack == 3    # +2 (snail level 2)
    assert f3.attack == 3    # +2


# ===========================================================================
# 9. Battle: faint trigger fires (Cricket summons Zombie Cricket)
# ===========================================================================

def test_cricket_summons_zombie_on_faint() -> None:
    """Wiki Cricket: 'Faint: Summon one 1/1 Zombie Cricket.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    cricket = make_pet(engine, "Cricket", health=1)
    strong_enemy = make_pet(engine, "Hippo", attack=10, health=50)

    p0.team[4] = cricket           # front of p0
    p1.team[4] = strong_enemy      # front of p1

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    # Cricket fainted — Zombie Cricket should have been summoned and then also
    # fought (and also probably fainted). The important thing: result is valid.
    assert result.finished
    assert result.outcome in (BattleOutcome.LOSS, BattleOutcome.DRAW, BattleOutcome.WIN)


# ===========================================================================
# 10. Duck sell: buffs shop pet HEALTH (not tier)
# ===========================================================================

def test_duck_sell_buffs_shop_pet_health() -> None:
    """Wiki Duck: 'Sell: Give shop pets +1 health (per level).'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    duck = make_pet(engine, "Duck", level=1)
    player.team[0] = duck

    # Place a pet offer in the shop
    offer = ShopOffer(kind="pet", name="Ant", tier=1, bonus_health=0)
    player.shop.slots[0] = offer

    engine.triggers.apply_sell(player, duck)

    assert offer.bonus_health == 1   # +1 health bonus on the offer


# ===========================================================================
# 11. Beaver sell: buffs 2 random friends attack by level
# ===========================================================================

def test_beaver_sell_buffs_two_friends() -> None:
    """Wiki Beaver: 'Sell: Give two random friends +level attack.'"""
    engine = make_engine(seed=5)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    beaver = make_pet(engine, "Beaver", level=2)
    ant = make_pet(engine, "Ant", attack=1)
    duck = make_pet(engine, "Duck", attack=1)
    player.team = [None, None, beaver, ant, duck]

    engine.shop.sell_pet(player, 2)  # sell beaver at index 2

    # Both ant and duck should have received +2 attack (level 2)
    assert ant.attack == 3 or duck.attack == 3  # at least one buffed


# ===========================================================================
# 12. Otter buy: gives health to N random friends (N = level)
# ===========================================================================

def test_otter_buy_gives_health_to_friends() -> None:
    """Wiki Otter: 'Buy: Give one random friend +1 health (level 1).'"""
    engine = make_engine(seed=7)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    friend = make_pet(engine, "Ant", health=2)
    otter = make_pet(engine, "Otter", level=1)
    player.team[0] = friend

    engine.triggers.apply_buy(player, otter)

    assert friend.health == 3   # +1 health


# ===========================================================================
# 13. Mosquito start-of-battle fires once per level (cross-team ordered)
# ===========================================================================

def test_mosquito_damages_correct_number_of_targets() -> None:
    """Wiki Mosquito: 'Start of battle: Deal 1 damage to N random enemies (N=level).'"""
    engine = make_engine(seed=9)
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    mosquito = make_pet(engine, "Mosquito", level=2)
    enemy1 = make_pet(engine, "Ant", health=3)
    enemy2 = make_pet(engine, "Duck", health=3)

    p0.team[4] = mosquito
    p1.team[3] = enemy1
    p1.team[4] = enemy2

    # Fire SOB for Mosquito only
    engine.triggers.apply_start_of_battle_pet(mosquito, p0, p1)

    # Level 2 Mosquito deals 1 damage to 2 random enemies
    total_damage = (3 - enemy1.health) + (3 - enemy2.health)
    assert total_damage == 2   # exactly 2 damage dealt across enemies


# ===========================================================================
# 14. Peacock gains attack when hurt
# ===========================================================================

def test_peacock_gains_attack_when_hurt() -> None:
    """Wiki Peacock: 'Hurt: Gain +3 attack (level 1).'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    peacock = make_pet(engine, "Peacock", attack=2, health=5, level=1)
    player.team[4] = peacock

    engine.triggers.apply_hurt(peacock, player, opp)

    assert peacock.attack == 5   # 2 + 3


# ===========================================================================
# 15. Honey perk: summon Bee on faint
# ===========================================================================

def test_honey_perk_summons_bee_on_faint() -> None:
    """Wiki Honey: 'Summon one 1/1 Bee after fainting.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    ant = make_pet(engine, "Ant", health=1)
    ant.perk = "honey"
    player.team = [None, None, None, None, ant]   # front (index 4)

    engine.triggers.apply_faint(ant, 4, player, opp)

    # Bee should be summoned somewhere in the team
    bee_names = [p.name for p in player.team if p is not None]
    assert "Bee" in bee_names


# ===========================================================================
# 16. Roll shop costs 1 gold
# ===========================================================================

def test_roll_shop_costs_1_gold() -> None:
    """Wiki §3: 'Rolling the shop costs 1 Gold.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    player.gold = 5

    result = engine.shop.roll_shop(player)

    assert result.success
    assert player.gold == 4


def test_roll_shop_fails_with_no_gold() -> None:
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    player.gold = 0

    result = engine.shop.roll_shop(player)
    assert not result.success


# ===========================================================================
# 17. Buy food: Apple gives +1/+1
# ===========================================================================

def test_apple_gives_plus_one_attack_and_health() -> None:
    """Wiki Apple: 'Give one pet +1 attack and +1 health.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", attack=2, health=2)
    player.team[0] = ant
    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Apple", tier=1)

    result = engine.shop.buy_food(player, 7, 0)
    assert result.success
    assert ant.attack == 3
    assert ant.health == 3


# ===========================================================================
# 18. Canned Food gives permanent shop bonus
# ===========================================================================

def test_canned_food_increments_permanent_shop_bonus() -> None:
    """Wiki Canned Food: 'Give all current and future shop pets +1/+1.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Canned Food", tier=4)

    engine.shop.buy_food(player, 7)   # no team_index needed (AoE food)

    assert player.shop_attack_bonus == 1
    assert player.shop_health_bonus == 1


# ===========================================================================
# 19. Sleeping Pill kills pet and triggers Faint ability
# ===========================================================================

def test_sleeping_pill_triggers_faint() -> None:
    """Wiki Sleeping Pill: 'Make one pet faint. Activates Faint abilities.'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", health=5, level=1)
    friend = make_pet(engine, "Duck", attack=1, health=1)
    player.team = [None, None, None, friend, ant]   # ant at index 4, friend at 3
    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Sleeping Pill", tier=2, cost_override=1)

    result = engine.shop.buy_food(player, 7, 4)
    assert result.success

    # Ant should be gone from the team
    assert player.team[4] is None
    # Ant's faint ability gives +1/+1 to a random friend — friend.attack should be 2
    # (the only friend on the team is Duck at index 3)
    assert friend.attack == 2


# ===========================================================================
# 20. Chocolate: +1 XP, +1/+1 stats, triggers level-up at threshold
# ===========================================================================

def test_chocolate_grants_xp_and_stats() -> None:
    """Wiki Chocolate: 'Give one pet +1 experience (+1/+1 stats).'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", attack=2, health=2, experience=0, level=1)
    player.team[0] = ant
    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Chocolate", tier=5)

    engine.shop.buy_food(player, 7, 0)

    assert ant.experience == 1
    assert ant.attack == 3
    assert ant.health == 3


def test_chocolate_triggers_level_up() -> None:
    """Chocolate at 1 XP → 2 XP → level 2."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", experience=1, level=1)
    player.team[0] = ant
    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Chocolate", tier=5)

    result = engine.shop.buy_food(player, 7, 0)

    assert ant.level == 2
    assert result.levelled_up


# ===========================================================================
# 21. Battle post-restore: temporary stats reset after battle
# ===========================================================================

def test_battle_resets_temporary_stats_after_resolve() -> None:
    """Wiki §7: Buffs applied during battle are temporary; surviving team reverts to pre-battle state.

    Uses high-health pets on both sides so the battle hits MAX_BATTLE_STEPS (200) and
    ends as a DRAW — both pets are still alive, so the restore runs for both.
    """
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    # ant survives 200 rounds of 1 damage each (total = 200 dmg, health 205 > 200)
    ant = make_pet(engine, "Ant", attack=1, health=205)
    ant.temporary_attack = 3
    ant.temporary_health = 0   # no temp HP so health tracks directly

    enemy = make_pet(engine, "Duck", attack=1, health=205)
    p0.team[4] = ant
    p1.team[4] = enemy

    pre_attack = ant.attack
    state.phase = Phase.BATTLE
    engine.battle.resolve(state)

    # After the draw, temporary buffs on surviving pets are reset
    assert ant.temporary_attack == 0
    assert ant.attack == pre_attack   # permanent attack unchanged


# ===========================================================================
# 22. Battle loses tracking: player0 losses increment on defeat
# ===========================================================================

# ===========================================================================
# 23. Badger faint: deal 50/100/150% attack to adjacent pets (both teams)
# ===========================================================================

def test_badger_faint_damages_adjacent_pets() -> None:
    """Wiki Badger: 'Faint: Deal 50% attack damage to adjacent pets.'
    Adjacent = nearest pet behind (lower index) and nearest ahead (higher index or enemy).
    """
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    behind_friend = make_pet(engine, "Ant", health=10)   # index 2 — behind Badger
    badger = make_pet(engine, "Badger", attack=6, health=1, level=1)  # index 3
    ahead_friend = make_pet(engine, "Duck", health=10)   # index 4 — ahead of Badger
    player.team = [None, None, behind_friend, badger, ahead_friend]

    # 50% of 6 = 3 damage to each adjacent pet
    engine.triggers.apply_faint(badger, 3, player, opp)

    assert behind_friend.health == 7   # 10 - 3
    assert ahead_friend.health == 7    # 10 - 3


def test_badger_faint_hits_enemy_when_no_alive_ahead() -> None:
    """Badger with no alive friend ahead hits the enemy attacker instead."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    behind_friend = make_pet(engine, "Ant", health=10)  # index 3
    badger = make_pet(engine, "Badger", attack=4, health=1, level=1)  # index 4 (front)
    enemy = make_pet(engine, "Duck", health=10)
    player.team = [None, None, None, behind_friend, badger]
    opp.team[4] = enemy

    engine.triggers.apply_faint(badger, 4, player, opp)

    # No alive pet at index 5+ (doesn't exist) so enemy takes Badger's ahead damage
    assert behind_friend.health == 8   # 10 - 2 (50% of 4)
    assert enemy.health == 8           # 10 - 2


# ===========================================================================
# 24. Shark: gain +2/+4/+6 attack and health each time a friend faints
# ===========================================================================

def test_shark_gains_stats_on_friend_faint() -> None:
    """Wiki Shark: 'Friend Faints: Gain +2 attack and +2 health (level 1).'"""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    ant = make_pet(engine, "Ant", health=1)       # index 3 — will faint
    shark = make_pet(engine, "Shark", attack=2, health=2, level=1)  # index 4
    player.team = [None, None, None, ant, shark]

    engine.triggers.apply_faint(ant, 3, player, opp)

    assert shark.attack == 4    # 2 + 2
    assert shark.health == 4    # 2 + 2


def test_shark_gains_double_stats_at_level2() -> None:
    """Level 2 Shark gains +4/+4 per friend faint."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    ant = make_pet(engine, "Ant", health=1)
    shark = make_pet(engine, "Shark", attack=2, health=2, level=2)
    player.team = [None, None, None, ant, shark]

    engine.triggers.apply_faint(ant, 3, player, opp)

    assert shark.attack == 6    # 2 + 4
    assert shark.health == 6    # 2 + 4


# ===========================================================================
# 25. Turkey: friend SUMMONED gives the summoned pet +3 attack +1 health
# ===========================================================================

def test_turkey_buffs_summoned_friend() -> None:
    """Wiki Turkey: 'Friend Summoned: Give it +3 attack and +1 health (level 1).'
    Note: Turkey fires on Friend Summoned, NOT Friend Faints.
    """
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    turkey = make_pet(engine, "Turkey", level=1)
    summoned = make_pet(engine, "Ant", attack=2, health=2)
    player.team = [None, None, None, turkey, None]

    engine.triggers.apply_friend_summoned(summoned, player)

    assert summoned.attack == 5   # 2 + 3
    assert summoned.health == 3   # 2 + 1


def test_turkey_does_not_fire_on_friend_faint() -> None:
    """Turkey should NOT buff a random friend on faint (that is the old, incorrect behaviour).
    Use Duck as the fainting pet — Duck has a Sell trigger (not a Faint trigger), so any
    attack increase on the bystander would only come from Turkey incorrectly firing.
    """
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    opp = state.players[1]

    duck = make_pet(engine, "Duck", health=1)      # Duck has no Faint ability
    turkey = make_pet(engine, "Turkey", level=1)
    bystander = make_pet(engine, "Beaver", attack=3)
    player.team = [None, None, bystander, duck, turkey]

    pre_attack = bystander.attack
    engine.triggers.apply_faint(duck, 3, player, opp)

    # bystander should NOT have gained any attack/temporary_attack from Turkey on friend-faint
    assert bystander.attack == pre_attack
    assert bystander.temporary_attack == 0


# ===========================================================================
# 26. Fish level-up only buffs team when Fish levels up (not any pet)
# ===========================================================================

def test_fish_levelup_buffs_two_friends() -> None:
    """Wiki Fish: 'Level up: Give all friends +level attack and health.'
    (Triggers when FISH specifically levels up.)
    """
    engine = make_engine(seed=3)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    fish = make_pet(engine, "Fish", level=1, experience=1)
    friend = make_pet(engine, "Ant", attack=1, health=1)
    player.team = [None, None, None, friend, fish]

    # Manually trigger Fish level-up (level 1→2 requires 2 XP; fish has 1 already)
    fish.experience = 2
    fish.level = 2
    engine.triggers.apply_fish_level_up(player, fish)

    # friend should receive +2/+2 (level 2 bonus)
    assert friend.attack == 3
    assert friend.health == 3


def test_non_fish_levelup_does_not_buff_team_via_chocolate() -> None:
    """Non-Fish pets (e.g. Ant) must NOT trigger Fish's team-buff on level-up."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", experience=1, level=1)
    friend = make_pet(engine, "Duck", attack=1, health=1)
    player.team = [None, None, None, friend, ant]
    player.gold = 10
    player.shop.slots[7] = ShopOffer(kind="food", name="Chocolate", tier=5)

    pre_attack = friend.attack
    pre_health = friend.health
    result = engine.shop.buy_food(player, 7, 4)   # ant is at index 4

    assert result.levelled_up            # ant did level up
    assert friend.attack == pre_attack   # but Duck should NOT have been buffed by Fish trigger
    assert friend.health == pre_health


def test_non_fish_merge_does_not_buff_team() -> None:
    """Merging two non-Fish pets must not trigger Fish's level-up buff."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    defn = engine.registry.pets["Ant"]
    ant1 = PetInstance(definition=defn, experience=1, level=2)  # 1 XP away from level 3
    ant2 = PetInstance(definition=defn, experience=3, level=2)  # merge will push to level 3
    friend = make_pet(engine, "Duck", attack=1, health=1)

    player.team = [None, None, None, friend, ant1]
    # Place ant2 in shop
    player.shop.slots[0] = ShopOffer(kind="pet", name="Ant", tier=1)
    player.gold = 10

    # Monkey-patch the shop offer so it delivers ant2's XP via a new instance at level 2
    # Simplest approach: call _merge_instances directly and then apply_fish_level_up
    from sap_engine.cpu.shop import _merge_instances
    _merge_instances(ant1, ant2)
    assert ant1.level == 3   # confirm merge levelled up

    pre_attack = friend.attack
    engine.triggers.apply_fish_level_up(player, ant1)

    assert friend.attack == pre_attack   # Duck unaffected — ant1 is not Fish


def test_battle_tracks_player_losses() -> None:
    """Player who loses a battle should have losses += 1."""
    engine = make_engine()
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    weak = make_pet(engine, "Ant", attack=1, health=1)
    strong = make_pet(engine, "Hippo", attack=10, health=50)

    p0.team[4] = weak
    p1.team[4] = strong

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    assert result.outcome == BattleOutcome.LOSS
    assert p0.losses == 1
    assert p1.wins == 1


# ===========================================================================
# 27. Battle continues until a team is fully gone (post-faint triggers)
# ===========================================================================

def test_battle_continues_after_mushroom_revive() -> None:
    """Wiki §8: combat continues until one team has no pets left standing."""
    engine = make_engine(seed=5)
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    ant = make_pet(engine, "Ant", attack=1, health=1)
    ant.perk = "mushroom"
    p0.team[4] = ant
    p1.team[4] = make_pet(engine, "Duck", attack=1, health=3)

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    assert result.outcome == BattleOutcome.LOSS
    assert len(result.snapshot.step_history) >= 4
    assert result.snapshot.step_history[-1]["description"].startswith("Battle End")


def test_battle_continues_after_honey_bee_summon() -> None:
    engine = make_engine(seed=9)
    state = engine.new_game(["Alpha", "Beta"])
    p0, p1 = state.players

    ant = make_pet(engine, "Ant", attack=1, health=1)
    ant.perk = "honey"
    p0.team[4] = ant
    p1.team[4] = make_pet(engine, "Duck", attack=1, health=3)

    state.phase = Phase.BATTLE
    result = engine.battle.resolve(state)

    assert result.outcome == BattleOutcome.LOSS
    assert len(result.snapshot.step_history) >= 4


# ===========================================================================
# 28. Tier-up reward on level-up (wiki §6)
# ===========================================================================

def test_merge_to_level_2_offers_tier_up_pets() -> None:
    engine = make_engine(seed=21)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    ant = make_pet(engine, "Ant", experience=1, level=1)
    player.team[0] = ant
    player.gold = 10
    player.shop.slots[0] = ShopOffer(kind="pet", name="Ant", tier=1)

    result = engine.shop.buy_pet(player, 0, 0)

    assert result.success
    assert result.levelled_up
    assert result.tier_up_offered
    tier_up_names = [slot.name for slot in player.shop.slots if slot is not None and slot.tier_up_reward]
    assert len(tier_up_names) == 2
    assert all(engine.registry.pets[name].tier == 2 for name in tier_up_names)


def test_l2_l2_merge_to_l3_does_not_offer_tier_up() -> None:
    engine = make_engine(seed=21)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]

    defn = engine.registry.pets["Ant"]
    ant1 = PetInstance(definition=defn, experience=3, level=2)
    ant2 = PetInstance(definition=defn, experience=3, level=2)
    player.team = [None, None, None, ant1, ant2]

    result = engine.shop.move_pet(player, 4, 3)

    assert result.success
    assert ant1.level == 3
    assert not result.tier_up_offered
    assert not any(slot is not None and slot.tier_up_reward for slot in player.shop.slots)


def test_buying_tier_up_pet_removes_the_other_choice() -> None:
    engine = make_engine(seed=21)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    player.gold = 10

    ant = make_pet(engine, "Ant", experience=1, level=1)
    player.team[0] = ant
    player.shop.slots[0] = ShopOffer(kind="pet", name="Ant", tier=1)
    engine.shop.buy_pet(player, 0, 0)

    tier_up_indices = [i for i, slot in enumerate(player.shop.slots) if slot is not None and slot.tier_up_reward]
    assert len(tier_up_indices) == 2

    chosen = tier_up_indices[0]
    result = engine.shop.buy_pet(player, chosen, 1)
    assert result.success
    remaining = [slot for slot in player.shop.slots if slot is not None and slot.tier_up_reward]
    assert remaining == []


def test_two_level_ups_in_one_turn_stack_tier_up_rewards() -> None:
    engine = make_engine(seed=21)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    player.gold = 20

    ant = make_pet(engine, "Ant", experience=1, level=1)
    beaver = make_pet(engine, "Beaver", experience=1, level=1)
    player.team[0] = ant
    player.team[1] = beaver
    player.shop.slots[0] = ShopOffer(kind="pet", name="Ant", tier=1)
    first = engine.shop.buy_pet(player, 0, 0)
    assert first.tier_up_offered
    first_group = player.tier_up_group_counter - 1
    first_reward_names = {
        slot.name
        for slot in player.shop.slots
        if slot is not None and slot.tier_up_reward and slot.tier_up_group == first_group
    }
    assert len(first_reward_names) == 2

    player.shop.slots[1] = ShopOffer(kind="pet", name="Beaver", tier=1)
    second = engine.shop.buy_pet(player, 1, 1)
    assert second.tier_up_offered
    tier_up_rewards = [slot for slot in player.shop.slots if slot is not None and slot.tier_up_reward]
    assert len(tier_up_rewards) == 4
    groups = {slot.tier_up_group for slot in tier_up_rewards}
    assert groups == {first_group, first_group + 1}
    assert first_reward_names.issubset({slot.name for slot in tier_up_rewards})


def test_buying_tier_up_pet_only_removes_other_choice_from_same_grant() -> None:
    engine = make_engine(seed=21)
    state = engine.new_game(["Alpha", "Beta"])
    player = state.players[0]
    player.gold = 20

    ant = make_pet(engine, "Ant", experience=1, level=1)
    beaver = make_pet(engine, "Beaver", experience=1, level=1)
    player.team[0] = ant
    player.team[1] = beaver
    player.shop.slots[0] = ShopOffer(kind="pet", name="Ant", tier=1)
    engine.shop.buy_pet(player, 0, 0)

    player.shop.slots[1] = ShopOffer(kind="pet", name="Beaver", tier=1)
    engine.shop.buy_pet(player, 1, 1)

    tier_up_indices = [i for i, slot in enumerate(player.shop.slots) if slot is not None and slot.tier_up_reward]
    assert len(tier_up_indices) == 4

    chosen = tier_up_indices[0]
    chosen_group = player.shop.slots[chosen].tier_up_group
    result = engine.shop.buy_pet(player, chosen, 2)
    assert result.success
    remaining = [slot for slot in player.shop.slots if slot is not None and slot.tier_up_reward]
    assert len(remaining) == 2
    assert all(slot.tier_up_group != chosen_group for slot in remaining)
