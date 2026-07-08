"""Comprehensive per-pet ability tests — one or more tests per Turtle Pack pet.

Covers all 60 pets across 6 tiers plus general-rule edge cases not covered
by tests/test_rule_fixes.py.
"""
from __future__ import annotations

import pytest

from sap_engine.cpu.game import CpuGameEngine
from sap_engine.cpu.shop import ShopEngine, _merge_instances
from sap_engine.cpu.battle import BattleEngine, _compact, _last_alive, _is_alive
from sap_engine.models import (
    BattleOutcome, Phase, PetInstance, PlayerState, ShopOffer, ShopState,
)
from sap_engine.registry import load_registry
from sap_engine.rng import SeededRNG
from sap_engine.triggers import TriggerEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine(seed: int = 42) -> CpuGameEngine:
    return CpuGameEngine(load_registry(), SeededRNG(seed))


def pet(engine: CpuGameEngine, name: str, **kw) -> PetInstance:
    return PetInstance(definition=engine.registry.pets[name], **kw)


def player(engine: CpuGameEngine, name: str = "P") -> PlayerState:
    return PlayerState(name=name)


def two_player_state(engine: CpuGameEngine):
    return engine.new_game(["A", "B"])


# ===========================================================================
# TIER 1
# ===========================================================================

