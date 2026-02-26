import time

# To avoid circular imports, we lazily import db methods or import them here
import app.storage.memory_store as store

class Session:
    def __init__(self, session_id: str, topic: str, duration: int):
        self.session_id = session_id
        self.topic = topic
        self.duration = duration          # seconds
        self.start_time = time.time()
        self.history = []

        # --- Turn control ---
        self.current_speaker: str = "ai"       # "user" | "ai" | "moderator"
        self.hand_raised: bool = False
        self.hand_queue: bool = False
        self.user_turn_granted: bool = False
        self.ai_is_speaking: bool = False

        # --- Session lifecycle ---
        self.is_ended: bool = False            # set True when /end fires; stops new AI tokens

        # --- Silence tracking ---
        self.last_activity_time: float = time.time()

    def is_time_over(self) -> bool:
        return (time.time() - self.start_time) > self.duration

    def reset_activity_clock(self):
        self.last_activity_time = time.time()
        self.save()

    def silence_duration(self) -> float:
        return time.time() - self.last_activity_time

    def add_message(self, role: str, content: str):
        self.history.append((role, content))
        store.add_message_to_db(self.session_id, role, content)

    def save(self):
        print("SESSION_SAVE", self.session_id, self.is_ended, self.current_speaker)
        """Flushes mutated state into SQLite"""
        store.update_session(self)
