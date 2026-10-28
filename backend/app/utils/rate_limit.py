"""How often one account may call the routes that cost the most (task S-04).

Login attempts have their own limit (services/auth_service.py). These are for an account that is
logged in: camera frames and spreadsheet uploads. A scanner sends a frame only after the answer to
the previous one, about 5 to 8 a second on this kind of computer, so the limits leave room for a few
scanners under one login and stop only a client that floods the backend. Counted in memory, which
is right for the one backend process this application runs as.
"""
import math
import threading
import time
from collections import deque

from fastapi import Depends, HTTPException

from app.security import current_account
from app.services.auth_service import Actor


class AccountLimit:
    """A dependency: at most `limit` requests per account in any `seconds`, otherwise 429 with Retry-After."""

    def __init__(self, name: str, limit: int, seconds: float):
        self.name = name
        self.limit = limit
        self.seconds = seconds
        self.hits = {}
        self.lock = threading.Lock()

    def __call__(self, actor: Actor = Depends(current_account)):
        now = time.monotonic()
        with self.lock:
            window = self.hits.setdefault(actor.id, deque())
            while window and now - window[0] >= self.seconds:
                window.popleft()
            if len(window) >= self.limit:
                wait = max(1, math.ceil(self.seconds - (now - window[0])))
                raise HTTPException(429, f"Too many requests. Wait {wait} seconds and try again.", headers={"Retry-After": str(wait)})
            window.append(now)

    def reset(self):
        with self.lock:
            self.hits.clear()


# Camera frames, scanner and enrollment together: 20 a second on average over 30 seconds.
frames = AccountLimit("frames", 600, 30)
# Spreadsheet uploads (each up to 5 MB and 2,000 rows).
uploads = AccountLimit("uploads", 20, 60)
# Attendance codes, scanned or typed: two a second over a minute keeps up with a queue at the door,
# and is far too few to find a working code by trying (there are 2^40 of them).
codes = AccountLimit("codes", 120, 60)
