"""数据层：SQLite（WAL），线程安全简易封装。所有时间用本地 ISO 字符串。"""
import sqlite3
import threading
from datetime import datetime

from . import config

_lock = threading.Lock()
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA foreign_keys=ON")


def backup_to(path):
    """把当前数据库完整导出到 path（sqlite3 backup API）。"""
    with _lock:
        dst = sqlite3.connect(path)
        try:
            _conn.backup(dst)
        finally:
            dst.close()


def restore_from(path):
    """用 path 里的数据库完整覆盖当前库（sqlite3 backup API 反向）。"""
    src = sqlite3.connect(path)
    try:
        with _lock:
            src.backup(_conn)
    finally:
        src.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS dramas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, category TEXT, share_rate REAL DEFAULT 0.6,
  status TEXT DEFAULT '在推',           -- 新剧/在推/完结
  is_exclusive INTEGER DEFAULT 0, tags TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS peer_accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE, fans INTEGER DEFAULT 0, style TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS peer_videos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER, drama_id INTEGER, title TEXT, cover_hue INTEGER DEFAULT 200,
  hook_type TEXT DEFAULT '', publish_time TEXT, discovered_at TEXT,
  violation INTEGER DEFAULT 0, track_done INTEGER DEFAULT 0,
  is_late_boom INTEGER DEFAULT 0, UNIQUE(title, account_id));
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id INTEGER, day_index INTEGER,           -- 1/2/3
  play INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, mount_clicks INTEGER,
  captured_at TEXT, UNIQUE(video_id, day_index));
CREATE TABLE IF NOT EXISTS own_videos(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, drama_id INTEGER, publish_time TEXT,
  play INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0,
  finish_rate REAL DEFAULT 0, mount_clicks INTEGER DEFAULT 0,
  conversions INTEGER DEFAULT 0, revenue REAL DEFAULT 0, is_hot INTEGER DEFAULT 0,
  segment_note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS share_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT, drama_id INTEGER, play INTEGER, conversions INTEGER, revenue REAL,
  UNIQUE(day, drama_id));
CREATE TABLE IF NOT EXISTS deconstructions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  own_video_id INTEGER UNIQUE, drama_id INTEGER,
  segments TEXT, factors TEXT, hook_logic TEXT, cross_validation TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS contents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drama_id INTEGER, script TEXT, image_prompt TEXT, title_copy TEXT,
  slot TEXT, template TEXT, status TEXT DEFAULT '待审核',   -- 待审核/已发布/已淘汰
  created_at TEXT);
CREATE TABLE IF NOT EXISTS strategies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drama_id INTEGER, direction TEXT, templates TEXT, fit TEXT,
  status TEXT DEFAULT '生效中', review TEXT DEFAULT '', created_at TEXT);  -- 生效中/已淘汰
CREATE TABLE IF NOT EXISTS experiences(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT, content TEXT, source TEXT, score INTEGER DEFAULT 60,
  week TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS meetings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT UNIQUE, summary TEXT, tasks TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT, level TEXT DEFAULT 'info',            -- info/warn/critical
  content TEXT, created_at TEXT, handled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT, action TEXT, detail TEXT, status TEXT,
  started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS daily_reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT UNIQUE, content TEXT, findings TEXT);
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT, role TEXT,                 -- user / agent
  content TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS group_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sender TEXT,                           -- boss / agent key
  sender_title TEXT, color TEXT DEFAULT '#888',
  think TEXT DEFAULT '',                 -- 深度思考过程
  content TEXT, created_at TEXT);
"""

def init():
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()

def q(sql, p=()):
    with _lock:
        cur = _conn.execute(sql, p)
        return [dict(r) for r in cur.fetchall()]

def one(sql, p=()):
    rows = q(sql, p)
    return rows[0] if rows else None

def ex(sql, p=()):
    with _lock:
        cur = _conn.execute(sql, p)
        _conn.commit()
        return cur.lastrowid

def now():
    return datetime.now().isoformat(timespec="seconds")

def today():
    return datetime.now().strftime("%Y-%m-%d")

def week_of(dt=None):
    dt = dt or datetime.now()
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"
