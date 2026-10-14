"""Pure decision policy for the depth-10 green-coat farm.

The caller supplies verified screen observations. No clicks or screenshots are
performed here, and `absent_visible` is never treated as proof of a complete
loot check by itself.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FarmObservation:
    elapsed_seconds: float
    loot_count: int | None
    fc_ready: bool
    energy: int | None = None
    panel_verdict: str | None = None
    panel_complete: bool = False
    battle_result: str | None = None  # 'failed' or 'won'


class GreenFarmPolicy:
    def __init__(self, first_drop_wait_seconds: float = 8.0):
        if first_drop_wait_seconds <= 0:
            raise ValueError('等待时间必须为正数')
        self.first_drop_wait_seconds = first_drop_wait_seconds
        self.phase = 'opening'
        self.fc_sent = False
        self.first_fc_clicked_at: float | None = None
        self.first_fc_energy_before: int | None = None
        self.first_fc_confirmed = False
        self.keep_run = False
        self.finish_fc_pending = False
        self.finish_fc_clicked_at: float | None = None
        self.finish_fc_energy_before: int | None = None

    def decide(self, obs: FarmObservation) -> str:
        """Return one proposed action; caller must verify its UI result."""
        fc_usable = obs.fc_ready and obs.energy is not None and obs.energy >= 4
        if obs.battle_result == 'failed':
            self.phase = 'retry'
            return 'retry'
        if obs.battle_result == 'won':
            self.phase = 'settle'
            return 'settle'
        if self.phase == 'opening':
            # A drop can precede a usable FC in the first spawn pattern.
            if obs.loot_count is not None and obs.loot_count > 0:
                self.phase = 'checking'
                return 'open_loot'
            if obs.loot_count is None:
                return 'wait'
            if obs.elapsed_seconds < self.first_drop_wait_seconds:
                return 'wait'
            if not self.fc_sent and fc_usable:
                self.fc_sent = True
                self.first_fc_clicked_at = obs.elapsed_seconds
                self.first_fc_energy_before = obs.energy
                self.phase = 'after_first_fc'
                return 'cast_fc_once'
            return 'wait'
        if self.phase == 'after_first_fc':
            if obs.loot_count is not None and obs.loot_count > 0:
                self.phase = 'checking'
                return 'open_loot'
            if (obs.energy is not None and self.first_fc_energy_before is not None and
                    obs.energy <= self.first_fc_energy_before - 3):
                self.first_fc_confirmed = True
            if (not self.first_fc_confirmed and obs.energy is not None and
                    self.first_fc_energy_before is not None and
                    obs.energy > self.first_fc_energy_before - 3 and
                    self.first_fc_clicked_at is not None and
                    obs.elapsed_seconds - self.first_fc_clicked_at > 5):
                return 'pause_for_review'  # Click not verified; never blindly retry.
            return 'wait'  # FC animation and reward counter may lag seconds.
        if self.phase == 'checking':
            if obs.panel_verdict == 'found':
                self.keep_run = True
                self.phase = 'finish'
                return 'close_loot'
            if obs.panel_verdict == 'absent_visible' and obs.panel_complete:
                self.phase = 'lose'
                return 'close_loot'
            return 'pause_for_review'
        if self.phase == 'lose':
            return 'wait'  # Let battle fail without further FC use.
        if self.phase == 'finish':
            if (self.finish_fc_pending and obs.energy is not None and
                    self.finish_fc_energy_before is not None and
                    obs.energy <= self.finish_fc_energy_before - 3):
                self.finish_fc_pending = False
                return 'wait'
            if self.finish_fc_pending:
                if (self.finish_fc_clicked_at is not None and
                        obs.elapsed_seconds - self.finish_fc_clicked_at > 5 and
                        obs.energy is not None and self.finish_fc_energy_before is not None and
                        obs.energy > self.finish_fc_energy_before - 3):
                    return 'pause_for_review'  # FC cost not observed; no blind retry.
                return 'wait'
            if not fc_usable:
                return 'wait'
            self.finish_fc_pending = True
            self.finish_fc_clicked_at = obs.elapsed_seconds
            self.finish_fc_energy_before = obs.energy
            return 'cast_fc'
        return 'wait'
