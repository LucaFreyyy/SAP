from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("SDL_VIDEO_CENTERED", "1")

import pygame

from ..cpu.game import CpuGameEngine
from ..models import GameState, Phase, PlayerState, ShopOffer
from ..registry import load_registry
from ..rng import SeededRNG
from .animations import AnimationTracker, HIGHLIGHT_FRAMES, PetVisualFX


WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
BACKGROUND = (14, 18, 28)
PANEL = (24, 31, 47)
PANEL_ALT = (31, 41, 61)
TEXT = (235, 240, 255)
MUTED = (150, 160, 185)
ACCENT = (100, 200, 255)
GOLD = (235, 198, 77)
SELECT = (80, 220, 120)
FREEZE = (100, 200, 255)
TIER_UP = (255, 180, 80)
STAT_HIGHLIGHT = (255, 255, 80)
STAT_HIGHLIGHT_BG = (255, 200, 40)
GOLDEN_BORDER = (255, 210, 60)
PANEL_BORDER = (60, 70, 92)
PERK_HIGHLIGHT = (255, 255, 80)
PERK_LOST = (255, 90, 90)

# Maps perk id -> (icon kind, display name)
PERK_ICON_MAP: dict[str, tuple[str, str]] = {
    "honey": ("foods", "Honey"),
    "melon": ("foods", "Melon"),
    "garlic": ("foods", "Garlic"),
    "meat_bone": ("foods", "Meat Bone"),
    "steak": ("foods", "Steak"),
    "chili": ("foods", "Chili"),
    "mushroom": ("foods", "Mushroom"),
    "cake": ("foods", "Cake"),
    "bread": ("foods", "Bread"),
    "peanut": ("tokens", "Peanut"),
    "coconut": ("tokens", "Coconut"),
}


@dataclass(slots=True)
class Selection:
    kind: str | None = None
    index: int | None = None


@dataclass(slots=True)
class PendingMergeChoice:
    team_index: int
    source: str = "team"  # "team" or "shop"
    from_index: int | None = None
    shop_index: int | None = None


class GameMode:
    HUMAN_VS_HUMAN = "Human vs Human"
    HUMAN_VS_AI = "Human vs AI"
    AI_VS_AI = "AI vs AI"


