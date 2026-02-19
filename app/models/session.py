import time
from collections import deque


class Session:
    def __init__(self, topic: str, duration: int):
        self.topic = topic
        self.duration = duration  # seconds
        self.start_time = time.time()

        self.history = []

        self.current_speaker = "moderator"

        # New additions
        self.hand_raise_queue = deque()
        self.last_activity_time = time.time()
        self.turn_count = 0

    def is_time_over(self):
        return (time.time() - self.start_time) > self.duration

    def is_silence_timeout(self, timeout_seconds=6):
        return (time.time() - self.last_activity_time) > timeout_seconds
