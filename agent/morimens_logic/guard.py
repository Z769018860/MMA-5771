"""Stuck detection with an escalation ladder, so the engine never repeats the same failing action forever.

Levels (by how many consecutive identical states were seen after our actions):
  0 normal -> 1 retry -> 2 alternate action -> 3 recover (back out / blank taps) -> 4 give up
"""

from .policy import get


class StuckGuard:
    def __init__(self, policy):
        self.policy = policy
        self.last_sig = None
        self.same = 0
        self.steps = 0
        self.unknown_run = 0
        self.history = []

    def signature(self, obs):
        if obs.fingerprint is not None:
            return ("fp", obs.fingerprint)
        return (obs.screen.value, obs.player, obs.event_title, tuple(obs.options), len(obs.choices),
                len(obs.shop_items), len(obs.candidates), obs.hp_ratio)

    def observe(self, obs):
        """Update counters and return the escalation level for this observation."""
        self.steps += 1
        sig = self.signature(obs)
        self.same = self.same + 1 if sig == self.last_sig else 0
        self.last_sig = sig
        self.unknown_run = self.unknown_run + 1 if obs.screen.value in ("unknown", "loading") else 0
        p = lambda k: get(self.policy, f"stuck.{k}")
        if self.steps > p("max_steps_per_map"):
            return 4
        if self.unknown_run > p("max_unknown_steps") and self.same >= p("same_state_alternate"):
            return 4
        if self.same >= p("same_state_recover") + 4:
            return 4
        if self.same >= p("same_state_recover"):
            return 3
        if self.same >= p("same_state_alternate"):
            return 2
        if self.same >= p("same_state_retry"):
            return 1
        return 0

    def note(self, action):
        self.history.append(str(action))
        self.history = self.history[-20:]

    def progressed(self):
        """Call when an action definitely changed the game (e.g. moved to a new tile)."""
        self.same = 0
        self.last_sig = None
