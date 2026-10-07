"""破损条：归还时可附破损说明，确认后落一条资格链。

落点（二选一，本模块落第一条）：
  - 无破损说明 → 物直接回可借栏（status='available'）
  - 有破损说明 → 物先停物主栏待解锁（status='owner_hold'），解锁后才可借

可借栏、物主栏、顶细条可借数都只跟 items.status 这一条链走，不另开状态。
预览（preview_return）是纯函数，不改 items.status，不落任何库。
确认（confirm_return）与解锁（unlock_item）必须在事务里调（见 db.transact），
关单 / 写破损条 / 落物态全或全无：不允许破损条已写、可借栏已放出，
而借单还挂在 on_loan 上。
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS damage_notes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  loan_id INTEGER NOT NULL,
  item_id INTEGER NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL,
  unlocked_at TEXT
);
"""

AVAILABLE_STATUS = "available"  # 可借栏
HELD_STATUS = "owner_hold"      # 物主栏 · 待解锁


class DamageNoteError(Exception):
    """业务失败；status/reason 由接口层映射成 HTTP 响应。事务由调用方回滚。"""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def ensure_schema(c) -> None:
    c.executescript(SCHEMA)


def clean_note(note) -> str:
    return (note or "").strip()


def landing_status(note) -> str:
    """资格链落点：有破损说明 → 停物主栏待解锁；否则直接回可借栏。"""
    return HELD_STATUS if clean_note(note) else AVAILABLE_STATUS


def landing_column(status: str) -> str:
    return "owner" if status == HELD_STATUS else "available"


def preview_return(loan: dict, note) -> dict:
    """归还预览：只算落点，不改 items.status，不写库。"""
    landing = landing_status(note)
    return {
        "loan_id": loan["id"],
        "item_id": loan["item_id"],
        "note": clean_note(note),
        "landing_status": landing,
        "landing_column": landing_column(landing),
        "unlock_required": landing == HELD_STATUS,
    }


def confirm_return(c, loan_id: int, note, now: str) -> dict:
    """确认归还：关借单 + （有破损则）写破损条 + 落物态，全或全无。

    物态更新带 status='on_loan' 守卫：物不在借则整笔失败，
    由调用方回滚——已写的破损条、已关的借单一并撤销，不留半笔。
    """
    loan = c.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
    if not loan:
        raise DamageNoteError(404, "loan")
    if loan["status"] != "active":
        raise DamageNoteError(400, "not_active")
    cur = c.execute(
        "UPDATE loans SET status='returned', returned_at=? WHERE id=? AND status='active'",
        (now, loan_id))
    if cur.rowcount != 1:
        raise DamageNoteError(409, "not_active")
    text = clean_note(note)
    landing = landing_status(text)
    cur = c.execute(
        "UPDATE items SET status=? WHERE id=? AND status='on_loan'",
        (landing, loan["item_id"]))
    if cur.rowcount != 1:
        raise DamageNoteError(409, "item_not_on_loan")
    note_id = None
    if text:
        note_id = c.execute(
            "INSERT INTO damage_notes(loan_id,item_id,note,created_at) VALUES (?,?,?,?)",
            (loan_id, loan["item_id"], text, now)).lastrowid
    return {
        "ok": True,
        "loan_id": loan_id,
        "item_id": loan["item_id"],
        "landing_status": landing,
        "landing_column": landing_column(landing),
        "unlock_required": landing == HELD_STATUS,
        "damage_note_id": note_id,
    }


def unlock_item(c, item_id: int, now: str) -> dict:
    """物主栏解锁：owner_hold → available，同时了结对应该物的未解破损条。"""
    item = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not item:
        raise DamageNoteError(404, "item")
    cur = c.execute(
        "UPDATE items SET status='available' WHERE id=? AND status=?",
        (item_id, HELD_STATUS))
    if cur.rowcount != 1:
        raise DamageNoteError(409, "not_held")
    c.execute(
        "UPDATE damage_notes SET unlocked_at=? WHERE item_id=? AND unlocked_at IS NULL",
        (now, item_id))
    return {"ok": True, "item_id": item_id, "status": AVAILABLE_STATUS}
