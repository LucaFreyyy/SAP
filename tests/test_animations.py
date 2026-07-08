from sap_engine.ui.animations import AnimationTracker, HIGHLIGHT_FRAMES


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
