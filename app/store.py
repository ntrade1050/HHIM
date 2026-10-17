"""SQLite: conversation history, processed-message ids, and reply counts."""
import sqlite3
import threading
import time


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, channel TEXT, contact TEXT,
                    role TEXT, text TEXT, ts REAL);
                CREATE INDEX IF NOT EXISTS turns_contact ON turns(channel, contact, ts);
                CREATE TABLE IF NOT EXISTS processed (key TEXT PRIMARY KEY, ts REAL);
                CREATE TABLE IF NOT EXISTS sends (channel TEXT, contact TEXT, ts REAL);
                """
            )

    def claim(self, key: str) -> bool:
        """Mark a message as handled. False if it was already handled (dedupe/retries)."""
        with self._lock:
            try:
                self._db.execute("INSERT INTO processed VALUES (?, ?)", (key, time.time()))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def add_turn(self, channel: str, contact: str, role: str, text: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO turns(channel, contact, role, text, ts) VALUES (?,?,?,?,?)",
                (channel, contact, role, text, time.time()),
            )
            self._db.commit()

    def history(self, channel: str, contact: str, limit: int = 12) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, text FROM turns WHERE channel=? AND contact=? ORDER BY ts DESC LIMIT ?",
                (channel, contact, limit),
            ).fetchall()
        return [{"role": r, "content": t} for r, t in reversed(rows)]

    def record_send(self, channel: str, contact: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO sends VALUES (?,?,?)", (channel, contact, time.time()))
            self._db.commit()

    def sends_last_day(self, channel: str, contact: str) -> int:
        with self._lock:
            (n,) = self._db.execute(
                "SELECT COUNT(*) FROM sends WHERE channel=? AND contact=? AND ts>?",
                (channel, contact, time.time() - 86400),
            ).fetchone()
        return n
