import csv
import random
from decimal import Decimal, InvalidOperation

from .database import get_conn
from .security import hash_pin, verify_pin

MIN_BALANCE = {"SAVINGS": 50_000, "CURRENT": 0}   # cents
DAILY_WITHDRAW_LIMIT = 5_000_000                  # 50,000.00
SAVINGS_RATE = Decimal("0.04")                    # 4% yearly
MAX_ATTEMPTS = 3


class BankError(Exception):
    """Any business-rule problem shown to the user."""


# ---------- helpers ----------
def to_cents(text) -> int:
    try:
        value = Decimal(str(text).strip())
    except InvalidOperation:
        raise BankError("Invalid amount.")
    if value <= 0 or value != value.quantize(Decimal("0.01")):
        raise BankError("Amount must be positive with max 2 decimals.")
    return int(value * 100)


def fmt(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def _log(conn, acc_no, tx_type, amount, balance_after, note=""):
    conn.execute(
        "INSERT INTO transactions (acc_no, tx_type, amount, balance_after, note) VALUES (?,?,?,?,?)",
        (acc_no, tx_type, amount, balance_after, note),
    )


def _new_acc_no(conn):
    while True:
        acc_no = "BK" + "".join(random.choices("0123456789", k=10))
        if not conn.execute("SELECT 1 FROM accounts WHERE acc_no=?", (acc_no,)).fetchone():
            return acc_no


def _get_active(conn, acc_no):
    acc = conn.execute("SELECT * FROM accounts WHERE acc_no=?", (acc_no,)).fetchone()
    if not acc:
        raise BankError(f"Account {acc_no} not found.")
    if acc["status"] != "ACTIVE":
        raise BankError(f"Account {acc_no} is {acc['status']}.")
    return acc


def _create_account(conn, user_id, acc_type, opening):
    acc_type = acc_type.upper()
    if acc_type not in MIN_BALANCE:
        raise BankError("Account type must be SAVINGS or CURRENT.")
    if opening < MIN_BALANCE[acc_type]:
        raise BankError(f"{acc_type} needs an opening deposit of at least {fmt(MIN_BALANCE[acc_type])}.")
    acc_no = _new_acc_no(conn)
    conn.execute("INSERT INTO accounts (acc_no, user_id, acc_type, balance) VALUES (?,?,?,?)",
                 (acc_no, user_id, acc_type, opening))
    if opening:
        _log(conn, acc_no, "DEPOSIT", opening, opening, "Opening deposit")
    return acc_no


# ---------- customers ----------
def register(name, phone, pin, acc_type, opening_text):
    if not name.strip():
        raise BankError("Name is required.")
    if not (phone.isdigit() and 8 <= len(phone) <= 15):
        raise BankError("Phone must be 8-15 digits.")
    if not (pin.isdigit() and len(pin) == 4):
        raise BankError("PIN must be exactly 4 digits.")
    opening = to_cents(opening_text) if opening_text.strip() not in ("", "0") else 0
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone():
            raise BankError("Phone number already registered.")
        h, s = hash_pin(pin)
        cur = conn.execute("INSERT INTO users (name, phone, pin_hash, salt) VALUES (?,?,?,?)",
                           (name.strip(), phone, h, s))
        return _create_account(conn, cur.lastrowid, acc_type, opening)


def authenticate(phone, pin, role="CUSTOMER"):
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE phone=? AND role=?", (phone, role)).fetchone()
        if not user:
            raise BankError("Invalid phone or PIN.")
        if user["locked"]:
            raise BankError("User is locked after too many wrong PINs. Contact admin.")
        if verify_pin(pin, user["pin_hash"], user["salt"]):
            conn.execute("UPDATE users SET failed_attempts=0 WHERE id=?", (user["id"],))
            return dict(user)
        attempts = user["failed_attempts"] + 1
        locked = 1 if attempts >= MAX_ATTEMPTS else 0
        conn.execute("UPDATE users SET failed_attempts=?, locked=? WHERE id=?", (attempts, locked, user["id"]))
    raise BankError("User locked." if locked else f"Invalid PIN. {MAX_ATTEMPTS - attempts} attempt(s) left.")


def change_pin(user_id, old, new):
    if not (new.isdigit() and len(new) == 4):
        raise BankError("New PIN must be exactly 4 digits.")
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not verify_pin(old, user["pin_hash"], user["salt"]):
            raise BankError("Current PIN is wrong.")
        h, s = hash_pin(new)
        conn.execute("UPDATE users SET pin_hash=?, salt=? WHERE id=?", (h, s, user_id))


def open_another_account(user_id, acc_type, opening_text):
    opening = to_cents(opening_text) if opening_text.strip() not in ("", "0") else 0
    with get_conn() as conn:
        return _create_account(conn, user_id, acc_type, opening)


def get_accounts(user_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM accounts WHERE user_id=? AND status!='CLOSED' ORDER BY created_at", (user_id,))]


# ---------- money operations ----------
def deposit(acc_no, amount_text):
    amount = to_cents(amount_text)
    with get_conn() as conn:
        acc = _get_active(conn, acc_no)
        new_bal = acc["balance"] + amount
        conn.execute("UPDATE accounts SET balance=? WHERE acc_no=?", (new_bal, acc_no))
        _log(conn, acc_no, "DEPOSIT", amount, new_bal, "Cash deposit")
        return new_bal


def withdraw(acc_no, amount_text):
    amount = to_cents(amount_text)
    with get_conn() as conn:
        acc = _get_active(conn, acc_no)
        if acc["balance"] - amount < MIN_BALANCE[acc["acc_type"]]:
            raise BankError("Insufficient funds (minimum balance rule applies).")
        today = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE acc_no=? AND tx_type='WITHDRAW' "
            "AND date(created_at)=date('now','localtime')", (acc_no,)).fetchone()[0]
        if today + amount > DAILY_WITHDRAW_LIMIT:
            raise BankError(f"Daily withdrawal limit {fmt(DAILY_WITHDRAW_LIMIT)} exceeded.")
        new_bal = acc["balance"] - amount
        conn.execute("UPDATE accounts SET balance=? WHERE acc_no=?", (new_bal, acc_no))
        _log(conn, acc_no, "WITHDRAW", amount, new_bal, "Cash withdrawal")
        return new_bal


def transfer(from_acc, to_acc, amount_text, note=""):
    amount = to_cents(amount_text)
    if from_acc == to_acc:
        raise BankError("Cannot transfer to the same account.")
    with get_conn() as conn:   # one transaction: all-or-nothing
        src = _get_active(conn, from_acc)
        dst = _get_active(conn, to_acc)
        if src["balance"] - amount < MIN_BALANCE[src["acc_type"]]:
            raise BankError("Insufficient funds (minimum balance rule applies).")
        src_bal, dst_bal = src["balance"] - amount, dst["balance"] + amount
        conn.execute("UPDATE accounts SET balance=? WHERE acc_no=?", (src_bal, from_acc))
        conn.execute("UPDATE accounts SET balance=? WHERE acc_no=?", (dst_bal, to_acc))
        _log(conn, from_acc, "TRANSFER_OUT", amount, src_bal, f"To {to_acc} {note}".strip())
        _log(conn, to_acc, "TRANSFER_IN", amount, dst_bal, f"From {from_acc} {note}".strip())
        return src_bal


def history(acc_no, limit=10):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM transactions WHERE acc_no=? ORDER BY id DESC LIMIT ?", (acc_no, limit))]


def export_statement(acc_no, path):
    rows = history(acc_no, limit=100000)[::-1]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Type", "Amount", "Balance After", "Note"])
        for r in rows:
            w.writerow([r["created_at"], r["tx_type"], fmt(r["amount"]), fmt(r["balance_after"]), r["note"]])
    return len(rows)


def close_account(acc_no, user_id):
    with get_conn() as conn:
        acc = _get_active(conn, acc_no)
        if acc["user_id"] != user_id:
            raise BankError("Not your account.")
        if acc["balance"] != 0:
            raise BankError("Withdraw or transfer the remaining balance before closing.")
        conn.execute("UPDATE accounts SET status='CLOSED' WHERE acc_no=?", (acc_no,))


# ---------- admin ----------
def all_accounts():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT a.*, u.name, u.phone, u.locked FROM accounts a JOIN users u ON u.id=a.user_id "
            "ORDER BY a.created_at")]


