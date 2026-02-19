import time


class Session:
    def __init__(self, topic: str, duration: int):
        self.topic = topic
        self.duration = duration  # seconds
        self.start_time = time.time()
        self.history = []
        self.current_speaker = "moderator"
        self.hand_raised = False

    def is_time_over(self):
        return (time.time() - self.start_time) > self.duration
