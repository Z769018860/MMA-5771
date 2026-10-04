"""Observation / Action contract between a GameAdapter and the decision engine."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Screen(str, Enum):
    MAP = "map"                # hex map, free to move
    EVENT = "event"            # event with options
    SHOP = "shop"
    PICK_ARTIFACT = "pick_artifact"   # choose one artifact (三选一造物)
    PICK_SEAL = "pick_seal"           # choose one seal (刻印)
    PICK_CARD = "pick_card"
    CONTACT = "contact"        # 联络点: heal / awaken
    FORMATION = "formation"    # squad screen before a battle
    BATTLE = "battle"
    DEFEAT = "defeat"          # revive / retreat decision
    DIALOGUE = "dialogue"      # story text, skippable
    POPUP = "popup"            # explanation popups, rewards, toasts
    RESULT = "result"          # investigation complete
    LOADING = "loading"
    UNKNOWN = "unknown"


class Do(str, Enum):
    TAP_TILE = "tap_tile"          # arg: (island,row,col)
    TAP_OPTION = "tap_option"      # arg: index of event option
    TAP_ITEM = "tap_item"          # arg: index of shop item (buy)
    TAP_CHOICE = "tap_choice"      # arg: index of artifact/seal/card
    CONFIRM = "confirm"
    LEAVE = "leave"                # close shop / leave event
    CHOOSE_HEAL = "choose_heal"
    CHOOSE_AWAKEN = "choose_awaken"
    START_BATTLE = "start_battle"  # formation -> investigate
    SKIP = "skip"                  # skip dialogue
    CLOSE_POPUP = "close_popup"
    FINISH = "finish"              # result page button
    REVIVE = "revive"
    RETREAT = "retreat"
    TAP_BLANK = "tap_blank"        # safe blank spot, dismisses popups
    BACK = "back"
    WAIT = "wait"
    STOP = "stop"                  # engine gives up / task done; arg: reason


@dataclass
class Action:
    kind: Do
    arg: object = None
    reason: str = ""

    def __str__(self):
        return f"{self.kind.value}({self.arg!r}) # {self.reason}" if self.arg is not None else f"{self.kind.value} # {self.reason}"


@dataclass
class ShopItem:
    price: Optional[int] = None
    affordable: bool = True
    name: Optional[str] = None
    sold: bool = False


@dataclass
class Observation:
    screen: Screen
    # map
    player: Optional[tuple] = None                 # (island,row,col) if localised
    map_id: Optional[str] = None                   # e.g. "5-6"; enables prior knowledge from maps.json
    candidates: list = field(default_factory=list)  # tiles that can be entered now: [(key, type|None)]
    # event / choices (text fields may be None if OCR is unavailable -> position-based choice)
    event_title: Optional[str] = None
    options: list = field(default_factory=list)    # option labels, or [None, None, ...] to give only the count
    choices: list = field(default_factory=list)    # artifact/seal/card names or [None]*n
    shop_items: list = field(default_factory=list)
    # status
    hp_ratio: Optional[float] = None
    currency: Optional[int] = None
    revive_available: Optional[bool] = None
    battle_won: Optional[bool] = None
    fingerprint: Optional[str] = None              # hash of the frame/state; used to detect "nothing changed"
