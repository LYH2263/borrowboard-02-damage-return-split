"""归还两口（预览/确认）+ 解锁 + 借出守卫的接口级对齐测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def item(client, iid):
    return next(i for i in client.get("/api/items").json() if i["id"] == iid)


def test_preview_does_not_touch_items(client):
    r = client.post("/api/loans/1/return/preview", json={"note": "裂了"})
    assert r.status_code == 200
    body = r.json()
    assert body["landing_column"] == "owner" and body["unlock_required"] is True
    # 预览不改 items.status
    assert item(client, 4)["status"] == "on_loan"
    r = client.post("/api/loans/1/return/preview", json={"note": ""})
    assert r.json()["landing_column"] == "available"
    assert item(client, 4)["status"] == "on_loan"


def test_confirm_with_note_parks_in_owner_column(client):
    r = client.post("/api/loans/1/return/confirm", json={"note": "角磕掉一块"})
    assert r.status_code == 200 and r.json()["landing_column"] == "owner"
    b = client.get("/api/board").json()
    # 资格链：可借栏没有它，物主栏有它，顶细条可借数不含它
    assert [i["id"] for i in b["available"]] == [1, 2, 3]
    assert [i["id"] for i in b["owner_hold"]] == [4]
    assert b["owner_hold"][0]["damage_note"] == "角磕掉一块"
    assert b["counts"] == {"available": 3, "owner_hold": 1, "active": 0, "overdue": 0}
    # 已还而顶细条逾期还挂着：不允许（种子借单原逾期，确认后逾期清零）
    assert b["overdue"] == []
    # 待解锁物不可借
    r = client.post("/api/items/4/lend", json={"borrower": "邻居乙", "due_date": "2026-12-31"})
    assert r.status_code == 409
    # 借还记录对齐：已还 + 破损条
    loans = client.get("/api/loans").json()
    assert loans["overdue"] == [] and loans["active"] == []
    ret = loans["returned"][0]
    assert ret["id"] == 1 and ret["damage_note"] == "角磕掉一块" and ret["damage_unlocked_at"] is None


def test_unlock_releases_to_available(client):
    client.post("/api/loans/1/return/confirm", json={"note": "裂了"})
    r = client.post("/api/items/4/unlock")
    assert r.status_code == 200 and r.json()["status"] == "available"
    b = client.get("/api/board").json()
    assert b["owner_hold"] == [] and b["counts"]["available"] == 4 and b["counts"]["owner_hold"] == 0
    # 解锁后可借；借还记录里破损条标记已解锁
    r = client.post("/api/items/4/lend", json={"borrower": "邻居乙", "due_date": "2026-12-31"})
    assert r.status_code == 200
    ret = client.get("/api/loans").json()["returned"][0]
    assert ret["damage_unlocked_at"] is not None


def test_confirm_without_note_then_relend_and_no_double_lend(client):
    r = client.post("/api/loans/1/return/confirm", json={"note": ""})
    assert r.status_code == 200 and r.json()["landing_column"] == "available"
    b = client.get("/api/board").json()
    assert b["counts"]["available"] == 4 and b["counts"]["owner_hold"] == 0
    # 再借成立；第二笔打在已 on_loan 的物上必须 409，不叠单
    r = client.post("/api/items/4/lend", json={"borrower": "邻居乙", "due_date": "2026-12-31"})
    assert r.status_code == 200
    r = client.post("/api/items/4/lend", json={"borrower": "邻居丙", "due_date": "2026-12-31"})
    assert r.status_code == 409
    loans = client.get("/api/loans").json()
    assert len(loans["active"]) == 1 and loans["active"][0]["borrower"] == "邻居乙"


def test_double_confirm_fails_and_dirty_row_not_whitewashed(client):
    assert client.post("/api/loans/1/return/confirm", json={"note": "裂了"}).status_code == 200
    r = client.post("/api/loans/1/return/confirm", json={"note": "再写"})
    assert r.status_code == 400 and r.json()["detail"] == "not_active"
    # 脏数据-无主不被洗白
    dirty = item(client, 3)
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty" and dirty["status"] == "available"
    r = client.post("/api/loans/999/return/confirm", json={"note": "x"})
    assert r.status_code == 404
    dirty = item(client, 3)
    assert dirty["owner"] == "" and dirty["data_quality"] == "dirty"
