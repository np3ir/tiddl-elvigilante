from dataclasses import dataclass


@dataclass
class SessionTrackLimit:
    """Per-run gate for ``max_tracks_per_session``.

    **What the cap counts (defined):** only tracks this run actually FETCHED
    (``record(was_downloaded=True)``). A track already complete on disk — the
    common ``skip_existing`` case — does NOT consume the cap, so a run over a
    mostly-downloaded library keeps making progress on the genuinely-missing
    tracks instead of the cap being eaten by files already present. This is a
    deliberate change from the old behaviour, which counted every *admitted*
    track (i.e. also the already-present ones).

    Reaching the cap latches :attr:`reached` — a run-wide signal that is
    **distinct from Cancel / 401 / 429**. It means "this run has downloaded its
    quota; stop taking new work and let the caller resume later", NOT an error or
    a user cancel, so the run still exits 0. Callers gate new dispatch /
    enumeration on :meth:`is_reached` and let already-admitted downloads finish.
    """

    limit: int
    downloaded: int = 0
    reached: bool = False
    announced: bool = False

    def is_enabled(self) -> bool:
        return self.limit > 0

    def is_reached(self) -> bool:
        """Run-wide 'quota used up' signal. Monotonic once set."""
        return self.reached

    def admit(self) -> tuple[bool, bool]:
        """Gate ONE track just before it is downloaded.

        Returns ``(admitted, should_announce)``. Not admitted once the quota of
        NEW downloads is used up; the warning is flagged exactly once even when
        many already-scheduled tracks reach the gate afterwards.
        """
        if self.limit > 0 and self.downloaded >= self.limit:
            self.reached = True
            should_announce = not self.announced
            self.announced = True
            return False, should_announce
        return True, False

    def record(self, was_downloaded: bool) -> None:
        """Count a finished track toward the cap. Only a NEW download consumes
        it — an already-present file does not. Latches :attr:`reached` when the
        quota is exhausted so the run stops taking new work."""
        if self.limit > 0 and was_downloaded:
            self.downloaded += 1
            if self.downloaded >= self.limit:
                self.reached = True
