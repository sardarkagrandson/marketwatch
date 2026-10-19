from datetime import date, timedelta

import pytest

from app import licensing
from app.config import get_settings


@pytest.fixture
def keys():
    return licensing.generate_keypair()  # (private_pem, public_b64)


def test_issue_and_verify(keys):
    priv, pub = keys
    tok = licensing.issue_token(priv, "ab12-cd34-ef56-7890", "Ravi", days=30)
    assert tok.startswith("SOD1.")
    info = licensing.verify_token(tok, pub, device_id="AB12-CD34-EF56-7890")
    assert info.name == "Ravi" and info.device_id == "AB12-CD34-EF56-7890"
    assert info.expires == (date.today() + timedelta(days=30)).isoformat()
    assert licensing.verify_token(licensing.issue_token(priv, "X", "No expiry", days=None), pub).expires is None


def test_rejects_wrong_device_signature_and_expiry(keys):
    priv, pub = keys
    tok = licensing.issue_token(priv, "AAAA-0000", "Ravi", days=10)
    with pytest.raises(licensing.LicenseError, match="valid for device"):
        licensing.verify_token(tok, pub, device_id="BBBB-1111")
    _, other_pub = licensing.generate_keypair()
    with pytest.raises(licensing.LicenseError, match="signature"):
        licensing.verify_token(tok, other_pub)
    with pytest.raises(licensing.LicenseError, match="expired"):
        licensing.verify_token(tok, pub, today=date.today() + timedelta(days=11))
    body, sig = tok[5:].split(".")
    tampered = "SOD1." + body[:-2] + "AA." + sig
    with pytest.raises(licensing.LicenseError):
        licensing.verify_token(tampered, pub)
    with pytest.raises(licensing.LicenseError):
        licensing.verify_token("hello", pub)


def test_device_id_is_stable():
    a = licensing.get_or_create_device_id()
    b = licensing.get_or_create_device_id()
    assert a == b and len(a) == 19 and a.count("-") == 3


def test_middleware_gate(client, keys, db):
    priv, pub = keys
    settings = get_settings()
    settings.license_public_key = pub
    licensing.invalidate_cache()
    try:
        assert client.get("/api/health").status_code == 200
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/activate"
        assert client.get("/api/stock/Infosys").status_code == 403
        assert client.get("/activate").status_code == 200

        device = client.get("/api/license").json()["device_id"]
        bad = licensing.issue_token(priv, "ZZZZ-ZZZZ-ZZZZ-ZZZZ", "Wrong", days=5)
        assert client.post("/api/license", json={"token": bad}).status_code == 400
        assert client.post("/activate", data={"token": bad}).status_code == 400

        good = licensing.issue_token(priv, device, "Ravi", days=5)
        r = client.post("/activate", data={"token": good}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/?msg=")
        st = client.get("/api/license").json()
        assert st["active"] and st["name"] == "Ravi"
        assert client.get("/api/stock/Infosys").status_code == 200
        assert "Licensed to Ravi" in client.get("/").text

        assert client.delete("/api/license").json()["active"] is False
        assert client.get("/api/stock/Infosys").status_code == 403
    finally:
        settings.license_public_key = ""
        licensing.deactivate()


def test_cli_roundtrip(tmp_path, monkeypatch, capsys):
    import tools.license_admin as cli

    key = tmp_path / "k.pem"
    monkeypatch.setattr("sys.argv", ["x", "keygen", "--out", str(key)])
    cli.main()
    pub = [l for l in capsys.readouterr().out.splitlines() if l.startswith("LICENSE_PUBLIC_KEY=")][0].split("=", 1)[1]
    monkeypatch.setattr("sys.argv", ["x", "issue", "--device-id", "1111-2222-3333-4444", "--name", "Test User", "--days", "7", "--key", str(key)])
    cli.main()
    tok = [l for l in capsys.readouterr().out.splitlines() if l.startswith("SOD1.")][0]
    assert licensing.verify_token(tok, pub, "1111-2222-3333-4444").name == "Test User"
    assert (tmp_path / "issued_licenses.csv").read_text().count("\n") == 2


def test_multi_device_key(keys):
    priv, pub = keys
    tok = licensing.issue_token(priv, ["AAAA-1111", "bbbb-2222"], "Two devices", days=30)
    assert licensing.verify_token(tok, pub, device_id="AAAA-1111").devices == ["AAAA-1111", "BBBB-2222"]
    assert licensing.verify_token(tok, pub, device_id="BBBB-2222").name == "Two devices"
    with pytest.raises(licensing.LicenseError, match="valid for device"):
        licensing.verify_token(tok, pub, device_id="CCCC-3333")
