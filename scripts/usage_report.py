"""Read-only local usage report; run on the server, never expose as a public command."""
import argparse
import json
from pathlib import Path
import sqlite3

parser=argparse.ArgumentParser()
parser.add_argument('--db',type=Path,default=Path('data/usage.sqlite3'))
args=parser.parse_args()
with sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True) as db:
    rows=db.execute('SELECT u.id,u.username,SUM(d.count) FROM users u JOIN daily d ON d.user=u.id '
                    'GROUP BY u.id ORDER BY SUM(d.count) DESC,u.id').fetchall()
    print(json.dumps({'unique_users':len(rows),'events':dict(db.execute('SELECT kind,SUM(count) FROM daily GROUP BY kind')),
        'users':[{'telegram_id':r[0],'username':r[1],'requests':r[2]} for r in rows]},ensure_ascii=False,indent=2))
