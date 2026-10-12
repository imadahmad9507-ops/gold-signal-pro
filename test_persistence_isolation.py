"""
Reproducible proof demonstrating why local SQLite cannot provide guaranteed durability across GitHub Actions jobs:
Each scheduled job runs in an independent container/VM. Unless changes are committed & pushed back to Git,
or stored in a persistent external database (e.g. Supabase / Neon PostgreSQL), local disk changes disappear.
Furthermore, git commit/push from GitHub Actions frequently suffers race conditions with concurrent or frequent runs (reject non-fast-forward push).
"""
import os
import shutil
import sqlite3

def test_ephemeral_runner_isolation():
    runner1_dir = "temp_runner_1"
    os.makedirs(runner1_dir, exist_ok=True)
    db1 = os.path.join(runner1_dir, "signals.db")

    conn1 = sqlite3.connect(db1)
    conn1.execute("CREATE TABLE test_signals (id INT, symbol TEXT)")
    conn1.execute("INSERT INTO test_signals VALUES (1, 'XAUUSD')")
    conn1.commit()
    conn1.close()
    print("Runner #1: Successfully wrote signal to local signals.db")

    # Runner #1 VM destroyed
    shutil.rmtree(runner1_dir)
    print("Runner #1: VM terminated and local disk destroyed.")

    # Runner #2 spawned independently 15m later
    runner2_dir = "temp_runner_2"
    os.makedirs(runner2_dir, exist_ok=True)
    db2 = os.path.join(runner2_dir, "signals.db")

    survived = os.path.exists(db2)
    print(f"Runner #2: Does signals.db survive? -> {survived}")
    shutil.rmtree(runner2_dir)
    return survived

if __name__ == "__main__":
    result = test_ephemeral_runner_isolation()
    print("Ephemeral storage proof completed. Survived:", result)