def set_status(acc_no, status):
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM accounts WHERE acc_no=?", (acc_no,)).fetchone():
            raise BankError("Account not found.")
        conn.execute("UPDATE accounts SET status=? WHERE acc_no=?", (status, acc_no))


def unlock_user(phone):
    with get_conn() as conn:
        cur = conn.execute("UPDATE users SET locked=0, failed_attempts=0 WHERE phone=?", (phone,))
        if cur.rowcount == 0:
            raise BankError("User not found.")


def apply_interest():
    count = 0
    with get_conn() as conn:
        for acc in conn.execute("SELECT * FROM accounts WHERE acc_type='SAVINGS' AND status='ACTIVE'").fetchall():
            interest = int((Decimal(acc["balance"]) * SAVINGS_RATE / 12).quantize(Decimal("1")))
            if interest > 0:
                new_bal = acc["balance"] + interest
                conn.execute("UPDATE accounts SET balance=? WHERE acc_no=?", (new_bal, acc["acc_no"]))
                _log(conn, acc["acc_no"], "INTEREST", interest, new_bal, "Monthly interest")
                count += 1
    return count


def summary():
    with get_conn() as conn:
        return dict(conn.execute(
            "SELECT COUNT(*) AS accounts, COALESCE(SUM(balance),0) AS total FROM accounts WHERE status!='CLOSED'"
        ).fetchone())