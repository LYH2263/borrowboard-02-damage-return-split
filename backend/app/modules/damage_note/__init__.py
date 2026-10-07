"""破损条：归还时可附破损说明。

资格链（唯一一条）：确认归还后，带破损的物先停物主栏待解锁
（items.status='damaged_hold'，不可借、不计入顶细条可借数），
物主解锁后才回可借栏；无破损则直接回可借栏。
预览只算不写，确认在同一事务内落：破损条 + 关单 + 物状态。
"""

DAMAGED_HOLD = "damaged_hold"


def ensure_table(c):
    c.execute("""
    CREATE TABLE IF NOT EXISTS damage_notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      loan_id INT NOT NULL,
      item_id INT NOT NULL,
      note TEXT NOT NULL,
      created_at TEXT NOT NULL
    )""")


def plan_return(note: str) -> dict:
    """预览与确认共用同一条资格链，保证看到什么就落什么。"""
    damage = bool((note or "").strip())
    return {"damage": damage, "next_status": DAMAGED_HOLD if damage else "available"}


def apply_return(c, loan, note: str, now: str) -> dict:
    """在调用方的事务内落单；任何一步失败由调用方整体回滚，不留半单。"""
    plan = plan_return(note)
    if plan["damage"]:
        c.execute(
            "INSERT INTO damage_notes(loan_id,item_id,note,created_at) VALUES (?,?,?,?)",
            (loan["id"], loan["item_id"], note.strip(), now))
    c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=? AND status='active'",
              (now, loan["id"]))
    c.execute("UPDATE items SET status=? WHERE id=?", (plan["next_status"], loan["item_id"]))
    return plan