class GameUI:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("SAP CPU Engine")
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 20)
        self.big_font = pygame.font.SysFont("arial", 30, bold=True)
        self.registry = load_registry()
        self.engine = CpuGameEngine(self.registry, SeededRNG(42))
        self._wire_ability_listener()
        self.state: GameState | None = None
        self.selection = Selection()
        self.status = "Select a mode to start."
        self.icon_cache: dict[tuple[str, str], pygame.Surface] = {}
        self.mode = None
        self.player_modes: list[str] = []
        self.pending_battle_frames = 0
        self.battle_replay_mode = False
        self.pending_merge: PendingMergeChoice | None = None
        self.animations = AnimationTracker()
        self._last_replay_step: int | None = None
        self.mode_buttons = {
            GameMode.HUMAN_VS_HUMAN: pygame.Rect(440, 300, 520, 56),
            GameMode.HUMAN_VS_AI: pygame.Rect(440, 380, 520, 56),
            GameMode.AI_VS_AI: pygame.Rect(440, 460, 520, 56),
        }

    def run(self) -> None:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.handle_click(event.pos)
                    elif event.button == 3:
                        self.handle_right_click(event.pos)

            self._update_ai_and_battle()
            self.animations.tick()

            self.draw()
            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()

    def handle_click(self, position: tuple[int, int]) -> None:
        if self.state is None:
            for mode, rect in self.mode_buttons.items():
                if rect.collidepoint(position):
                    self._start_mode(mode)
                    return
            return

        if self.pending_battle_frames > 0:
            return

        if self.pending_merge is not None:
            if self._handle_merge_dialog_click(position):
                return

        # Handle battle replay controls
        if self.battle_replay_mode and self.state.phase == Phase.BATTLE:
            snapshot = self.state.battle
            if self._hit_button(position, self._battle_back_rect()):
                if snapshot.current_step > 0:
                    snapshot.current_step -= 1
                    self._last_replay_step = None
                return
            if self._hit_button(position, self._battle_forward_rect()):
                if snapshot.current_step < len(snapshot.step_history) - 1:
                    snapshot.current_step += 1
                    self._last_replay_step = None
                return
            if self._hit_button(position, self._battle_next_turn_rect()):
                if snapshot.current_step == len(snapshot.step_history) - 1:
                    self._advance_to_next_turn()
                return
            return

        if self._hit_button(position, self._end_turn_rect()):
            result = self.engine.end_shop_turn(self.state)
            if result.battle_pending:
                self.pending_battle_frames = 18
                self.status = "Battle phase..."
            else:
                self.status = f"Turn passed to {self.state.current_player().name}."
            self.selection = Selection()
            return

        if self._hit_button(position, self._roll_rect()):
            before = self.animations.snapshot_player(self.state.current_player())
            result = self.engine.shop.roll_shop(self.state.current_player())
            after = self.animations.snapshot_player(self.state.current_player())
            self.animations.record_changes(before, after)
            self.status = result.message
            return

        if self._hit_button(position, self._sell_rect()):
            if self.selection.kind == "team" and self.selection.index is not None:
                before = self.animations.snapshot_player(self.state.current_player())
                result = self.engine.shop.sell_pet(self.state.current_player(), self.selection.index)
                after = self.animations.snapshot_player(self.state.current_player())
                self.animations.record_changes(before, after)
                self.status = result.message
            self.selection = Selection()
            return

        shop_index = self._hit_shop_slot(position)
        team_index = self._hit_team_slot(position)

        if shop_index is not None:
            self._handle_shop_click(shop_index)
            return
        if team_index is not None:
            self._handle_team_click(team_index)
            return

        self.selection = Selection()

    def handle_right_click(self, position: tuple[int, int]) -> None:
        if self.state is None:
            return
        if self.pending_battle_frames > 0:
            return
        shop_index = self._hit_shop_slot(position)
        if shop_index is not None:
            result = self.engine.shop.freeze_slot(self.state.current_player(), shop_index)
            self.status = result.message

    def _advance_to_next_turn(self) -> None:
        """Advance to the next shop turn after battle replay."""
        self.battle_replay_mode = False
        result = self.engine.start_next_round(self.state)
        self.status = f"Round {self.state.turn} started."
        self.selection = Selection()

    def _wire_ability_listener(self) -> None:
        def listener(pet, player):
            self.animations.on_ability_trigger(pet, player)

        self.engine.triggers.ability_listener = listener

    def _record_shop_result(self, before, after, result) -> None:
        self.animations.record_changes(before, after)
        if result.levelled_up and self.state is not None:
            player = self.state.current_player()
            for pet in player.team:
                if pet is not None and pet.name == result.level_up_pet:
                    self.animations.note_xp_gain(pet, leveled_up=True)
                    break

    def _merge_dialog_rect(self) -> pygame.Rect:
        return pygame.Rect(420, 330, 560, 220)

    def _merge_button_rect(self) -> pygame.Rect:
        return pygame.Rect(470, 470, 180, 48)

    def _swap_button_rect(self) -> pygame.Rect:
        return pygame.Rect(670, 470, 180, 48)

    def _cancel_merge_rect(self) -> pygame.Rect:
        return pygame.Rect(870, 470, 80, 48)

    def _draw_merge_dialog(self) -> None:
        if self.pending_merge is None or self.state is None:
            return
        overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.screen.blit(overlay, (0, 0))
        dialog = self._merge_dialog_rect()
        pygame.draw.rect(self.screen, PANEL, dialog, border_radius=18)
        pygame.draw.rect(self.screen, SELECT, dialog, 2, border_radius=18)
        player = self.state.current_player()
        if self.pending_merge.source == "shop":
            offer = player.shop.slots[self.pending_merge.shop_index or 0]
            pet_name = offer.name if offer is not None else "pet"
            title = self.big_font.render("Buy Same Pet", True, TEXT)
            self.screen.blit(title, (dialog.x + 24, dialog.y + 24))
            message = self.font.render(
                f"Merge {pet_name} onto slot {self.pending_merge.team_index + 1}, or place in an empty slot?",
                True,
                MUTED,
            )
            self.screen.blit(message, (dialog.x + 24, dialog.y + 78))
            action_labels = (
                (self._merge_button_rect(), "Merge"),
                (self._swap_button_rect(), "Place"),
                (self._cancel_merge_rect(), "Cancel"),
            )
        else:
            src = player.team[self.pending_merge.from_index or 0]
            title = self.big_font.render("Same Pet Selected", True, TEXT)
            self.screen.blit(title, (dialog.x + 24, dialog.y + 24))
            if src is not None:
                message = self.font.render(
                    f"Merge {src.name} into slot {self.pending_merge.team_index + 1}, or swap positions?",
                    True,
                    MUTED,
                )
                self.screen.blit(message, (dialog.x + 24, dialog.y + 78))
            action_labels = (
                (self._merge_button_rect(), "Merge"),
                (self._swap_button_rect(), "Swap"),
                (self._cancel_merge_rect(), "Cancel"),
            )
        for rect, label in action_labels:
            pygame.draw.rect(self.screen, (46, 59, 85), rect, border_radius=12)
            pygame.draw.rect(self.screen, (80, 100, 140), rect, 2, border_radius=12)
            self._draw_centered_text(rect, label, TEXT)

    def _handle_merge_dialog_click(self, position: tuple[int, int]) -> bool:
        if self.pending_merge is None or self.state is None:
            return False
        if self._hit_button(position, self._cancel_merge_rect()):
            self.pending_merge = None
            self.selection = Selection()
            self.status = "Merge cancelled."
            return True
        player = self.state.current_player()
        merge = self.pending_merge
        if self._hit_button(position, self._merge_button_rect()):
            before = self.animations.snapshot_player(player)
            if merge.source == "shop":
                result = self.engine.shop.buy_pet(player, merge.shop_index, merge.team_index)
            else:
                result = self.engine.shop.move_pet(player, merge.from_index, merge.team_index)
            after = self.animations.snapshot_player(player)
            self._record_shop_result(before, after, result)
            self.status = result.message
            self.pending_merge = None
            self.selection = Selection()
            return True
        if self._hit_button(position, self._swap_button_rect()):
            if merge.source == "shop":
                empty = player.first_empty_team_slot()
                if empty is None:
                    self.status = "No empty team slot available."
                else:
                    before = self.animations.snapshot_player(player)
                    result = self.engine.shop.buy_pet(player, merge.shop_index, empty)
                    after = self.animations.snapshot_player(player)
                    self._record_shop_result(before, after, result)
                    self.status = result.message
            else:
                player.team[merge.from_index], player.team[merge.team_index] = (
                    player.team[merge.team_index],
                    player.team[merge.from_index],
                )
                self.status = "Pets swapped."
            self.pending_merge = None
            self.selection = Selection()
            return True
        if self._merge_dialog_rect().collidepoint(position):
            return True
        self.pending_merge = None
        self.selection = Selection()
        return True

    def _update_replay_animations(self, snapshot) -> None:
        step = snapshot.current_step
        if step == self._last_replay_step:
            return
        history = snapshot.step_history
        current = history[step]
        previous = history[step - 1] if step > 0 else None
        self.animations.on_replay_step_changed(current, previous)
        self.animations.trigger_replay_abilities(current.get("ability_triggers", []), current)
        self._last_replay_step = step

    def _start_mode(self, mode: str) -> None:
        if mode == GameMode.HUMAN_VS_HUMAN:
            self.player_modes = ["human", "human"]
            names = ["Player 1", "Player 2"]
        elif mode == GameMode.HUMAN_VS_AI:
            self.player_modes = ["human", "ai"]
            names = ["Human", "AI"]
        else:
            self.player_modes = ["ai", "ai"]
            names = ["AI 1", "AI 2"]
        self.mode = mode
        self.state = self.engine.new_game(names)
        self.selection = Selection()
        self.status = f"Mode selected: {mode}."
        self.pending_battle_frames = 0
        self.battle_replay_mode = False
        self.pending_merge = None
        self.animations.clear()
        self._last_replay_step = None

    def _handle_shop_click(self, shop_index: int) -> None:
        if self.state is None:
            return
        current_player = self.state.current_player()
        offer = current_player.shop.slots[shop_index]
        if offer is None:
            self.selection = Selection()
            return
        if self.selection.kind == "team" and self.selection.index is not None:
            before = self.animations.snapshot_player(current_player)
            result = self.engine.shop.buy_pet(current_player, shop_index, self.selection.index)
            after = self.animations.snapshot_player(current_player)
            self._record_shop_result(before, after, result)
            self.status = result.message
            self.selection = Selection()
            return
        self.selection = Selection(kind="shop", index=shop_index)
        self.status = f"Selected shop slot {shop_index + 1}: {offer.name}"

    def _handle_team_click(self, team_index: int) -> None:
        if self.state is None:
            return
        current_player = self.state.current_player()
        team_pet = current_player.team[team_index]
        if self.selection.kind == "shop" and self.selection.index is not None:
            offer = current_player.shop.slots[self.selection.index]
            if offer is None:
                self.selection = Selection()
                return
            before = self.animations.snapshot_player(current_player)
            if offer.kind == "food":
                result = self.engine.shop.buy_food(current_player, self.selection.index, team_index)
                after = self.animations.snapshot_player(current_player)
                self._record_shop_result(before, after, result)
                self.status = result.message
                self.selection = Selection()
                return
            team_pet_at_target = current_player.team[team_index]
            if (
                team_pet_at_target is not None
                and team_pet_at_target.name == offer.name
                and current_player.first_empty_team_slot() is not None
            ):
                self.pending_merge = PendingMergeChoice(
                    team_index=team_index,
                    source="shop",
                    shop_index=self.selection.index,
                )
                self.status = f"Merge {offer.name} or place in an empty slot?"
                return
            result = self.engine.shop.buy_pet(current_player, self.selection.index, team_index)
            after = self.animations.snapshot_player(current_player)
            self._record_shop_result(before, after, result)
            self.status = result.message
            self.selection = Selection()
            return
        if self.selection.kind == "team" and self.selection.index is not None:
            if self.selection.index == team_index:
                self.selection = Selection()
                self.status = "Selection cleared."
                return
            src = current_player.team[self.selection.index]
            dst = current_player.team[team_index]
            if src is not None and dst is not None and src.name == dst.name:
                self.pending_merge = PendingMergeChoice(
                    team_index=team_index,
                    source="team",
                    from_index=self.selection.index,
                )
                self.status = f"Merge or swap {src.name}?"
                return
            current_player.team[self.selection.index], current_player.team[team_index] = (
                current_player.team[team_index],
                current_player.team[self.selection.index],
            )
            self.selection = Selection()
            self.status = "Pets moved."
            return
        if team_pet is None:
            self.selection = Selection()
            return
        self.selection = Selection(kind="team", index=team_index)
        self.status = f"Selected team slot {team_index + 1}: {team_pet.name}"

    def draw(self) -> None:
        self.screen.fill(BACKGROUND)
        if self.state is None:
            self._draw_mode_menu()
        elif self.state.finished:
            self._draw_game_over()
        elif self.state.phase == Phase.BATTLE or self.pending_battle_frames > 0 or self.battle_replay_mode:
            self._draw_battle_scene()
        else:
            self._draw_header()
            self._draw_team_panel()
            self._draw_shop_panel()
            self._draw_footer()
        if self.pending_merge is not None:
            self._draw_merge_dialog()

    def _draw_game_over(self) -> None:
        title = self.big_font.render("Game Over", True, TEXT)
        self.screen.blit(title, (24, 18))
        if self.state is None:
            return
        if self.state.winner_index is None:
            message = "Result: Draw"
        else:
            message = f"Winner: {self.state.players[self.state.winner_index].name}"
        reason = self.state.finish_reason or "finished"
        status = self.font.render(f"{message} | Reason: {reason} | Round limit reached.", True, GOLD)
        self.screen.blit(status, (24, 60))
        self._draw_mode_menu()

    def _draw_battle_scene(self) -> None:
        title = self.big_font.render("Battle Phase", True, TEXT)
        self.screen.blit(title, (24, 18))

        if self.state is None:
            return

        snapshot = self.state.battle
        if self.battle_replay_mode and snapshot.step_history:
            current_step_data = snapshot.step_history[snapshot.current_step]
            subtitle = self.font.render(f"Replay: {current_step_data['description']} | Step {snapshot.current_step + 1}/{len(snapshot.step_history)}", True, MUTED)
            self.screen.blit(subtitle, (24, 56))

            # Draw teams from replay data
            step_data = snapshot.step_history[snapshot.current_step]
            self._update_replay_animations(snapshot)
            self._draw_replay_team(step_data["p0_team"], 0, 100, step_data["p0_health"])
            self._draw_replay_team(step_data["p1_team"], 1, 390, step_data["p1_health"])

            # Draw navigation buttons
            self._draw_battle_controls()
        else:
            subtitle = self.font.render("Battle is resolving. Shop controls are locked.", True, MUTED)
            self.screen.blit(subtitle, (24, 56))

            pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 100, 1352, 260), border_radius=18)
            pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 390, 1352, 260), border_radius=18)

            top_player = self.state.players[0]
            bottom_player = self.state.players[1]
            self._draw_battle_team(top_player, 0, 100)
            self._draw_battle_team(bottom_player, 1, 390)

            center = pygame.Rect(540, 682, 320, 64)
            pygame.draw.rect(self.screen, (46, 59, 85), center, border_radius=16)
            pygame.draw.rect(self.screen, (80, 100, 140), center, 2, border_radius=16)
            self._draw_centered_text(center, self.status or "Battle in progress", TEXT)

    def _draw_battle_team(self, player, player_number: int, top: int) -> None:
        label = self.font.render(f"Player {player_number + 1}: {player.name} | HP {player.health}", True, TEXT)
        self.screen.blit(label, (40, top + 16))
        for index, pet in enumerate(player.team):
            rect = pygame.Rect(52 + index * 260, top + 48, 220, 170)
            pygame.draw.rect(self.screen, PANEL_ALT if index % 2 == 0 else PANEL, rect, border_radius=14)
            fx = self.animations.fx(pet) if pet is not None else None
            self._draw_layered_borders(rect, self._replay_border_layers(fx))
            self._draw_pet_or_empty(rect, pet, index + 1, player_idx=player_number, slot_idx=index)

    def _draw_replay_team(self, team_data: list[dict | None], player_number: int, top: int, health: int) -> None:
        label = self.font.render(f"Player {player_number + 1} | HP {health}", True, TEXT)
        self.screen.blit(label, (40, top + 16))
        for index, pet_data in enumerate(team_data):
            rect = pygame.Rect(52 + index * 260, top + 48, 220, 170)
            pygame.draw.rect(self.screen, PANEL_ALT if index % 2 == 0 else PANEL, rect, border_radius=14)
            fx = self.animations.replay_fx(player_number, pet_data.get("uid")) if pet_data is not None else None
            self._draw_layered_borders(rect, self._replay_border_layers(fx))
            if pet_data is None:
                self._draw_centered_text(rect, "Empty", MUTED)
            else:
                self._draw_replay_pet(rect, pet_data, index + 1, player_number, index)

    def _draw_battle_controls(self) -> None:
        snapshot = self.state.battle
        has_prev = snapshot.current_step > 0
        has_next = snapshot.current_step < len(snapshot.step_history) - 1

        # Backward button
        back_rect = self._battle_back_rect()
        pygame.draw.rect(self.screen, (46, 59, 85) if has_prev else (30, 35, 45), back_rect, border_radius=14)
        pygame.draw.rect(self.screen, (80, 100, 140) if has_prev else (50, 60, 80), back_rect, 2, border_radius=14)
        self._draw_centered_text(back_rect, "◀ Back", TEXT if has_prev else MUTED)

        # Forward button
        forward_rect = self._battle_forward_rect()
        pygame.draw.rect(self.screen, (46, 59, 85) if has_next else (30, 35, 45), forward_rect, border_radius=14)
        pygame.draw.rect(self.screen, (80, 100, 140) if has_next else (50, 60, 80), forward_rect, 2, border_radius=14)
        self._draw_centered_text(forward_rect, "Forward ▶", TEXT if has_next else MUTED)

        # Next Turn button (only shown at the end)
        if snapshot.current_step == len(snapshot.step_history) - 1:
            next_turn_rect = self._battle_next_turn_rect()
            pygame.draw.rect(self.screen, (46, 85, 59), next_turn_rect, border_radius=14)
            pygame.draw.rect(self.screen, (80, 140, 100), next_turn_rect, 2, border_radius=14)
            self._draw_centered_text(next_turn_rect, f"Start Turn {self.state.turn + 1}", TEXT)

    def _draw_mode_menu(self) -> None:
        title = self.big_font.render("Super Auto Pets CPU Engine", True, TEXT)
        self.screen.blit(title, (360, 170))
        subtitle = self.font.render("Pick a game mode to start testing the UI and engine.", True, MUTED)
        self.screen.blit(subtitle, (410, 220))
        for mode, rect in self.mode_buttons.items():
            pygame.draw.rect(self.screen, (46, 59, 85), rect, border_radius=14)
            pygame.draw.rect(self.screen, (80, 100, 140), rect, 2, border_radius=14)
            self._draw_centered_text(rect, mode, TEXT)

    def _draw_header(self) -> None:
        title = self.big_font.render("Super Auto Pets CPU Engine", True, TEXT)
        self.screen.blit(title, (24, 18))
        current = self.state.current_player()
        phase_label = "Battle Phase" if self.state.phase == Phase.BATTLE or self.pending_battle_frames > 0 else "Shop Phase"
        info = self.font.render(
            f"{phase_label} | Turn {self.state.turn} | Active: {current.name} | Gold: {current.gold} | Health: {current.health}",
            True,
            MUTED,
        )
        self.screen.blit(info, (24, 56))

    def _draw_team_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 100, 1352, 250), border_radius=18)
        label = self.font.render("Team", True, TEXT)
        self.screen.blit(label, (40, 116))
        player = self.state.current_player()
        for index, pet in enumerate(player.team):
            rect = self._team_rect(index)
            pygame.draw.rect(self.screen, PANEL_ALT if index % 2 == 0 else PANEL, rect, border_radius=14)
            self._draw_layered_borders(rect, self._team_border_layers(index, pet))
            self._draw_pet_or_empty(rect, pet, index + 1)

    def _draw_shop_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 380, 1312, 370), border_radius=18)
        label = self.font.render("Shop", True, TEXT)
        self.screen.blit(label, (40, 396))
        player = self.state.current_player()
        for index, offer in enumerate(player.shop.slots):
            rect = self._shop_rect(index)
            pygame.draw.rect(self.screen, PANEL_ALT if index % 2 == 0 else PANEL, rect, border_radius=14)
            self._draw_layered_borders(rect, self._shop_border_layers(index, offer))
            if offer is None:
                self._draw_centered_text(rect, "Empty", MUTED)
            else:
                self._draw_offer(rect, offer, index + 1)

    def _draw_footer(self) -> None:
        status = self.font.render(self.status, True, GOLD)
        self.screen.blit(status, (24, 820))
        for rect, text in ((self._roll_rect(), "Roll"), (self._sell_rect(), "Sell"), (self._end_turn_rect(), "End Turn")):
            pygame.draw.rect(self.screen, (46, 59, 85), rect, border_radius=14)
            pygame.draw.rect(self.screen, (80, 100, 140), rect, 2, border_radius=14)
            self._draw_centered_text(rect, text, TEXT)

    def _draw_pet_or_empty(
        self,
        rect: pygame.Rect,
        pet,
        slot_number: int,
        *,
        player_idx: int | None = None,
        slot_idx: int | None = None,
    ) -> None:
        slot_label = self.font.render(f"Slot {slot_number}", True, MUTED)
        self.screen.blit(slot_label, (rect.x + 12, rect.y + 10))
        if pet is None:
            self._draw_centered_text(rect, "Empty", MUTED)
            return
        fx = self.animations.fx(pet)
        icon = self._load_icon("pets", pet.name)
        self._draw_rotated_icon(icon, rect, fx)
        self._draw_perk_badge(rect, pet.perk, fx)
        name = self.font.render(pet.name, True, TEXT)
        self.screen.blit(name, (rect.x + 12, rect.bottom - 56))
        self._draw_live_pet_stats(rect, pet, fx)

    def _draw_stat_value(self, text: str, x: int, y: int, highlighted: bool, intensity: float = 1.0) -> int:
        surface = self.font.render(text, True, (255, 255, 255) if highlighted else GOLD)
        width = surface.get_width()
        if highlighted:
            pad_x = 6
            pad_y = 3
            glow_rect = pygame.Rect(x - pad_x, y - pad_y, width + pad_x * 2, surface.get_height() + pad_y * 2)
            glow = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
            alpha = int(100 + 155 * intensity)
            glow.fill((*STAT_HIGHLIGHT_BG, alpha))
            self.screen.blit(glow, glow_rect.topleft)
            pygame.draw.rect(self.screen, STAT_HIGHLIGHT, glow_rect, 2, border_radius=5)
            inner = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
            inner_alpha = int(60 + 80 * intensity)
            inner.fill((255, 255, 255, inner_alpha))
            self.screen.blit(inner, glow_rect.topleft)
        self.screen.blit(surface, (x, y))
        return width

    def _highlight_intensity(self, fx: PetVisualFX | None, frames: int) -> float:
        if fx is None or frames <= 0:
            return 0.0
        return min(1.0, frames / HIGHLIGHT_FRAMES)

    def _draw_live_pet_stats(self, rect: pygame.Rect, pet, fx: PetVisualFX | None) -> None:
        eff_atk = pet.effective_attack
        eff_hp = pet.effective_health
        x = rect.x + 12
        y = rect.bottom - 30
        atk_hi = fx is not None and fx.highlight_attack > 0
        hp_hi = fx is not None and fx.highlight_health > 0
        xp_hi = fx is not None and fx.highlight_xp > 0
        atk_int = self._highlight_intensity(fx, fx.highlight_attack if fx else 0)
        hp_int = self._highlight_intensity(fx, fx.highlight_health if fx else 0)
        xp_int = self._highlight_intensity(fx, fx.highlight_xp if fx else 0)

        if pet.temporary_attack > 0:
            x += self._draw_stat_value(str(eff_atk), x, y, atk_hi, atk_int)
            underline_y = y + self.font.get_height() - 1
            pygame.draw.line(self.screen, STAT_HIGHLIGHT if atk_hi else GOLD, (rect.x + 12, underline_y), (x, underline_y), 2)
        else:
            x += self._draw_stat_value(str(eff_atk), x, y, atk_hi, atk_int)

        slash = self.font.render("/", True, GOLD if not (atk_hi or hp_hi) else STAT_HIGHLIGHT)
        self.screen.blit(slash, (x, y))
        x += slash.get_width()
        x += self._draw_stat_value(str(eff_hp), x, y, hp_hi, hp_int)
        xp_text = f"  Lv{pet.level} ({pet.experience} XP)"
        if xp_hi:
            x += self._draw_stat_value(xp_text, x, y, True, xp_int)
        else:
            self.screen.blit(self.font.render(xp_text, True, GOLD), (x, y))

    def _draw_replay_pet(
        self,
        rect: pygame.Rect,
        pet_data: dict,
        slot_number: int,
        player_idx: int,
        slot_idx: int,
    ) -> None:
        slot_label = self.font.render(f"Slot {slot_number}", True, MUTED)
        self.screen.blit(slot_label, (rect.x + 12, rect.y + 10))
        fx = self.animations.replay_fx(player_idx, pet_data.get("uid"))
        icon = self._load_icon("pets", pet_data["name"])
        self._draw_rotated_icon(icon, rect, fx)
        self._draw_perk_badge(rect, pet_data.get("perk"), fx)
        name = self.font.render(pet_data["name"], True, TEXT)
        self.screen.blit(name, (rect.x + 12, rect.bottom - 56))
        self._draw_replay_pet_stats(rect, pet_data, fx)

    def _draw_replay_pet_stats(self, rect: pygame.Rect, pet_data: dict, fx: PetVisualFX | None) -> None:
        total_attack = pet_data["attack"] + pet_data.get("temporary_attack", 0)
        total_health = pet_data["health"] + pet_data.get("temporary_health", 0)
        temp_atk = pet_data.get("temporary_attack", 0)
        x = rect.x + 12
        y = rect.bottom - 30
        atk_hi = fx is not None and fx.highlight_attack > 0
        hp_hi = fx is not None and fx.highlight_health > 0
        xp_hi = fx is not None and fx.highlight_xp > 0
        atk_int = self._highlight_intensity(fx, fx.highlight_attack if fx else 0)
        hp_int = self._highlight_intensity(fx, fx.highlight_health if fx else 0)
        xp_int = self._highlight_intensity(fx, fx.highlight_xp if fx else 0)

        if temp_atk > 0:
            x += self._draw_stat_value(str(total_attack), x, y, atk_hi, atk_int)
            underline_y = y + self.font.get_height() - 1
            pygame.draw.line(self.screen, STAT_HIGHLIGHT if atk_hi else GOLD, (rect.x + 12, underline_y), (x, underline_y), 2)
        else:
            x += self._draw_stat_value(str(total_attack), x, y, atk_hi, atk_int)

        slash = self.font.render("/", True, GOLD if not (atk_hi or hp_hi) else STAT_HIGHLIGHT)
        self.screen.blit(slash, (x, y))
        x += slash.get_width()
        x += self._draw_stat_value(str(total_health), x, y, hp_hi, hp_int)
        xp_text = f"  Lv{pet_data['level']} ({pet_data['experience']} XP)"
        if xp_hi:
            x += self._draw_stat_value(xp_text, x, y, True, xp_int)
        else:
            self.screen.blit(self.font.render(xp_text, True, GOLD), (x, y))

    def _draw_rotated_icon(
        self,
        icon: pygame.Surface | None,
        rect: pygame.Rect,
        fx: PetVisualFX | None,
    ) -> None:
        if icon is None:
            return
        angle = fx.rotation_deg if fx is not None else 0.0
        if angle:
            icon = pygame.transform.rotate(icon, -angle)
        self.screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 76)))

    def _draw_layered_borders(
        self,
        rect: pygame.Rect,
        layers: list[tuple[tuple[int, int, int], int]],
    ) -> None:
        inset = 0
        for color, width in layers:
            border_rect = pygame.Rect(
                rect.x + inset,
                rect.y + inset,
                rect.width - inset * 2,
                rect.height - inset * 2,
            )
            if border_rect.width <= width * 2 or border_rect.height <= width * 2:
                break
            radius = max(4, 14 - inset)
            pygame.draw.rect(self.screen, color, border_rect, width, border_radius=radius)
            inset += width

    def _team_border_layers(self, index: int, pet) -> list[tuple[tuple[int, int, int], int]]:
        layers: list[tuple[tuple[int, int, int], int]] = [(PANEL_BORDER, 2)]
        if self.selection.kind == "team" and self.selection.index == index:
            layers.append((SELECT, 2))
        fx = self.animations.fx(pet) if pet is not None else None
        if fx is not None and fx.golden_border > 0:
            layers.append((GOLDEN_BORDER, 3))
        return layers

    def _shop_border_layers(
        self,
        index: int,
        offer: ShopOffer | None,
    ) -> list[tuple[tuple[int, int, int], int]]:
        layers: list[tuple[tuple[int, int, int], int]] = [(PANEL_BORDER, 2)]
        if offer is not None and offer.frozen:
            layers.append((FREEZE, 2))
        if offer is not None and offer.tier_up_reward:
            layers.append((TIER_UP, 2))
        if self.selection.kind == "shop" and self.selection.index == index:
            layers.append((SELECT, 2))
        return layers

    def _replay_border_layers(self, fx: PetVisualFX | None) -> list[tuple[tuple[int, int, int], int]]:
        layers: list[tuple[tuple[int, int, int], int]] = [(PANEL_BORDER, 2)]
        if fx is not None and fx.golden_border > 0:
            layers.append((GOLDEN_BORDER, 3))
        return layers

    def _draw_perk_badge(
        self,
        rect: pygame.Rect,
        perk: str | None,
        fx: PetVisualFX | None = None,
    ) -> None:
        badge_size = 36
        badge_x = rect.right - badge_size - 8
        badge_y = rect.y + 8
        badge_rect = pygame.Rect(badge_x, badge_y, badge_size, badge_size)

        if fx is not None and fx.perk_lost and fx.perk_lost_frames > 0 and fx.perk_lost in PERK_ICON_MAP:
            lost_kind, lost_name = PERK_ICON_MAP[fx.perk_lost]
            lost_icon = self._load_icon(lost_kind, lost_name, size=32)
            if lost_icon is not None:
                alpha = int(180 * fx.perk_lost_frames / HIGHLIGHT_FRAMES)
                ghost = lost_icon.copy()
                ghost.set_alpha(max(40, alpha))
                pygame.draw.rect(self.screen, PANEL, badge_rect, border_radius=8)
                pygame.draw.rect(self.screen, PERK_LOST, badge_rect, 2, border_radius=8)
                self.screen.blit(ghost, ghost.get_rect(center=badge_rect.center))
                x_color = PERK_LOST if fx.perk_lost_frames > HIGHLIGHT_FRAMES // 3 else MUTED
                x_surf = self.font.render("×", True, x_color)
                self.screen.blit(x_surf, x_surf.get_rect(center=badge_rect.center))

        if not perk or perk not in PERK_ICON_MAP:
            return

        kind, name = PERK_ICON_MAP[perk]
        icon = self._load_icon(kind, name, size=32)
        if icon is None:
            return

        highlighted = fx is not None and fx.highlight_perk > 0
        if highlighted:
            pad = 3
            glow_rect = pygame.Rect(
                badge_rect.x - pad,
                badge_rect.y - pad,
                badge_rect.width + pad * 2,
                badge_rect.height + pad * 2,
            )
            glow = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
            intensity = min(1.0, fx.highlight_perk / HIGHLIGHT_FRAMES)
            glow.fill((*PERK_HIGHLIGHT, int(100 + 120 * intensity)))
            self.screen.blit(glow, glow_rect.topleft)

        pygame.draw.rect(self.screen, PANEL, badge_rect, border_radius=8)
        border_color = PERK_HIGHLIGHT if highlighted else GOLD
        pygame.draw.rect(self.screen, border_color, badge_rect, 2, border_radius=8)
        self.screen.blit(icon, icon.get_rect(center=badge_rect.center))

    def _draw_offer(self, rect: pygame.Rect, offer: ShopOffer, slot_number: int) -> None:
        slot_label = self.font.render(f"Slot {slot_number}", True, MUTED)
        self.screen.blit(slot_label, (rect.x + 12, rect.y + 10))
        icon = self._load_icon(offer.kind + "s" if offer.kind in {"pet", "food", "token"} else "pets", offer.name)
        if icon is not None:
            self.screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 76)))
        name = self.font.render(offer.name, True, TEXT)
        if offer.tier_up_reward:
            kind = self.font.render(f"Tier-Up T{offer.tier}", True, ACCENT)
        else:
            kind = self.font.render(f"{offer.kind.title()} T{offer.tier}", True, GOLD)
        self.screen.blit(name, (rect.x + 12, rect.bottom - 56))
        self.screen.blit(kind, (rect.x + 12, rect.bottom - 30))
        if offer.kind == "pet" and offer.name in self.registry.pets:
            pet_stats = self.registry.pets[offer.name]
            effective_attack = pet_stats.attack + offer.bonus_attack
            effective_health = pet_stats.health + offer.bonus_health
            stat_line = self.font.render(f"{effective_attack}/{effective_health}", True, MUTED)
            self.screen.blit(stat_line, (rect.x + 12, rect.y + 40))

    def _draw_centered_text(self, rect: pygame.Rect, text: str, color: tuple[int, int, int]) -> None:
        surface = self.font.render(text, True, color)
        self.screen.blit(surface, surface.get_rect(center=rect.center))

    def _load_icon(self, kind: str, name: str, *, size: int = 60) -> pygame.Surface | None:
        key = (kind, name, size)
        if key in self.icon_cache:
            return self.icon_cache[key]
        path = self.registry.pet_icon(name) if kind == "pets" else self.registry.food_icon(name) if kind == "foods" else self.registry.token_icon(name)
        if not path.exists():
            return None
        image = pygame.image.load(path.as_posix()).convert_alpha()
        image = pygame.transform.smoothscale(image, (size, size))
        self.icon_cache[key] = image
        return image

    def _team_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(52 + index * 260, 148, 220, 170)

    def _shop_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(40 + index * 142, 430, 128, 260)

    def _roll_rect(self) -> pygame.Rect:
        return pygame.Rect(930, 784, 130, 44)

    def _sell_rect(self) -> pygame.Rect:
        return pygame.Rect(1080, 784, 130, 44)

    def _end_turn_rect(self) -> pygame.Rect:
        return pygame.Rect(1230, 784, 130, 44)

    def _battle_back_rect(self) -> pygame.Rect:
        return pygame.Rect(440, 682, 200, 44)

    def _battle_forward_rect(self) -> pygame.Rect:
        return pygame.Rect(660, 682, 200, 44)

    def _battle_next_turn_rect(self) -> pygame.Rect:
        return pygame.Rect(880, 682, 260, 44)

    def _hit_button(self, position: tuple[int, int], rect: pygame.Rect) -> bool:
        return rect.collidepoint(position)

    def _hit_team_slot(self, position: tuple[int, int]) -> int | None:
        for index in range(5):
            if self._team_rect(index).collidepoint(position):
                return index
        return None

    def _hit_shop_slot(self, position: tuple[int, int]) -> int | None:
        for index in range(9):
            if self._shop_rect(index).collidepoint(position):
                return index
        return None

    def _update_ai_and_battle(self) -> None:
        if self.state is None:
            return
        if self.pending_battle_frames > 0:
            self.pending_battle_frames -= 1
            if self.pending_battle_frames == 0:
                has_human = "human" in self.player_modes
                if has_human:
                    result = self.engine.resolve_battle_only(self.state)
                    self.battle_replay_mode = True
                    self.state.battle.current_step = 0
                    self._last_replay_step = None
                    self.animations.clear()
                    self.status = f"Battle resolved: {result.battle_result.value}. Review the replay, then start turn {self.state.turn + 1}."
                else:
                    result = self.engine.resolve_battle_and_start_next_round(self.state)
                    self.status = f"Battle resolved: {result.battle_result.value}. Round {self.state.turn} started."
            return

        if self.battle_replay_mode:
            return

        current_index = self.state.active_player_index
        if current_index >= len(self.player_modes):
            return
        if self.player_modes[current_index] != "ai" or self.state.phase != Phase.SHOP:
            return

        self._run_simple_ai_turn()

    def _run_simple_ai_turn(self) -> None:
        if self.state is None:
            return
        player = self.state.current_player()
        for shop_index, offer in enumerate(player.shop.slots):
            if offer is None or offer.kind != "pet":
                continue
            if player.gold < 3:
                break
            target_slot = player.first_empty_team_slot()
            if target_slot is None:
                break
            result = self.engine.shop.buy_pet(player, shop_index, target_slot)
            if result.success:
                self.status = f"AI bought {offer.name}."
                break

        result = self.engine.end_shop_turn(self.state)
        if result.battle_pending:
            self.pending_battle_frames = 18
            self.status = "Battle phase..."


def main() -> None:
    GameUI().run()


if __name__ == "__main__":
    main()