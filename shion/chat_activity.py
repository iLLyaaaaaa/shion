"""Transient Claude Desktop presence and single active task."""
from __future__ import annotations


class ChatActivity:
    def __init__(self):
        self.clients = set()
        self.seen_online = False
        self.clear()

    def clear(self):
        self.owner = None
        self.phase = "idle"
        self.deadline = 0

    def expire(self, now):
        if self.owner and now >= self.deadline:
            self.clear()

    def receive(self, event, client, now):
        self.expire(now)
        if event == "offline":
            self.clients.discard(client)
            if self.owner == client:
                self.clear()
            return
        self.clients.add(client)
        self.seen_online = True
        if event == "online":
            return
        if event == "working":
            self.owner = client
            self.phase = event
            self.deadline = now + 900
        elif event == "need_input" and self.owner in (None, client):
            if self.phase == event:
                return
            if self.owner is None:
                self.deadline = now + 900
            self.owner = client
            self.phase = event
        elif event == "done" and self.owner == client:
            self.clear()
        else:
            return
        return event
