from sap_engine.ui.animations import AnimationTracker, HIGHLIGHT_FRAMES, PetSnapshot


def test_replay_step_change_ignores_slot_shift_without_stat_change() -> None:
    tracker = AnimationTracker()
    previous = {
        "p0_team": [
            None,
            None,
            None,
            {"uid": 101, "name": "Ant", "attack": 2, "health": 1, "temporary_attack": 0, "temporary_health": 0, "level": 1, "experience": 0},
            {"uid": 102, "name": "Beaver", "attack": 3, "health": 3, "temporary_attack": 0, "temporary_health": 0, "level": 1, "experience": 0},
        ],
        "p1_team": [None] * 5,
    }
    current = {
        "p0_team": [
            None,
            None,
            None,
            None,
            {"uid": 101, "name": "Ant", "attack": 2, "health": 1, "temporary_attack": 0, "temporary_health": 0, "level": 1, "experience": 0},
        ],
        "p1_team": [None] * 5,
    }

    tracker.on_replay_step_changed(current, previous)

    assert tracker.replay_fx(0, 101) is None


def test_replay_step_change_highlights_stat_change_after_slot_shift() -> None:
    tracker = AnimationTracker()
    previous = {
        "p0_team": [
            None,
            None,
            None,
            None,
            {"uid": 201, "name": "Ant", "attack": 2, "health": 3, "temporary_attack": 0, "temporary_health": 0, "level": 1, "experience": 0},
        ],
        "p1_team": [None] * 5,
    }
    current = {
        "p0_team": [
            None,
            None,
            None,
            {"uid": 201, "name": "Ant", "attack": 2, "health": 1, "temporary_attack": 0, "temporary_health": 0, "level": 1, "experience": 0},
        ],
        "p1_team": [None] * 5,
    }

    tracker.on_replay_step_changed(current, previous)

    fx = tracker.replay_fx(0, 201)
    assert fx is not None
    assert fx.highlight_health == HIGHLIGHT_FRAMES
    assert fx.highlight_attack == 0


def test_replay_step_change_highlights_perk_loss() -> None:
    tracker = AnimationTracker()
    previous = {
        "p0_team": [
            None,
            None,
            None,
            None,
            {
                "uid": 301,
                "name": "Ant",
                "attack": 2,
                "health": 2,
                "temporary_attack": 0,
                "temporary_health": 0,
                "level": 1,
                "experience": 0,
                "perk": "melon",
                "perk_uses": 0,
            },
        ],
        "p1_team": [None] * 5,
    }
    current = {
        "p0_team": [
            None,
            None,
            None,
            None,
            {
                "uid": 301,
                "name": "Ant",
                "attack": 2,
                "health": 2,
                "temporary_attack": 0,
                "temporary_health": 0,
                "level": 1,
                "experience": 0,
                "perk": None,
                "perk_uses": 0,
            },
        ],
        "p1_team": [None] * 5,
    }

    tracker.on_replay_step_changed(current, previous)

    fx = tracker.replay_fx(0, 301)
    assert fx is not None
    assert fx.highlight_perk == HIGHLIGHT_FRAMES
    assert fx.perk_lost == "melon"
    assert fx.perk_lost_frames == HIGHLIGHT_FRAMES


def test_record_changes_detects_shop_perk_gain() -> None:
    tracker = AnimationTracker()
    before = {
        1: PetSnapshot(
            attack=2,
            health=2,
            temporary_attack=0,
            temporary_health=0,
            experience=0,
            level=1,
            perk=None,
            perk_uses=0,
        )
    }
    after = {
        1: PetSnapshot(
            attack=2,
            health=2,
            temporary_attack=0,
            temporary_health=0,
            experience=0,
            level=1,
            perk="garlic",
            perk_uses=0,
        )
    }
    tracker.record_changes(before, after)
    stored = tracker._fx[1]
    assert stored.highlight_perk == HIGHLIGHT_FRAMES
    assert stored.perk_lost is None
