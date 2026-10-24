"""Daily usage counters: user IDs/usernames, never query text or OAuth tokens."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import Lock
import time


class UsageStats:
    def __init__(self, path):
        """Open private usage storage and create daily counters and user metadata tables."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        Path(path).chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, first_seen REAL, last_seen REAL);
            CREATE TABLE IF NOT EXISTS daily (day TEXT, user INTEGER, kind TEXT, count INTEGER,
                PRIMARY KEY(day,user,kind));
        ''')

    def record(self, user, kind):
        """Increment an allowed daily event without storing search text or account tokens."""
        if kind not in {'inline','start','current','connect','disconnect'}:
            raise ValueError('Unknown usage event')
        now = time.time();day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with self.lock, self.db:
            self.db.execute('INSERT INTO users VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                            'username=excluded.username,last_seen=excluded.last_seen',
                            (user.id, user.username, now, now))
            self.db.execute('INSERT INTO daily VALUES (?,?,?,1) ON CONFLICT(day,user,kind) '
                            'DO UPDATE SET count=count+1',(day,user.id,kind))

    def report(self):
        """Return aggregate usage and per-user request totals since recording started."""
        with self.lock:
            users=[{'telegram_id':r[0],'username':r[1],'requests':r[2]} for r in self.db.execute(
                'SELECT u.id,u.username,SUM(d.count) FROM users u JOIN daily d ON d.user=u.id '
                'GROUP BY u.id ORDER BY SUM(d.count) DESC,u.id')]
            counts=dict(self.db.execute('SELECT kind,SUM(count) FROM daily GROUP BY kind'))
            started=self.db.execute('SELECT MIN(first_seen) FROM users').fetchone()[0]
        return {'recording_started_utc':datetime.fromtimestamp(started,timezone.utc).isoformat() if started else None,
                'unique_users':len(users),'events':counts,'users':users}

    def close(self):
        """Close the usage statistics database."""
        self.db.close()
