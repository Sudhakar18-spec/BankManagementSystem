import os
import sqlite3

from .security import hash_pin

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bank.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'CUSTOMER',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS accounts (
    acc_no TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    acc_type TEXT NOT NULL,
    balance INTEGER NOT NULL DEFAULT 0,   -- stored in cents (no float errors)
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acc_no TEXT NOT NULL REFERENCES accounts(acc_no),
    tx_type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM users WHERE role='ADMIN'").fetchone():
            h, s = hash_pin("0000")
            conn.execute(
                "INSERT INTO users (name, phone, pin_hash, salt, role) VALUES (?,?,?,?,'ADMIN')",
                ("Administrator", "admin", h, s),
            )