from __future__ import annotations
class ApiError(Exception):
    def __init__(self, status: int, subStatus: str = None, userMessage: str = None, **kwargs):
        self.status = status
        self.sub_status = subStatus
        self.user_message = userMessage
        self.extra = kwargs

    def __str__(self):
        msg = self.user_message or "Unknown Error"
        sub = self.sub_status or "?"
        return f"{msg} ({self.status}/{sub})"
