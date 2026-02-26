import sqlite3
import json
import logging
from app.models.session import Session

DB_PATH = "sessions.db"

# Cache active sessions in memory so concurrent streaming requests share the same object reference
_active_sessions_cache = {}

logger = logging.getLogger(__name__)


def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    topic TEXT,
                    duration INTEGER,
                    start_time REAL,
                    current_speaker TEXT,
                    hand_raised BOOLEAN,
                    hand_queue BOOLEAN,
                    user_turn_granted BOOLEAN,
                    ai_is_speaking BOOLEAN,
                    is_ended BOOLEAN,
                    last_activity_time REAL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            ''')
            conn.commit()
            logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")


def create_session(session_id: str, topic: str, duration: int):
    session = Session(session_id, topic, duration)
    _active_sessions_cache[session_id] = session

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sessions (
                    id, topic, duration, start_time, current_speaker, hand_raised,
                    hand_queue, user_turn_granted, ai_is_speaking, is_ended, last_activity_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, topic, duration, session.start_time, session.current_speaker,
                session.hand_raised, session.hand_queue, session.user_turn_granted,
                session.ai_is_speaking, session.is_ended, session.last_activity_time
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Error creating session in DB: {e}")


def _load_session_from_db(session_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()

            if not row:
                return None

            # row corresponds to the SELECT layout
            (s_id, topic, duration, start_time, current_speaker, hand_raised,
             hand_queue, user_turn_granted, ai_is_speaking, is_ended, last_activity_time) = row

            session = Session(session_id, topic, duration)
            session.start_time = start_time
            session.current_speaker = current_speaker
            session.hand_raised = bool(hand_raised)
            session.hand_queue = bool(hand_queue)
            session.user_turn_granted = bool(user_turn_granted)
            session.ai_is_speaking = bool(ai_is_speaking)
            session.is_ended = bool(is_ended)
            session.last_activity_time = last_activity_time

            # Load history
            cursor.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
            messages = cursor.fetchall()
            session.history = [(r, c) for r, c in messages]

            _active_sessions_cache[session_id] = session
            return session
    except Exception as e:
        logger.error(f"Error loading session from DB: {e}")
        return None


def get_session(session_id: str):
    # Check memory cache first for shared object reference
    if session_id in _active_sessions_cache:
        return _active_sessions_cache[session_id]
    
    # Not in cache (e.g., server restarted) - load from DB
    return _load_session_from_db(session_id)


def update_session(session: Session):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE sessions SET 
                    current_speaker = ?, 
                    hand_raised = ?, 
                    hand_queue = ?, 
                    user_turn_granted = ?, 
                    ai_is_speaking = ?, 
                    is_ended = ?, 
                    last_activity_time = ?
                WHERE id = ?
            ''', (
                session.current_speaker, 
                session.hand_raised, 
                session.hand_queue, 
                session.user_turn_granted, 
                session.ai_is_speaking, 
                session.is_ended, 
                session.last_activity_time,
                session.session_id
            ))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating session in DB: {e}")


def add_message_to_db(session_id: str, role: str, content: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO messages (session_id, role, content)
                VALUES (?, ?, ?)
            ''', (session_id, role, content))
            conn.commit()
    except Exception as e:
        logger.error(f"Error adding message to DB: {e}")


def delete_session(session_id: str):
    if session_id in _active_sessions_cache:
        del _active_sessions_cache[session_id]
        
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error deleting session from DB: {e}")
