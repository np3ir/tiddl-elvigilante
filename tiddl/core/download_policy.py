from dataclasses import dataclass


@dataclass
class SessionTrackLimit:
    """Small, synchronous gate for a per-process track limit.

    ``admit`` returns whether the item may continue and whether the caller
    should display the limit warning.  The warning is deliberately emitted
    only once even when many already-scheduled items reach the gate.
    """

    limit: int
    count: int = 0
    announced: bool = False

    def admit(self) -> tuple[bool, bool]:
        if self.limit > 0 and self.count >= self.limit:
            should_announce = not self.announced
            self.announced = True
            return False, should_announce

        self.count += 1
        return True, False
