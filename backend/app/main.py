from datetime import date, datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed
from app.db import connect, transact
from app.engines.borrow_rules import can_lend, classify_loans
from app.modules import damage_note
from app.modules.damage_note import DamageNoteError

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/board")
def board():
    c = connect()
    available = [dict(r) for r in c.execute("SELECT * FROM items WHERE status='available'")]
    held = [dict(r) for r in c.execute(
        """SELECT items.*, damage_notes.note AS damage_note
           FROM items LEFT JOIN damage_notes
             ON damage_notes.item_id=items.id AND damage_notes.unlocked_at IS NULL
           WHERE items.status='owner_hold'""")]
    loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    c.close()
    cls = classify_loans(loans, date.today().isoformat())
    return {
        "available": available,
        "owner_hold": held,
        "active": cls["active"],
        "overdue": cls["overdue"],
        "counts": {
            "available": len(available),
            "owner_hold": len(held),
            "active": len(cls["active"]),
            "overdue": len(cls["overdue"]),
        },
    }

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                    (body.title, body.owner, "available", "clean"))
    c.commit(); iid = cur.lastrowid; c.close(); return {"id": iid}

class LendIn(BaseModel):
    borrower: str
    due_date: str

def _lend(c, iid: int, body: LendIn) -> dict:
    item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    if not item: raise HTTPException(404, "item")
    active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
    check = can_lend(item["status"], active)
    if not check["ok"]: raise HTTPException(409, check["reason"])
    # 守卫更新：并发下只有一笔能把 available 翻成 on_loan，其余 409，不叠单
    cur = c.execute("UPDATE items SET status='on_loan' WHERE id=? AND status='available'", (iid,))
    if cur.rowcount != 1: raise HTTPException(409, "item_not_available")
    cur = c.execute(
        "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
        (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
    return {"loan_id": cur.lastrowid}

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    c = connect()
    try:
        return transact(c, lambda: _lend(c, iid, body))
    finally:
        c.close()

class ReturnIn(BaseModel):
    note: str = ""

def _get_active_loan(c, lid: int):
    loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
    if not loan: raise HTTPException(404, "loan")
    if loan["status"] != "active": raise HTTPException(400, "not_active")
    return loan

@app.post("/api/loans/{lid}/return/preview")
def return_preview(lid: int, body: ReturnIn):
    """归还预览：只算落点，不改 items.status，不写库。"""
    c = connect()
    try:
        loan = _get_active_loan(c, lid)
        return damage_note.preview_return(dict(loan), body.note)
    finally:
        c.close()

@app.post("/api/loans/{lid}/return/confirm")
def return_confirm(lid: int, body: ReturnIn):
    """确认归还：关单 + 写破损条 + 落物态，全或全无。"""
    c = connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        return transact(c, lambda: damage_note.confirm_return(c, lid, body.note, now))
    except DamageNoteError as e:
        raise HTTPException(e.status, e.reason)
    finally:
        c.close()

@app.post("/api/items/{iid}/unlock")
def unlock(iid: int):
    """物主栏解锁：owner_hold → available，破损条了结。"""
    c = connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        return transact(c, lambda: damage_note.unlock_item(c, iid, now))
    except DamageNoteError as e:
        raise HTTPException(e.status, e.reason)
    finally:
        c.close()

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title,
                  damage_notes.note AS damage_note, damage_notes.unlocked_at AS damage_unlocked_at
           FROM loans JOIN items ON items.id=loans.item_id
           LEFT JOIN damage_notes ON damage_notes.loan_id=loans.id
           ORDER BY loans.id DESC""")]
    c.close()
    return classify_loans(rows, date.today().isoformat())

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
