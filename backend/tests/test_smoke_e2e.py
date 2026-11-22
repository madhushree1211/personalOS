import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_login_document_search_supervisor_and_audit_smoke_flow() -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "demo@personalos.ai", "password": "test-demo-password"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    document_text = "Phase seven smoke document with unique phoenix-protocol phrase."
    uploaded = client.post(
        "/api/documents",
        headers=headers,
        json={"filename": "smoke.txt", "text": document_text},
    )
    assert uploaded.status_code == 200

    searched = client.get(
        "/api/documents/search",
        headers=headers,
        params={"q": "phoenix-protocol", "limit": 5},
    )
    assert searched.status_code == 200
    assert searched.json()["results"]

    routed = client.post(
        "/api/supervisor/route",
        headers=headers,
        json={"query": "search my uploaded document for phoenix-protocol"},
    )
    assert routed.status_code == 200

    audit = client.get("/api/audit-log", headers=headers, params={"limit": 100, "offset": 0})
    assert audit.status_code == 200
    entries = audit.json()["entries"]
    events = {entry["event"] for entry in entries}
    assert "document-ingested" in events
    assert "document-searched" in events

    for entry in entries:
        if entry["event"] in {"document-ingested", "document-searched"}:
            assert document_text not in json.dumps(entry["details"])
