from __future__ import annotations

import os
from dataclasses import dataclass

os.environ.setdefault("SDL_VIDEO_CENTERED", "1")

import pygame

from ..cpu.game import CpuGameEngine
from ..models import GameState, Phase, PlayerState, ShopOffer
from ..registry import load_registry
from ..rng import SeededRNG


WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
BACKGROUND = (14, 18, 28)
PANEL = (24, 31, 47)
PANEL_ALT = (31, 41, 61)
TEXT = (235, 240, 255)
MUTED = (150, 160, 185)
ACCENT = (100, 200, 255)
GOLD = (235, 198, 77)


@dataclass(slots=True)
class Selection:
    kind: str | None = None
    index: int | None = None


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
        self.state: GameState | None = None
        self.selection = Selection()
        self.status = "Select a mode to start."
        self.icon_cache: dict[tuple[str, str], pygame.Surface] = {}
        self.mode = None
        self.player_modes: list[str] = []
        self.pending_battle_frames = 0
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
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_click(event.pos)

            self._update_ai_and_battle()

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
            self.engine.shop.roll(self.state.current_player())
            self.status = "Shop rolled."
            return

        if self._hit_button(position, self._sell_rect()):
            if self.selection.kind == "team" and self.selection.index is not None:
                result = self.engine.shop.sell_pet(self.state.current_player(), self.selection.index)
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

    def _handle_shop_click(self, shop_index: int) -> None:
        if self.state is None:
            return
        current_player = self.state.current_player()
        offer = current_player.shop.slots[shop_index]
        if offer is None:
            self.selection = Selection()
            return
        if self.selection.kind == "team" and self.selection.index is not None:
            result = self.engine.shop.buy_pet(current_player, shop_index, self.selection.index)
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
            if offer.kind == "food":
                result = self.engine.shop.buy_food(current_player, self.selection.index, team_index)
            else:
                result = self.engine.shop.buy_pet(current_player, self.selection.index, team_index)
            self.status = result.message
            self.selection = Selection()
            return
        if self.selection.kind == "team" and self.selection.index is not None:
            if self.selection.index == team_index:
                self.selection = Selection()
                self.status = "Selection cleared."
                return
            current_player.team[self.selection.index], current_player.team[team_index] = current_player.team[team_index], current_player.team[self.selection.index]
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
        elif self.state.phase == Phase.BATTLE or self.pending_battle_frames > 0:
            self._draw_battle_scene()
        else:
            self._draw_header()
            self._draw_team_panel()
            self._draw_shop_panel()
            self._draw_footer()

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
        subtitle = self.font.render("Battle is resolving. Shop controls are locked.", True, MUTED)
        self.screen.blit(subtitle, (24, 56))

        pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 100, 1352, 260), border_radius=18)
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 390, 1352, 260), border_radius=18)

        if self.state is None:
            return

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
            self._draw_pet_or_empty(rect, pet, index + 1)

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
            pygame.draw.rect(self.screen, ACCENT if self.selection.kind == "team" and self.selection.index == index else (60, 70, 92), rect, 2, border_radius=14)
            self._draw_pet_or_empty(rect, pet, index + 1)

    def _draw_shop_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL, pygame.Rect(24, 380, 1352, 370), border_radius=18)
        label = self.font.render("Shop", True, TEXT)
        self.screen.blit(label, (40, 396))
        player = self.state.current_player()
        for index, offer in enumerate(player.shop.slots):
            rect = self._shop_rect(index)
            pygame.draw.rect(self.screen, PANEL_ALT if index % 2 == 0 else PANEL, rect, border_radius=14)
            pygame.draw.rect(self.screen, ACCENT if self.selection.kind == "shop" and self.selection.index == index else (60, 70, 92), rect, 2, border_radius=14)
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

    def _draw_pet_or_empty(self, rect: pygame.Rect, pet, slot_number: int) -> None:
        slot_label = self.font.render(f"Slot {slot_number}", True, MUTED)
        self.screen.blit(slot_label, (rect.x + 12, rect.y + 10))
        if pet is None:
            self._draw_centered_text(rect, "Empty", MUTED)
            return
        icon = self._load_icon("pets", pet.name)
        if icon is not None:
            self.screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 76)))
        name = self.font.render(pet.name, True, TEXT)
        stats = self.font.render(f"{pet.attack}/{pet.health}  Lv{pet.level}", True, GOLD)
        self.screen.blit(name, (rect.x + 12, rect.bottom - 56))
        self.screen.blit(stats, (rect.x + 12, rect.bottom - 30))

    def _draw_offer(self, rect: pygame.Rect, offer: ShopOffer, slot_number: int) -> None:
        slot_label = self.font.render(f"Slot {slot_number}", True, MUTED)
        self.screen.blit(slot_label, (rect.x + 12, rect.y + 10))
        icon = self._load_icon(offer.kind + "s" if offer.kind in {"pet", "food", "token"} else "pets", offer.name)
        if icon is not None:
            self.screen.blit(icon, icon.get_rect(center=(rect.centerx, rect.y + 76)))
        name = self.font.render(offer.name, True, TEXT)
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

    def _load_icon(self, kind: str, name: str) -> pygame.Surface | None:
        key = (kind, name)
        if key in self.icon_cache:
            return self.icon_cache[key]
        path = self.registry.pet_icon(name) if kind == "pets" else self.registry.food_icon(name) if kind == "foods" else self.registry.token_icon(name)
        if not path.exists():
            return None
        image = pygame.image.load(path.as_posix()).convert_alpha()
        image = pygame.transform.smoothscale(image, (60, 60))
        self.icon_cache[key] = image
        return image

    def _team_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(52 + index * 260, 148, 220, 170)

    def _shop_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(52 + index * 155, 430, 136, 260)

    def _roll_rect(self) -> pygame.Rect:
        return pygame.Rect(930, 784, 130, 44)

    def _sell_rect(self) -> pygame.Rect:
        return pygame.Rect(1080, 784, 130, 44)

    def _end_turn_rect(self) -> pygame.Rect:
        return pygame.Rect(1230, 784, 130, 44)

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
                result = self.engine.resolve_battle_and_start_next_round(self.state)
                self.status = f"Battle resolved: {result.battle_result.value}."
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