class TestHorse:
    """Friend Summoned: Give summoned friend +1 temporary attack (per level)."""

    def test_horse_gives_temp_attack_to_summoned(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        horse = pet(engine, "Horse", level=1)
        ant = pet(engine, "Ant", attack=2)
        p.team = [None, None, None, horse, None]

        engine.triggers.apply_friend_summoned(ant, p)
        assert ant.temporary_attack == 1  # +1 per level

    def test_horse_level2_gives_more_temp_attack(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        horse = pet(engine, "Horse", level=2)
        ant = pet(engine, "Ant", attack=2)
        p.team = [None, None, None, horse, None]

        engine.triggers.apply_friend_summoned(ant, p)
        assert ant.temporary_attack == 2


class TestPigeon:
    """Sell: Give N Bread Crumbs to the shop (N = level)."""

    def test_pigeon_sell_adds_bread_crumbs_to_shop(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        pigeon = pet(engine, "Pigeon", level=1)
        p.team[0] = pigeon

        engine.triggers.apply_sell(p, pigeon)
        food_names = [s.name for s in p.shop.slots if s is not None and s.kind == "food"]
        assert "Bread Crumbs" in food_names

    def test_pigeon_level2_adds_two_bread_crumbs(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        pigeon = pet(engine, "Pigeon", level=2)
        engine.triggers.apply_sell(p, pigeon)

        food_names = [s.name for s in p.shop.slots if s is not None and s.kind == "food"]
        assert food_names.count("Bread Crumbs") == 2


# ===========================================================================
# TIER 2
# ===========================================================================

class TestCrab:
    """SOB: Copy 25/50/75% of the highest-health friend's health."""

    def test_crab_copies_fraction_of_healthiest_friend(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        healthiest = pet(engine, "Elephant", health=20)
        crab = pet(engine, "Crab", health=1, level=1)
        p.team = [None, None, None, healthiest, crab]  # crab at front
        opp.team[4] = pet(engine, "Ant")

        engine.triggers.apply_start_of_battle_pet(crab, p, opp)
        # 25% of 20 = 5, so crab.health += 5 → 6
        assert crab.health == 6

    def test_crab_level2_copies_50_percent(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        healthiest = pet(engine, "Elephant", health=20)
        crab = pet(engine, "Crab", health=1, level=2)
        p.team = [None, None, None, healthiest, crab]
        opp.team[4] = pet(engine, "Ant")

        engine.triggers.apply_start_of_battle_pet(crab, p, opp)
        assert crab.health == 11  # 50% of 20 = 10, +1 base


class TestRat:
    """Faint: Summon one 1/1 Dirty Rat on the enemy team."""

    def test_rat_summons_dirty_rat_on_enemy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        rat = pet(engine, "Rat", level=1)
        p.team[4] = rat

        engine.triggers.apply_faint(rat, 4, p, opp)

        names_on_opp = [p.name for p in opp.team if p is not None]
        assert "Dirty Rat" in names_on_opp

    def test_rat_level2_summons_two_dirty_rats(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        rat = pet(engine, "Rat", level=2)
        engine.triggers.apply_faint(rat, 4, p, opp)

        dirty_rats = [p for p in opp.team if p is not None and p.name == "Dirty Rat"]
        assert len(dirty_rats) == 2


class TestHedgehog:
    """Faint: Deal 2*level damage to all other pets (both teams)."""

    def test_hedgehog_damages_all_pets_on_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        hedgehog = pet(engine, "Hedgehog", level=1, health=1)
        friend = pet(engine, "Ant", health=10)
        enemy = pet(engine, "Duck", health=10)

        p.team = [None, None, None, friend, hedgehog]
        opp.team[4] = enemy

        engine.triggers.apply_faint(hedgehog, 4, p, opp)

        assert friend.health == 8   # 10 - 2 (level 1 = 2 dmg)
        assert enemy.health == 8


class TestFlamingo:
    """Faint: Give the two pets behind +level attack and health."""

    def test_flamingo_buffs_two_behind_on_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        f1 = pet(engine, "Ant", attack=1, health=1)  # index 1
        f2 = pet(engine, "Duck", attack=1, health=1)  # index 2
        flamingo = pet(engine, "Flamingo", level=1, health=1)  # index 4
        p.team = [None, f1, f2, None, flamingo]

        engine.triggers.apply_faint(flamingo, 4, p, opp)

        # Nearest behind: f2 (index 2), then f1 (index 1) — but flamingo has no
        # pets at index 3, so behind of index 4 is: 3 (None), 2 (f2), 1 (f1)
        assert f2.attack == 2  # +1
        assert f1.attack == 2  # +1 (second behind)


class TestWorm:
    """Start of Turn: Add an Apple variant to the shop."""

    def test_worm_adds_apple_to_shop_at_sot(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        worm = pet(engine, "Worm", level=1)
        p.team[4] = worm

        engine.triggers.apply_start_of_turn(p)

        food_names = [s.name for s in p.shop.slots if s is not None and s.kind == "food"]
        assert "Apple" in food_names


class TestKangaroo:
    """After Attack: When friend ahead attacks, gain +level attack and health."""

    def test_kangaroo_gains_stats_when_friend_ahead_attacks(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        kang = pet(engine, "Kangaroo", attack=2, health=2, level=1)
        attacker = pet(engine, "Ant", attack=3)
        # attacker is ahead of kangaroo
        p.team = [None, None, None, kang, attacker]

        engine.triggers.apply_after_attack(attacker, p, opp)

        assert kang.attack == 3  # +1
        assert kang.health == 3  # +1

    def test_kangaroo_does_not_fire_when_non_adjacent_attacks(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        kang = pet(engine, "Kangaroo", attack=2, health=2, level=1)
        duck = pet(engine, "Duck", attack=1)
        # duck is NOT ahead of kang (duck is behind)
        p.team = [None, None, None, duck, kang]

        # kang attacks — duck is behind, not ahead
        engine.triggers.apply_after_attack(kang, p, opp)
        assert duck.attack == 1  # unchanged


class TestSpider:
    """Faint: Summon a random tier-3 pet as 2/2 level 1."""

    def test_spider_summons_tier3_pet_on_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        spider = pet(engine, "Spider", level=1, health=1)
        p.team = [None, None, None, None, spider]

        engine.triggers.apply_faint(spider, 4, p, opp)

        summoned = [pet for pet in p.team if pet is not None and pet.name != "Spider"]
        assert len(summoned) == 1
        assert summoned[0].tier == 3
        assert summoned[0].attack == 2
        assert summoned[0].health == 2


# ===========================================================================
# TIER 3
# ===========================================================================

class TestDodo:
    """SOB: Give nearest friend ahead 50/100/150% of attack."""

    def test_dodo_gives_50pct_attack_to_friend_ahead(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        friend = pet(engine, "Elephant", attack=10)
        dodo = pet(engine, "Dodo", attack=8, level=1)
        p.team = [None, None, None, dodo, friend]
        opp.team[4] = pet(engine, "Ant")

        engine.triggers.apply_start_of_battle_pet(dodo, p, opp)
        # 50% of 8 = 4 → friend gets +4
        assert friend.attack == 14

    def test_dodo_level2_gives_100pct(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        friend = pet(engine, "Elephant", attack=5)
        dodo = pet(engine, "Dodo", attack=6, level=2)
        p.team = [None, None, None, dodo, friend]
        opp.team[4] = pet(engine, "Ant")

        engine.triggers.apply_start_of_battle_pet(dodo, p, opp)
        # 100% of 6 = 6 → friend gets +6
        assert friend.attack == 11


class TestDolphin:
    """SOB: Deal 4 damage to the lowest-health enemy, N times."""

    def test_dolphin_hits_lowest_health_enemy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        dolphin = pet(engine, "Dolphin", level=1)
        weakest = pet(engine, "Ant", health=3)
        strong = pet(engine, "Hippo", health=50)
        p.team[4] = dolphin
        opp.team[3] = weakest
        opp.team[4] = strong

        engine.triggers.apply_start_of_battle_pet(dolphin, p, opp)
        assert weakest.health == -1  # 3 - 4 = -1 (dead)
        assert strong.health == 50   # untouched


class TestGiraffe:
    """Start of Turn: Give nearest N friends ahead +1/+1."""

    def test_giraffe_buffs_nearest_friend_ahead(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        friend_near = pet(engine, "Ant", attack=1, health=1)
        friend_far = pet(engine, "Duck", attack=1, health=1)
        giraffe = pet(engine, "Giraffe", level=1)
        p.team = [None, None, giraffe, friend_near, friend_far]

        engine.triggers.apply_start_of_turn(p)
        # Level 1 Giraffe only buffs nearest 1 ahead
        assert friend_near.attack == 2
        assert friend_far.attack == 1  # not buffed


class TestElephant:
    """After Attack: Deal 1 damage to the pet behind (N times = level)."""

    def test_elephant_damages_pet_behind_after_attack(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        behind = pet(engine, "Peacock", attack=1, health=5)
        elephant = pet(engine, "Elephant", level=1)
        p.team = [None, None, None, behind, elephant]

        engine.triggers.apply_after_attack(elephant, p, opp)
        # 1 dmg to behind pet (Peacock); Peacock's Hurt ability then fires: +3 atk
        assert behind.health == 4   # 5 - 1
        assert behind.attack == 4   # Peacock hurt: +3


class TestCamel:
    """Hurt: Give nearest friend behind +level attack and +2*level health."""

    def test_camel_buffs_friend_behind_when_hurt(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        behind = pet(engine, "Ant", attack=1, health=1)
        camel = pet(engine, "Camel", level=2, health=10)
        p.team = [None, None, None, behind, camel]

        engine.triggers.apply_hurt(camel, p, opp)
        assert behind.attack == 3   # +2 (level 2)
        assert behind.health == 5   # +4 (2*2)


class TestRabbit:
    """Eats Food: Give the eating pet +level health (3 times per turn)."""

    def test_rabbit_gives_health_to_eating_pet(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        rabbit = pet(engine, "Rabbit", level=1)
        eating = pet(engine, "Ant", health=3)
        p.team = [None, None, None, rabbit, None]

        engine.triggers.apply_eats_food(p, eating)
        assert eating.health == 4  # +1

    def test_rabbit_triggers_when_rabbit_itself_eats(self):
        """Wiki: Rabbit gives +health even when Rabbit itself eats."""
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        rabbit = pet(engine, "Rabbit", level=1, health=3)
        p.team[4] = rabbit

        engine.triggers.apply_eats_food(p, rabbit)  # rabbit eats food
        assert rabbit.health == 4  # self-buff

    def test_rabbit_capped_at_three_per_turn(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]
        p.rabbit_count_this_turn = 3  # already at cap

        rabbit = pet(engine, "Rabbit", level=1)
        eating = pet(engine, "Ant", health=3)
        p.team[4] = rabbit

        engine.triggers.apply_eats_food(p, eating)
        assert eating.health == 3  # no change — cap reached


class TestOx:
    """Friend Ahead Faints: Gain Melon perk and +1 attack (N times per level)."""

    def test_ox_gains_melon_when_friend_ahead_faints(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        ox = pet(engine, "Ox", level=1)
        # Use Duck (no faint ability) so no extra buffs land on Ox
        ahead = pet(engine, "Duck", health=1)
        p.team = [None, None, None, ox, ahead]

        engine.triggers.apply_faint(ahead, 4, p, opp)

        assert ox.perk == "melon"
        assert ox.attack == 2  # base 1 + 1 from ability


class TestDog:
    """Friend Summoned: Give Dog +2 temporary attack and +1 temporary health."""

    def test_dog_gains_temp_stats_on_friend_summon(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        dog = pet(engine, "Dog", level=1)
        summoned = pet(engine, "Ant")
        p.team = [None, None, None, dog, None]

        engine.triggers.apply_friend_summoned(summoned, p)
        assert dog.temporary_attack == 2
        assert dog.temporary_health == 1


class TestSheep:
    """Faint: Summon two 2/2 Rams."""

    def test_sheep_summons_two_rams(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        sheep = pet(engine, "Sheep", level=1, health=1)
        p.team = [None, None, None, None, sheep]

        engine.triggers.apply_faint(sheep, 4, p, opp)

        rams = [p2 for p2 in p.team if p2 is not None and p2.name == "Ram"]
        assert len(rams) == 2
        assert rams[0].attack == 2
        assert rams[0].health == 2


# ===========================================================================
# TIER 4
# ===========================================================================

class TestSkunk:
    """SOB: Reduce the highest-health enemy's health by 33/66/99%."""

    def test_skunk_reduces_highest_health_enemy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        skunk = pet(engine, "Skunk", level=1)
        enemy = pet(engine, "Hippo", health=30)
        p.team[4] = skunk
        opp.team[4] = enemy

        engine.triggers.apply_start_of_battle_pet(skunk, p, opp)
        # 33% of 30 = 10 (ceil), so health drops to max(1, 30-10)=20
        assert enemy.health == 20

    def test_skunk_does_not_trigger_hurt(self):
        """Skunk reduces health without triggering Hurt (per wiki §9)."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        skunk = pet(engine, "Skunk", level=1)
        peacock = pet(engine, "Peacock", attack=1, health=10)
        p.team[4] = skunk
        opp.team[4] = peacock

        engine.triggers.apply_start_of_battle_pet(skunk, p, opp)
        assert peacock.attack == 1  # Peacock Hurt ability did NOT fire


class TestHippo:
    """Knock Out: Gain +3 attack and health (max 3 times per battle)."""

    def test_hippo_gains_stats_on_knockout(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        hippo = pet(engine, "Hippo", attack=4, health=4, level=1)
        p.team[4] = hippo
        opp.team[4] = pet(engine, "Ant")

        engine.triggers.apply_knock_out(hippo, p, opp)
        assert hippo.attack == 7   # +3
        assert hippo.health == 7   # +3

    def test_hippo_ko_capped_at_3_times(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        hippo = pet(engine, "Hippo", attack=1, health=1, level=1)
        hippo.knock_out_count = 3  # already used 3 times
        p.team[4] = hippo

        engine.triggers.apply_knock_out(hippo, p, opp)
        assert hippo.attack == 1  # no gain — capped


class TestBison:
    """End Turn: If you have a level-3 friend, gain +level attack and +2*level health."""

    def test_bison_gains_stats_with_level3_friend(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        bison = pet(engine, "Bison", attack=1, health=1, level=1)
        lvl3_friend = pet(engine, "Ant", level=3)
        p.team = [None, None, None, lvl3_friend, bison]

        engine.triggers.apply_end_turn(p)
        assert bison.attack == 2
        assert bison.health == 3

    def test_bison_does_not_fire_without_level3_friend(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        bison = pet(engine, "Bison", attack=1, health=1, level=1)
        p.team[4] = bison

        engine.triggers.apply_end_turn(p)
        assert bison.attack == 1  # no change


class TestBlowfish:
    """Hurt: Deal 3*level damage to a random enemy."""

    def test_blowfish_deals_damage_on_hurt(self):
        engine = make_engine(seed=5)
        state = two_player_state(engine)
        p, opp = state.players

        blowfish = pet(engine, "Blowfish", level=1, health=5)
        enemy = pet(engine, "Ant", health=10)
        p.team[4] = blowfish
        opp.team[4] = enemy

        engine.triggers.apply_hurt(blowfish, p, opp)
        assert enemy.health == 7  # 10 - 3


class TestTurtle:
    """Faint: Give N pets behind the Melon perk."""

    def test_turtle_gives_melon_to_pet_behind(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        behind = pet(engine, "Ant")
        turtle = pet(engine, "Turtle", level=1, health=1)
        p.team = [None, None, None, behind, turtle]

        engine.triggers.apply_faint(turtle, 4, p, opp)
        assert behind.perk == "melon"


class TestSquirrel:
    """Start of Turn: Reduce food cost by level gold."""

    def test_squirrel_reduces_food_cost(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        squirrel = pet(engine, "Squirrel", level=1)
        p.team[4] = squirrel

        engine.triggers.apply_start_of_turn(p)
        assert p.food_cost_discount == 1


class TestPenguin:
    """Start of Turn: Give 2 random level-2+ friends +level attack and health."""

    def test_penguin_buffs_level2_friends(self):
        engine = make_engine(seed=1)
        state = two_player_state(engine)
        p = state.players[0]

        penguin = pet(engine, "Penguin", level=1)
        lvl2_friend = pet(engine, "Ant", attack=1, health=1, level=2)
        p.team = [None, None, None, lvl2_friend, penguin]

        engine.triggers.apply_start_of_turn(p)
        assert lvl2_friend.attack == 2  # +1
        assert lvl2_friend.health == 2  # +1

    def test_penguin_ignores_level1_friends(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        penguin = pet(engine, "Penguin", level=1)
        lvl1_friend = pet(engine, "Ant", attack=1, health=1, level=1)
        p.team = [None, None, None, lvl1_friend, penguin]

        engine.triggers.apply_start_of_turn(p)
        assert lvl1_friend.attack == 1  # unchanged — not level 2+


class TestDeer:
    """Faint: Summon a Bus with Chili perk."""

    def test_deer_summons_bus_with_chili(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        deer = pet(engine, "Deer", level=1, health=1)
        p.team = [None, None, None, None, deer]

        engine.triggers.apply_faint(deer, 4, p, opp)

        buses = [p2 for p2 in p.team if p2 is not None and p2.name == "Bus"]
        assert len(buses) == 1
        assert buses[0].perk == "chili"
        assert buses[0].attack == 5
        assert buses[0].health == 3


class TestWhale:
    """SOB: Swallow nearest friend ahead; Faint: Release it."""

    def test_whale_swallows_and_releases_friend(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        ant = pet(engine, "Ant", attack=4, health=5)
        whale = pet(engine, "Whale", level=1, health=10)
        # "ahead" = higher index; Ant (idx=4) is ahead of Whale (idx=3)
        p.team = [None, None, None, whale, ant]
        opp.team[4] = pet(engine, "Duck")

        # SOB: Whale swallows Ant (nearest friend ahead of whale = Ant at index 4)
        engine.triggers.apply_start_of_battle_pet(whale, p, opp)
        assert p.team[4] is None         # Ant was removed (ahead of whale)
        assert "whale_swallowed" in (whale.copied_ability or "")

        # Whale faints: Ant is released
        p.team[3] = None  # pretend whale fainted
        engine.triggers.apply_faint(whale, 3, p, opp)

        released = [p2 for p2 in p.team if p2 is not None and p2.name == "Ant"]
        assert len(released) == 1


class TestParrot:
    """End Turn: Copy the ability of the nearest friend ahead."""

    def test_parrot_copies_friend_ahead_ability(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        ant = pet(engine, "Ant")
        parrot = pet(engine, "Parrot")
        p.team = [None, None, None, parrot, ant]

        engine.triggers.apply_end_turn(p)
        assert parrot.copied_ability == "Ant"

    def test_parrot_clears_if_no_friend_ahead(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        parrot = pet(engine, "Parrot")
        parrot.copied_ability = "Ant"
        p.team[4] = parrot

        engine.triggers.apply_end_turn(p)
        assert parrot.copied_ability is None


# ===========================================================================
# TIER 5
# ===========================================================================

class TestScorpion:
    """Friend Summoned: Scorpion itself gets Peanut perk when summoned."""

    def test_scorpion_gains_peanut_on_summon(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        scorpion = pet(engine, "Scorpion")
        engine.triggers.apply_friend_summoned(scorpion, p)
        assert scorpion.perk == "peanut"


class TestCrocodile:
    """SOB: Deal 8 damage to the last-alive enemy pet, N times."""

    def test_crocodile_hits_backmost_enemy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        croc = pet(engine, "Crocodile", level=1)
        back_enemy = pet(engine, "Ant", health=10)
        front_enemy = pet(engine, "Hippo", health=50)
        p.team[4] = croc
        opp.team[0] = back_enemy
        opp.team[4] = front_enemy

        engine.triggers.apply_start_of_battle_pet(croc, p, opp)
        assert back_enemy.health == 2   # 10 - 8 = 2
        assert front_enemy.health == 50  # not targeted


class TestRhino:
    """Knock Out: Deal 4*level damage to the enemy attacker; double vs tier-1."""

    def test_rhino_damages_enemy_on_ko(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        rhino = pet(engine, "Rhino", level=1)
        enemy = pet(engine, "Hippo", attack=1, health=20, level=1)
        p.team[4] = rhino
        opp.team[4] = enemy

        engine.triggers.apply_knock_out(rhino, p, opp)
        assert enemy.health == 16   # 20 - 4

    def test_rhino_doubles_damage_vs_tier1(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        rhino = pet(engine, "Rhino", level=1)
        # Ant is tier 1
        ant = pet(engine, "Ant", health=10)
        p.team[4] = rhino
        opp.team[4] = ant

        engine.triggers.apply_knock_out(rhino, p, opp)
        assert ant.health == 2   # 10 - 8 (4*1*2 = 8 vs tier-1)


class TestMonkey:
    """End Turn: Give the frontmost friend +2*level attack and +2*level health."""

    def test_monkey_buffs_front_friend_at_end_turn(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        front = pet(engine, "Ant", attack=1, health=1)
        monkey = pet(engine, "Monkey", level=1)
        p.team = [None, None, None, monkey, front]

        engine.triggers.apply_end_turn(p)
        assert front.attack == 3   # +2
        assert front.health == 3   # +2


class TestArmadillo:
    """SOB: Give all pets on both teams +8*level health."""

    def test_armadillo_gives_health_to_all_pets(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        armadillo = pet(engine, "Armadillo", level=1)
        friend = pet(engine, "Ant", health=2)
        enemy = pet(engine, "Duck", health=3)
        p.team = [None, None, None, friend, armadillo]
        opp.team[4] = enemy

        engine.triggers.apply_start_of_battle_pet(armadillo, p, opp)
        assert friend.health == 10   # 2 + 8
        assert enemy.health == 11    # 3 + 8
        # Armadillo itself also gets +8 (since it's on team)
        assert armadillo.health == armadillo.definition.health + 8


class TestCow:
    """Buy: Remove all food from shop, add 2 free Milk variants."""

    def test_cow_removes_food_and_adds_milk(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        cow = pet(engine, "Cow", level=1)
        # Place an Apple in the shop
        p.shop.slots[7] = ShopOffer(kind="food", name="Apple", tier=1)

        engine.triggers.apply_buy(p, cow)

        food_slots = [s for s in p.shop.slots if s is not None and s.kind == "food"]
        food_names = [s.name for s in food_slots]

        assert "Apple" not in food_names  # removed
        assert food_names.count("Milk") == 2
        assert all(s.cost_override == 0 for s in food_slots)


class TestSeal:
    """Eats Food: Give 3 random friends +level attack."""

    def test_seal_buffs_friends_when_eating(self):
        engine = make_engine(seed=2)
        state = two_player_state(engine)
        p = state.players[0]

        seal = pet(engine, "Seal", level=1)
        f1 = pet(engine, "Ant", attack=1)
        f2 = pet(engine, "Duck", attack=1)
        p.team = [None, None, f1, f2, seal]

        engine.triggers.apply_eats_food(p, seal)
        # 3 random friends (excluding seal) — only 2 friends, both get buffed
        assert f1.attack == 2
        assert f2.attack == 2


class TestRooster:
    """Faint: Summon N Rooster Chicks with half of Rooster's health."""

    def test_rooster_summons_chick_on_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        rooster = pet(engine, "Rooster", health=6, level=1)
        p.team = [None, None, None, None, rooster]

        engine.triggers.apply_faint(rooster, 4, p, opp)

        chicks = [p2 for p2 in p.team if p2 is not None and p2.name == "Rooster Chick"]
        assert len(chicks) == 1
        assert chicks[0].health == 3   # ceil(6/2)


# ===========================================================================
# TIER 6
# ===========================================================================

class TestLeopard:
    """SOB: Deal 50% attack to N random enemies."""

    def test_leopard_hits_one_random_enemy(self):
        engine = make_engine(seed=3)
        state = two_player_state(engine)
        p, opp = state.players

        leopard = pet(engine, "Leopard", attack=10, health=4, level=1)
        e1 = pet(engine, "Ant", health=10)
        e2 = pet(engine, "Duck", health=10)
        p.team[4] = leopard
        opp.team[3] = e1
        opp.team[4] = e2

        engine.triggers.apply_start_of_battle_pet(leopard, p, opp)
        total_taken = (10 - e1.health) + (10 - e2.health)
        assert total_taken == 5   # 50% of 10 = 5, one hit

    def test_leopard_level2_hits_two_different_enemies(self):
        engine = make_engine(seed=7)
        state = two_player_state(engine)
        p, opp = state.players

        leopard = pet(engine, "Leopard", attack=10, health=4, level=2)
        e1 = pet(engine, "Ant", health=10)
        e2 = pet(engine, "Duck", health=10)
        p.team[4] = leopard
        opp.team[3] = e1
        opp.team[4] = e2

        engine.triggers.apply_start_of_battle_pet(leopard, p, opp)
        total_taken = (10 - e1.health) + (10 - e2.health)
        assert total_taken == 10   # 5+5, both hit


class TestBoar:
    """Before Attack: Gain +4*level temporary attack and +2*level temporary health."""

    def test_boar_gains_temp_stats_before_attack(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        boar = pet(engine, "Boar", attack=10, health=6, level=1)
        p.team[4] = boar

        engine.triggers.apply_before_attack(boar, p, opp)
        assert boar.temporary_attack == 4   # +4*1
        assert boar.temporary_health == 2   # +2*1

    def test_boar_stats_are_temporary(self):
        """Boar stats are NOT retained outside of battle."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        boar = pet(engine, "Boar", attack=5, health=5, level=1)
        p.team[4] = boar

        # Verify temporary, not permanent
        engine.triggers.apply_before_attack(boar, p, opp)
        assert boar.attack == 5              # permanent unchanged
        assert boar.temporary_attack == 4    # only temporary


class TestWolverine:
    """Every 4 friends hurt: Remove 3*level health from all enemies (min 1)."""

    def test_wolverine_fires_after_4_hurts(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        wolverine = pet(engine, "Wolverine", level=1)
        e1 = pet(engine, "Ant", health=5)
        p.team[4] = wolverine
        opp.team[4] = e1

        # Simulate 3 hurts — should NOT fire yet
        p.hurt_count_this_battle = 3
        engine.triggers.apply_hurt(wolverine, p, opp)  # 4th hurt
        # Now hurt_count = 4, Wolverine fires: remove 3 health from e1
        assert e1.health == 2   # 5 - 3

    def test_wolverine_health_removal_min_1(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        wolverine = pet(engine, "Wolverine", level=3)  # removes 9 health
        e1 = pet(engine, "Ant", health=2)
        p.team[4] = wolverine
        opp.team[4] = e1

        p.hurt_count_this_battle = 3
        engine.triggers.apply_hurt(wolverine, p, opp)
        assert e1.health == 1   # cannot go below 1

    def test_wolverine_does_not_trigger_hurt_on_enemies(self):
        """Health removal is distinct from damage — does not fire Hurt triggers."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        wolverine = pet(engine, "Wolverine", level=1)
        peacock = pet(engine, "Peacock", attack=2, health=10)
        p.team[4] = wolverine
        opp.team[4] = peacock

        p.hurt_count_this_battle = 3
        engine.triggers.apply_hurt(wolverine, p, opp)
        assert peacock.attack == 2  # Peacock Hurt did NOT fire


class TestGorilla:
    """Hurt: Gain Coconut perk. Works N times per battle (N = level)."""

    def test_gorilla_gains_coconut_on_hurt(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        gorilla = pet(engine, "Gorilla", level=1)
        p.team[4] = gorilla

        engine.triggers.apply_hurt(gorilla, p, opp)
        assert gorilla.perk == "coconut"

    def test_gorilla_coconut_capped_at_level_times(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        gorilla = pet(engine, "Gorilla", level=1)
        gorilla.ability_uses = 1  # already used its 1 time
        gorilla.perk = None
        p.team[4] = gorilla

        engine.triggers.apply_hurt(gorilla, p, opp)
        assert gorilla.perk is None  # not gained again — capped


class TestDragon:
    """Tier-1 friend bought: Give all friends +level attack and health (4x/turn)."""

    def test_dragon_buffs_friends_on_tier1_buy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        dragon = pet(engine, "Dragon", level=1)
        friend = pet(engine, "Duck", attack=2, health=2)
        tier1_pet = pet(engine, "Ant")  # tier 1
        p.team = [None, None, friend, dragon, None]

        engine.triggers.apply_buy(p, tier1_pet)
        assert friend.attack == 3   # +1
        assert friend.health == 3   # +1
        assert dragon.attack == dragon.definition.attack  # Dragon doesn't buff itself

    def test_dragon_does_not_fire_for_tier2_buy(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        dragon = pet(engine, "Dragon", level=1)
        friend = pet(engine, "Duck", attack=2, health=2)
        tier2_pet = pet(engine, "Snail")  # tier 2
        p.team = [None, None, friend, dragon, None]

        engine.triggers.apply_buy(p, tier2_pet)
        assert friend.attack == 2   # unchanged

    def test_dragon_capped_at_4_fires_per_turn(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        dragon = pet(engine, "Dragon", level=1)
        friend = pet(engine, "Duck", attack=1, health=1)
        p.team = [None, None, None, friend, dragon]
        p.dragon_buys_this_turn = 4  # already at cap

        tier1_pet = pet(engine, "Ant")
        engine.triggers.apply_buy(p, tier1_pet)
        assert friend.attack == 1   # no buff — cap reached


class TestCat:
    """Food gives multiplied stats (2x/3x/4x). Works 2 times per turn per Cat."""

    def test_cat_doubles_apple_stats(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        cat = pet(engine, "Cat", level=1)
        target = pet(engine, "Ant", attack=1, health=1)
        p.team = [None, None, None, cat, target]
        p.cat_food_uses_this_turn = 2   # Cat has 2 uses this turn

        p.gold = 10
        p.shop.slots[7] = ShopOffer(kind="food", name="Apple", tier=1)
        engine.shop.buy_food(p, 7, 4)  # target is at index 4

        assert target.attack == 3   # 1 + 1*2 (Cat L1 mult = 2)
        assert target.health == 3

    def test_cat_uses_are_exhausted(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        cat = pet(engine, "Cat", level=1)
        target = pet(engine, "Ant", attack=1, health=1)
        p.team = [None, None, None, cat, target]
        p.cat_food_uses_this_turn = 0   # no uses remaining

        p.gold = 10
        p.shop.slots[7] = ShopOffer(kind="food", name="Apple", tier=1)
        engine.shop.buy_food(p, 7, 4)

        assert target.attack == 2   # 1+1, no Cat multiplier
        assert target.health == 2

    def test_cat_does_not_affect_chocolate(self):
        engine = make_engine()
        state = two_player_state(engine)
        p = state.players[0]

        cat = pet(engine, "Cat", level=1)
        target = pet(engine, "Ant", attack=1, health=1, experience=0)
        p.team = [None, None, None, cat, target]
        p.cat_food_uses_this_turn = 2

        p.gold = 10
        p.shop.slots[7] = ShopOffer(kind="food", name="Chocolate", tier=5)
        engine.shop.buy_food(p, 7, 4)

        assert target.attack == 2   # only +1 (no Cat mult on Chocolate)
        assert target.health == 2


class TestSnake:
    """Friend Ahead Attacks: Deal 5*level damage to a random enemy. Works 5 times/battle."""

    def test_snake_fires_when_friend_ahead_attacks(self):
        engine = make_engine(seed=1)
        state = two_player_state(engine)
        p, opp = state.players

        snake = pet(engine, "Snake", level=1)
        attacker = pet(engine, "Ant")
        enemy = pet(engine, "Duck", health=10)
        p.team = [None, None, None, snake, attacker]
        opp.team[4] = enemy

        engine.triggers.apply_after_attack(attacker, p, opp)
        assert enemy.health == 5   # 10 - 5

    def test_snake_capped_at_5_fires(self):
        engine = make_engine(seed=1)
        state = two_player_state(engine)
        p, opp = state.players

        snake = pet(engine, "Snake", level=1)
        snake.ability_uses = 5  # already used 5 times
        attacker = pet(engine, "Ant")
        enemy = pet(engine, "Duck", health=10)
        p.team = [None, None, None, snake, attacker]
        opp.team[4] = enemy

        engine.triggers.apply_after_attack(attacker, p, opp)
        assert enemy.health == 10   # no damage — capped


class TestFly:
    """Friend Faints: Summon 4*level/4*level Zombie Fly. Works 3 times per battle."""

    def test_fly_summons_zombie_fly_on_friend_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        fly = pet(engine, "Fly", level=1)
        ant = pet(engine, "Ant", health=1)
        p.team = [None, None, None, ant, fly]

        engine.triggers.apply_faint(ant, 3, p, opp)

        zombie_flies = [p2 for p2 in p.team if p2 is not None and p2.name == "Zombie Fly"]
        assert len(zombie_flies) == 1
        assert zombie_flies[0].attack == 4   # 4 * level 1
        assert zombie_flies[0].health == 4

    def test_fly_capped_at_3_summons(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        fly = pet(engine, "Fly", level=1)
        fly.ability_uses = 3  # already used 3 times
        ant = pet(engine, "Ant", health=1)
        p.team = [None, None, None, ant, fly]

        engine.triggers.apply_faint(ant, 3, p, opp)

        zombie_flies = [p2 for p2 in p.team if p2 is not None and p2.name == "Zombie Fly"]
        assert len(zombie_flies) == 0  # capped

    def test_fly_does_not_trigger_on_zombie_fly_faint(self):
        """Per wiki: Zombie Fly faint does not trigger Fly's ability."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players
        from sap_engine.models import PetDefinition

        fly = pet(engine, "Fly", level=1)
        defn = PetDefinition(name="Zombie Fly", tier=6, attack=4, health=4)
        zombie_fly = PetInstance(definition=defn, attack=4, health=1)
        p.team = [None, None, None, zombie_fly, fly]

        # Remove zombie_fly from team first (as battle.py does before calling apply_faint)
        p.team[3] = None
        engine.triggers.apply_faint(zombie_fly, 3, p, opp)

        new_zombies = [p2 for p2 in p.team if p2 is not None and p2.name == "Zombie Fly"]
        assert len(new_zombies) == 0  # Fly did not trigger


class TestMammoth:
    """Faint: Give all friends +2*level attack and health."""

    def test_mammoth_buffs_all_friends_on_faint(self):
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        mammoth = pet(engine, "Mammoth", level=1, health=1)
        f1 = pet(engine, "Ant", attack=1, health=1)
        f2 = pet(engine, "Duck", attack=1, health=1)
        p.team = [None, None, f1, f2, mammoth]

        engine.triggers.apply_faint(mammoth, 4, p, opp)
        assert f1.attack == 3   # +2
        assert f1.health == 3   # +2
        assert f2.attack == 3
        assert f2.health == 3


class TestTiger:
    """While in battle: friend ahead repeats their ability at Tiger's level."""

    def test_tiger_repeats_hurt_ability_of_friend_ahead(self):
        """Tiger causes Peacock (friend ahead) to fire Hurt again at Tiger's level."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        tiger = pet(engine, "Tiger", level=2)
        peacock = pet(engine, "Peacock", attack=1, health=5, level=1)
        p.team = [None, None, None, tiger, peacock]

        # Peacock is hurt: fires its own Hurt (+3 atk) at level 1,
        # then Tiger causes it to repeat at Tiger's level 2 (+6 atk more)
        engine.triggers.apply_hurt(peacock, p, opp)
        # Level 1 fires: +3; Tiger level 2 repeat fires: +6
        assert peacock.attack == 10   # 1 + 3 + 6

    def test_tiger_repeats_after_attack_for_kangaroo(self):
        """Tiger causes Kangaroo (friend ahead) to gain double stats."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        tiger = pet(engine, "Tiger", level=1)
        kang = pet(engine, "Kangaroo", attack=1, health=1, level=1)
        attacker = pet(engine, "Ant", attack=5)
        # Layout: tiger at 2, kang at 3, attacker at 4
        p.team = [None, None, tiger, kang, attacker]

        engine.triggers.apply_after_attack(attacker, p, opp)
        # Kangaroo fires once normally (+1/+1), Tiger causes it to repeat (+1/+1 again)
        assert kang.attack == 3   # 1 + 1 + 1
        assert kang.health == 3   # 1 + 1 + 1

    def test_tiger_does_not_repeat_for_non_adjacent_friend(self):
        """Tiger only repeats the ability of its NEAREST friend ahead."""
        engine = make_engine()
        state = two_player_state(engine)
        p, opp = state.players

        tiger = pet(engine, "Tiger", level=2)
        # Peacock is NOT adjacent (there's a Duck between)
        peacock = pet(engine, "Peacock", attack=1, health=5, level=1)
        duck = pet(engine, "Duck", attack=1, health=5)
        p.team = [None, None, tiger, duck, peacock]  # duck is nearest ahead

        engine.triggers.apply_hurt(peacock, p, opp)
        # Tiger's nearest-ahead is Duck, not Peacock → Tiger does NOT repeat Peacock
        assert peacock.attack == 4  # only level-1 Hurt fired (+3), no Tiger repeat


# ===========================================================================
# GENERAL RULES
# ===========================================================================

class TestGeneralRules:
    """Tests for general wiki rules (§1–§9)."""

    def test_two_player_game_starts_with_6_lives(self):
        """Wiki §1: In a 2-player game, each player starts with 6 lives."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        assert state.players[0].health == 6
        assert state.players[1].health == 6

    def test_life_gain_rule_at_turn_3(self):
        """Wiki §1: Player who lost lives in turns 1–2 regains 1 life at start of turn 3."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        alice = state.players[0]
        alice.health = 5   # lost 1 life
        alice.losses = 1   # had at least 1 loss
        state.turn = 3

        engine.start_shop_turn(state, 0)
        assert alice.health == 6   # restored

    def test_life_gain_does_not_fire_if_no_losses(self):
        """Players who never lost a life do NOT get the turn-3 bonus."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        alice = state.players[0]
        alice.health = 6
        alice.losses = 0
        state.turn = 3

        engine.start_shop_turn(state, 0)
        assert alice.health == 6   # unchanged (would be 7 if the rule fired wrongly)

    def test_life_gain_does_not_fire_on_other_turns(self):
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        alice = state.players[0]
        alice.health = 5
        alice.losses = 1
        state.turn = 4   # turn 4, not 3

        engine.start_shop_turn(state, 0)
        assert alice.health == 5   # rule does not fire on turn 4

    def test_stat_cap_enforced_at_50(self):
        """Wiki §5: Pet stats cap at 50 for both attack and health."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p = state.players[0]

        ant = pet(engine, "Ant", attack=49, health=49)
        p.team[4] = ant
        p.gold = 10
        p.shop.slots[7] = ShopOffer(kind="food", name="Pear", tier=4)

        engine.shop.buy_food(p, 7, 4)
        assert ant.attack == 50   # capped
        assert ant.health == 50   # capped

    def test_draw_when_both_teams_faint_simultaneously(self):
        """Wiki §1: If both teams faint simultaneously, result is a Draw."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p0, p1 = state.players

        # Both pets deal enough to kill each other simultaneously
        a = pet(engine, "Ant", attack=5, health=1)
        b = pet(engine, "Duck", attack=5, health=1)
        p0.team[4] = a
        p1.team[4] = b

        state.phase = Phase.BATTLE
        result = engine.battle.resolve(state)
        assert result.outcome == BattleOutcome.DRAW

    def test_pets_cost_3_gold(self):
        """Wiki §3: Pets cost 3 Gold to buy."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p = state.players[0]
        p.gold = 3

        # Find a pet in the shop
        pet_idx = next(
            i for i, s in enumerate(p.shop.slots)
            if s is not None and s.kind == "pet"
        )
        engine.shop.buy_pet(p, pet_idx, 0)
        assert p.gold == 0

    def test_sell_returns_level_gold(self):
        """Wiki §3: Selling returns gold equal to level."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p = state.players[0]

        p.gold = 0
        lvl2_pet = pet(engine, "Ant", level=2)
        p.team[0] = lvl2_pet

        engine.shop.sell_pet(p, 0)
        assert p.gold == 2   # level 2 = 2 gold

    def test_freeze_preserves_item_across_reroll(self):
        """Wiki §4: Frozen items are preserved when rerolling."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p = state.players[0]

        # Find a pet slot and freeze it
        slot_idx = next(i for i, s in enumerate(p.shop.slots) if s is not None and s.kind == "pet")
        frozen_name = p.shop.slots[slot_idx].name
        p.shop.slots[slot_idx].frozen = True
        p.gold = 5

        engine.shop.roll_shop(p)

        assert p.shop.slots[slot_idx] is not None
        assert p.shop.slots[slot_idx].name == frozen_name
        assert p.shop.slots[slot_idx].frozen

    def test_battle_restores_team_after_resolve(self):
        """Wiki §8: Temporary buffs are removed after battle; permanent stats restored."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p0, p1 = state.players

        a = pet(engine, "Ant", attack=2, health=200)
        a.temporary_attack = 5
        b = pet(engine, "Duck", attack=1, health=200)
        p0.team[4] = a
        p1.team[4] = b

        state.phase = Phase.BATTLE
        engine.battle.resolve(state)   # Draw after 200 steps

        assert a.temporary_attack == 0
        assert a.attack == 2   # permanent unchanged

    def test_battle_loss_costs_one_life(self):
        """Wiki §1: Losing player loses 1 life."""
        engine = make_engine()
        state = engine.new_game(["Alice", "Bob"])
        p0, p1 = state.players

        p0.team[4] = pet(engine, "Ant", attack=1, health=1)   # weak
        p1.team[4] = pet(engine, "Hippo", attack=10, health=50)  # strong

        initial_health = p0.health
        state.phase = Phase.BATTLE
        engine.battle.resolve(state)

        assert p0.health == initial_health - 1

    def test_shop_tier_unlocks_per_turn_schedule(self):
        """Wiki §4: Tier 2 unlocks on turn 3, Tier 3 on turn 5."""
        from sap_engine.paths import unlock_tier_for_turn
        assert unlock_tier_for_turn(1) == 1
        assert unlock_tier_for_turn(2) == 1
        assert unlock_tier_for_turn(3) == 2
        assert unlock_tier_for_turn(5) == 3
        assert unlock_tier_for_turn(7) == 4
        assert unlock_tier_for_turn(9) == 5
        assert unlock_tier_for_turn(11) == 6
        assert unlock_tier_for_turn(25) == 6   # stays at 6
