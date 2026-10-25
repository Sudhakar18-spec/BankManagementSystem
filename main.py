"""Bank Management System - run with:  python main.py"""
from getpass import getpass

from bank import services as bank
from bank.database import init_db
from bank.services import BankError, fmt


def ask(prompt):
    return input(prompt).strip()


def safe(fn, *args):
    """Run a bank operation and print errors nicely."""
    try:
        return fn(*args)
    except BankError as e:
        print(f"  ✗ {e}")
    except KeyboardInterrupt:
        raise
    return None


def pick_account(user):
    accounts = bank.get_accounts(user["id"])
    if not accounts:
        print("  You have no open accounts.")
        return None
    if len(accounts) == 1:
        return accounts[0]["acc_no"]
    for i, a in enumerate(accounts, 1):
        print(f"  {i}. {a['acc_no']}  {a['acc_type']:<8} {fmt(a['balance'])}  [{a['status']}]")
    choice = ask("Select account: ")
    if choice.isdigit() and 1 <= int(choice) <= len(accounts):
        return accounts[int(choice) - 1]["acc_no"]
    print("  ✗ Invalid choice.")
    return None


def register_flow():
    print("\n--- Open New Account ---")
    name, phone = ask("Full name: "), ask("Phone (login id): ")
    pin = getpass("Set 4-digit PIN: ")
    acc_type = ask("Type (SAVINGS min 500 / CURRENT): ").upper() or "SAVINGS"
    opening = ask("Opening deposit: ")
    acc_no = safe(bank.register, name, phone, pin, acc_type, opening)
    if acc_no:
        print(f"  ✓ Account created! Your account number: {acc_no}")


def customer_menu(user):
    while True:
        print(f"\n=== Welcome, {user['name']} ===")
        print("1 Balance   2 Deposit   3 Withdraw   4 Transfer   5 Mini statement")
        print("6 Export CSV statement   7 Change PIN   8 Open another account")
        print("9 Close account   0 Logout")
        c = ask("Choose: ")
        if c == "0":
            return
        if c == "7":
            if safe(bank.change_pin, user["id"], getpass("Current PIN: "), getpass("New PIN: ")) is None:
                print("  ✗ Failed to change PIN.")
            else:
                print("  ✓ PIN changed.")
            continue
        if c == "8":
            acc = safe(bank.open_another_account, user["id"], ask("Type (SAVINGS/CURRENT): "), ask("Opening deposit: "))
            if acc:
                print(f"  ✓ New account: {acc}")
            continue
        if c not in "123456789":
            print("  ✗ Invalid option.")
            continue
        acc_no = pick_account(user)
        if not acc_no:
            continue
        if c == "1":
            for a in bank.get_accounts(user["id"]):
                if a["acc_no"] == acc_no:
                    print(f"  Balance: {fmt(a['balance'])}")
        elif c == "2":
            bal = safe(bank.deposit, acc_no, ask("Amount: "))
            if bal is not None: print(f"  ✓ Deposited. New balance: {fmt(bal)}")
        elif c == "3":
            bal = safe(bank.withdraw, acc_no, ask("Amount: "))
            if bal is not None: print(f"  ✓ Withdrawn. New balance: {fmt(bal)}")
        elif c == "4":
            to = ask("Destination account no: ")
            bal = safe(bank.transfer, acc_no, to, ask("Amount: "), ask("Note (optional): "))
            if bal is not None: print(f"  ✓ Transferred. New balance: {fmt(bal)}")
        elif c == "5":
            print(f"\n  {'Date':<20}{'Type':<14}{'Amount':>12}{'Balance':>14}  Note")
            for t in bank.history(acc_no):
                print(f"  {t['created_at']:<20}{t['tx_type']:<14}{fmt(t['amount']):>12}{fmt(t['balance_after']):>14}  {t['note']}")
        elif c == "6":
            path = f"statement_{acc_no}.csv"
            n = bank.export_statement(acc_no, path)
            print(f"  ✓ {n} transactions saved to {path}")
        elif c == "9":
            if ask("Type YES to close this account: ") == "YES":
                if safe(bank.close_account, acc_no, user["id"]) is None:
                    pass
                else:
                    print("  ✓ Account closed.")


def admin_menu():
    while True:
        print("\n=== ADMIN PANEL ===")
        print("1 List accounts  2 Freeze  3 Unfreeze  4 Apply monthly interest")
        print("5 Bank summary   6 Unlock user   0 Logout")
        c = ask("Choose: ")
        if c == "0":
            return
        if c == "1":
            for a in bank.all_accounts():
                lock = " (USER LOCKED)" if a["locked"] else ""
                print(f"  {a['acc_no']}  {a['name']:<18}{a['phone']:<13}{a['acc_type']:<8}{fmt(a['balance']):>14}  {a['status']}{lock}")
        elif c in ("2", "3"):
            status = "FROZEN" if c == "2" else "ACTIVE"
            if safe(bank.set_status, ask("Account no: "), status) is None:
                pass
            else:
                print(f"  ✓ Account set to {status}.")
        elif c == "4":
            print(f"  ✓ Interest credited to {bank.apply_interest()} savings account(s).")
        elif c == "5":
            s = bank.summary()
            print(f"  Open accounts: {s['accounts']}   Total deposits: {fmt(s['total'])}")
        elif c == "6":
            if safe(bank.unlock_user, ask("User phone: ")) is None:
                pass
            else:
                print("  ✓ User unlocked.")


def main():
    init_db()
    while True:
        print("\n==============================")
        print("   BANK MANAGEMENT SYSTEM")
        print("==============================")
        print("1 Open account   2 Customer login   3 Admin login   0 Exit")
        c = ask("Choose: ")
        if c == "1":
            register_flow()
        elif c == "2":
            user = safe(bank.authenticate, ask("Phone: "), getpass("PIN: "))
            if user:
                customer_menu(user)
        elif c == "3":
            user = safe(bank.authenticate, ask("Admin id: "), getpass("PIN: "), "ADMIN")
            if user:
                admin_menu()
        elif c == "0":
            print("Goodbye!")
            break
        else:
            print("  ✗ Invalid option.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nGoodbye!")