"""破损条模块：资格链落点、确认归还事务、解锁、脏数据不洗白。"""
import pytest

from app import seed
from app.db import connect, transact
from app.engines.borrow_rules import can_lend
from app.modules import damage_note
from app.modules.damage_note import DamageNoteError

NOW = "2026-10-07T00:00:00+00:00"
# 种子：1 电钻 / 2 折叠桌 / 3 脏数据-无主(dirty,owner='') 可借；4 已外借样例 on_loan，借单 1 活跃且逾期


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()


def one(sql, args=()):
    c = connect(); r = c.execute(sql, args).fetchone(); c.close(); return r


def ids(sql, args=()):
    c = connect(); r = [row["id"] for row in c.execute(sql, args)]; c.close(); return r


def confirm(lid, note, now=NOW):
    c = connect()
    try:
        return transact(c, lambda: damage_note.confirm_return(c, lid, note, now))
    finally:
        c.close()


def unlock(iid, now=NOW):
    c = connect()
    try:
        return transact(c, lambda: damage_note.unlock_item(c, iid, now))
    finally:
        c.close()


def test_landing_chain():
    assert damage_note.landing_status("角磕掉一块") == "owner_hold"
    assert damage_note.landing_status("") == "available"
    assert damage_note.landing_status("   ") == "available"
    assert damage_note.landing_status(None) == "available"
    # 资格链：owner_hold 不可借，可借栏/物主栏/顶细条同跟 items.status
    assert not can_lend("owner_hold", 0)["ok"]
    assert can_lend("available", 0)["ok"]


def test_preview_is_pure(db):
    loan = one("SELECT * FROM loans WHERE id=1")
    p = damage_note.preview_return(dict(loan), "裂了")
    assert p["landing_status"] == "owner_hold" and p["landing_column"] == "owner"
    assert p["unlock_required"] is True
    p2 = damage_note.preview_return(dict(loan), "")
    assert p2["landing_status"] == "available" and p2["landing_column"] == "available"
    # 预览不改 items.status、不落库
    assert one("SELECT status FROM items WHERE id=4")["status"] == "on_loan"
    assert one("SELECT COUNT(*) c FROM damage_notes")["c"] == 0


def test_confirm_with_note_holds_in_owner_column(db):
    r = confirm(1, "角磕掉一块")
    assert r["landing_status"] == "owner_hold" and r["damage_note_id"]
    loan = one("SELECT * FROM loans WHERE id=1")
    assert loan["status"] == "returned" and loan["returned_at"] == NOW
    assert one("SELECT status FROM items WHERE id=4")["status"] == "owner_hold"
    note = one("SELECT * FROM damage_notes WHERE loan_id=1")
    assert note["item_id"] == 4 and note["note"] == "角磕掉一块" and note["unlocked_at"] is None
    # 可借栏不含待解锁物
    assert ids("SELECT id FROM items WHERE status='available'") == [1, 2, 3]


def test_confirm_without_note_back_to_available(db):
    r = confirm(1, "")
    assert r["landing_status"] == "available" and r["damage_note_id"] is None
    assert one("SELECT status FROM items WHERE id=4")["status"] == "available"
    assert one("SELECT COUNT(*) c FROM damage_notes")["c"] == 0


def test_unlock_releases_to_available(db):
    confirm(1, "裂了")
    r = unlock(4)
    assert r["status"] == "available"
    assert one("SELECT status FROM items WHERE id=4")["status"] == "available"
    assert one("SELECT unlocked_at FROM damage_notes WHERE loan_id=1")["unlocked_at"] == NOW
    with pytest.raises(DamageNoteError) as e:
        unlock(4)
    assert e.value.status == 409 and e.value.reason == "not_held"


def test_double_return_fails_and_dirty_row_not_whitewashed(db):
    confirm(1, "裂了")
    with pytest.raises(DamageNoteError) as e:
        confirm(1, "再写一条")
    assert e.value.status == 400 and e.value.reason == "not_active"
    # 脏数据-无主不被洗白：owner 仍空、data_quality 仍 dirty
    dirty = one("SELECT * FROM items WHERE id=3")
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty" and dirty["status"] == "available"
    # 失败的第二笔不留半笔：借单仍已还、破损条仍只有一条
    assert one("SELECT status FROM loans WHERE id=1")["status"] == "returned"
    assert one("SELECT COUNT(*) c FROM damage_notes")["c"] == 1


def test_return_unknown_loan_has_no_side_effects(db):
    with pytest.raises(DamageNoteError) as e:
        confirm(999, "x")
    assert e.value.status == 404
    dirty = one("SELECT * FROM items WHERE id=3")
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty"
    assert one("SELECT COUNT(*) c FROM damage_notes")["c"] == 0


def test_confirm_rolls_back_when_item_not_on_loan(db):
    # 模拟漂移：借单还 active 但物态不是 on_loan —— 禁止破损条已写、可借栏已放出、借单仍挂 on_loan
    c = connect()
    c.execute("UPDATE items SET status='available' WHERE id=4")
    c.commit(); c.close()
    with pytest.raises(DamageNoteError) as e:
        confirm(1, "裂了")
    assert e.value.status == 409 and e.value.reason == "item_not_on_loan"
    # 全或全无：借单仍 active、无破损条、脏数据原样
    assert one("SELECT status FROM loans WHERE id=1")["status"] == "active"
    assert one("SELECT COUNT(*) c FROM damage_notes")["c"] == 0
    dirty = one("SELECT * FROM items WHERE id=3")
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty"
