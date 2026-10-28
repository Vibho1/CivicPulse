"""WhatsApp Cloud API intake: webhook auth, drafts, filing, replies, limits and privacy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import itertools
import json
import logging
import threading
import wave
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.ai import ResilientAI
from app.ai.heuristic import HeuristicAI
from app.config import Settings
from app.main import create_app
from app.services import whatsapp as wa
from app.services.common import now_utc
from app.services.present import present_cluster

PHONE = "919876543210"
NEIGHBOUR = "919812345678"
PNID = "106540352242922"  # the business number's phone_number_id
VERIFY = "verify-token-for-tests"
SECRET = "app-secret-for-tests"
HOOK = "/api/whatsapp/webhook"
ORR = (12.9262, 77.6816)
SONY = (12.9345, 77.6231)
_SIGN = object()
_ids = itertools.count(1)


class FakeGraph:
    """Stands in for GraphClient: serves canned media and records replies."""

    def __init__(self) -> None:
        self.media: dict[str, tuple[bytes, str]] = {}
        self.fetched: list[str] = []
        self.sent: list[tuple[str, str]] = []

    def fetch_media(self, media_id: str) -> tuple[bytes, str]:
        self.fetched.append(media_id)
        if media_id not in self.media:
            raise wa.GraphError("HTTP 404")
        return self.media[media_id]

    def send_text(self, to: str, body: str) -> bool:
        self.sent.append((to, body))
        return True

    @property
    def last(self) -> str:
        return self.sent[-1][1] if self.sent else ""


class NotCivicAI(HeuristicAI):
    def parse_report(self, inp):
        return super().parse_report(inp).model_copy(update={"is_civic_issue": False})


class EmergencyAI(HeuristicAI):
    def parse_report(self, inp):
        return super().parse_report(inp).model_copy(update={"is_emergency": True})


# ----------------------------------------------------------------- helpers --
def settings_for(tmp_path, **overrides) -> Settings:
    values = dict(
        gemini_api_key="",
        database_path=str(tmp_path / "test.db"),
        uploads_dir=str(tmp_path / "uploads"),
        frontend_dist=str(tmp_path / "no-dist"),
        demo_mode=True,
        seed_on_startup=False,
        notify_webhook_url="",
        public_base_url="https://civicpulse.example",
        max_image_mb=10,
        max_audio_mb=10,
        max_audio_s=30,
        duplicate_window_s=300,
        duplicate_radius_m=1000,
        whatsapp_verify_token=VERIFY,
        whatsapp_app_secret=SECRET,
        whatsapp_access_token="test-access-token",
        whatsapp_phone_number_id=PNID,
        whatsapp_graph_version="v21.0",
    )
    values.update(overrides)
    return Settings(**values)


def app_for(tmp_path, store, graph, ai=None, **overrides):
    app = create_app(settings=settings_for(tmp_path, **overrides), store=store, ai=ai or ResilientAI(None, HeuristicAI()))
    app.state.whatsapp_client = graph
    return app


@pytest.fixture()
def graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture()
def bot(tmp_path, store, ai, graph):
    with TestClient(app_for(tmp_path, store, graph, ai)) as client:
        yield client


def wamid(sender: str) -> str:
    """A message id shaped like WhatsApp's, which base64-embeds the sender's number."""
    return "wamid." + base64.b64encode(f"\x1c\x18\x0c{sender}\x15\x02\x00\x12\x18\x14{next(_ids):020d}".encode()).decode()


def message(kind: str, sender: str = PHONE, **content) -> dict:
    return {"from": sender, "id": wamid(sender), "timestamp": "1761642000", "type": kind, kind: content}


def text(body: str, sender: str = PHONE) -> dict:
    return message("text", sender, body=body)


def location(lat: float, lng: float, sender: str = PHONE) -> dict:
    return message("location", sender, latitude=lat, longitude=lng)


def image(media_id: str, caption: str | None = None, sender: str = PHONE) -> dict:
    content = {"id": media_id, "mime_type": "image/jpeg", "sha256": "abc"}
    if caption:
        content["caption"] = caption
    return message("image", sender, **content)


def voice(media_id: str, sender: str = PHONE) -> dict:
    return message("audio", sender, id=media_id, mime_type="audio/ogg; codecs=opus", voice=True)


def delivery(*messages: dict, phone_number_id: str = PNID) -> dict:
    """A webhook delivery shaped like Meta's."""
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550001234", "phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": "Asha"}, "wa_id": m["from"]} for m in messages],
        "messages": list(messages),
    }
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA-ID", "changes": [{"field": "messages", "value": value}]}]}


def post(client: TestClient, body: dict, signature=_SIGN, secret: str = SECRET):
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if signature is _SIGN:
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post(HOOK, content=raw, headers=headers)


def send(client: TestClient, *messages: dict) -> None:
    r = post(client, delivery(*messages))
    assert r.status_code == 200, r.text


def rows(store, table: str) -> list[dict]:
    wa.ensure_schema(store)
    with store._lock:
        return [dict(r) for r in store.conn.execute(f"SELECT * FROM {table}").fetchall()]


def wav(seconds: float, rate: int = 8000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(b"\x80" * int(seconds * rate))
    return out.getvalue()


def gif() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (16, 12), (100, 100, 100)).save(out, format="GIF")
    return out.getvalue()


# ------------------------------------------------------------------- tests --
def test_disabled_without_a_verify_token(tmp_path, store, ai, graph):
    with TestClient(app_for(tmp_path, store, graph, ai, whatsapp_verify_token="")) as client:
        assert client.get(HOOK, params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "42"}).status_code == 404
        assert post(client, delivery(text("Pothole near the bus stop"))).status_code == 404
    assert graph.sent == []


def test_verification_handshake(bot):
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"}
    ok = bot.get(HOOK, params=params)
    assert ok.status_code == 200 and ok.text == "1158201444"
    assert ok.headers["content-type"].startswith("text/plain")
    assert bot.get(HOOK, params={**params, "hub.verify_token": "wrong"}).status_code == 403
    assert bot.get(HOOK, params={**params, "hub.mode": "unsubscribe"}).status_code == 403
    assert bot.get(HOOK).status_code == 403


def test_webhook_calls_must_be_signed(bot, graph, store):
    body = delivery(text("Garbage dumped near the bus stop"))
    assert post(bot, body, signature=None).status_code == 401
    assert post(bot, body, signature="sha256=" + "0" * 64).status_code == 401
    assert post(bot, body, secret="someone-elses-secret").status_code == 401
    assert graph.sent == [] and rows(store, "wa_sessions") == []
    assert post(bot, body).status_code == 200
    assert len(graph.sent) == 1
    assert bot.post(HOOK, content=b"not json", headers={"X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), b"not json", hashlib.sha256).hexdigest()}).status_code == 400


def test_text_then_location_files_a_report_and_replies_with_the_ticket(bot, graph, store):
    send(bot, text("Dodda gundi near Ecospace gate on the service lane, bikes are falling"))
    assert rows(store, "reports") == []
    to, body = graph.sent[-1]
    assert to == PHONE and "location" in body.lower() and "\U0001f4ce" in body

    send(bot, location(*ORR))
    [report] = rows(store, "reports")
    assert report["reporter_id"] == wa.sender_key(bot.app.state.settings, PHONE)
    assert report["reporter_id"].startswith("wa:") and len(report["reporter_id"]) == 19
    cid = report["cluster_id"]
    c = present_cluster(store.get_cluster(cid))
    to, body = graph.sent[-1]
    assert to == PHONE
    assert cid in body and "new issue" in body
    assert c["category_label"] in body and c["severity_level"] in body.lower() and c["agency_label"] in body
    if c.get("secondary_agency_label"):
        assert c["secondary_agency_label"] in body
    assert f"https://civicpulse.example/clusters/{cid}" in body
    assert rows(store, "wa_sessions") == []  # the draft is gone once filed

    # a neighbour reporting the same pothole joins the same issue
    send(bot, text("Big pothole on the service lane near Ecospace", NEIGHBOUR), location(ORR[0] + 0.0001, ORR[1], NEIGHBOUR))
    to, body = graph.sent[-1]
    assert to == NEIGHBOUR and cid in body and "existing issue" in body and "2 citizens" in body


def test_photo_flow_downloads_the_media(bot, graph, store, jpeg, tmp_path):
    graph.media["MEDIA-PHOTO-1"] = (jpeg, "image/jpeg")
    send(bot, location(*SONY))
    assert "location saved" in graph.last.lower() and graph.fetched == []

    send(bot, image("MEDIA-PHOTO-1", caption="Garbage dumped near Sony World junction, stinks"))
    assert graph.fetched == ["MEDIA-PHOTO-1"]
    [report] = rows(store, "reports")
    assert report["text"] == "Garbage dumped near Sony World junction, stinks"
    assert report["photo_path"] and (tmp_path / "uploads" / report["photo_path"]).is_file()
    assert report["cluster_id"] in graph.last


def test_media_without_a_location_asks_for_it(bot, graph, store, jpeg):
    graph.media["MEDIA-PHOTO-2"] = (jpeg, "image/jpeg")
    graph.media["MEDIA-VOICE-2"] = (wav(5), "audio/wav")
    send(bot, image("MEDIA-PHOTO-2"))
    to, body = graph.sent[-1]
    assert to == PHONE and "photo" in body and "location" in body.lower() and "\U0001f4ce" in body
    assert graph.fetched == []  # nothing is downloaded before the report is complete
    [draft] = rows(store, "wa_sessions")
    assert draft["photo_media_id"] == "MEDIA-PHOTO-2" and draft["lat"] is None
    assert rows(store, "reports") == []

    send(bot, voice("MEDIA-VOICE-2"), text("Deep pothole near the school gate"))  # a burst: no repeated prompt
    assert len(graph.sent) == 1
    [draft] = rows(store, "wa_sessions")
    assert draft["audio_media_id"] == "MEDIA-VOICE-2" and draft["text"] == "Deep pothole near the school gate"

    send(bot, location(12.9116, 77.6389))
    assert sorted(graph.fetched) == ["MEDIA-PHOTO-2", "MEDIA-VOICE-2"]
    [report] = rows(store, "reports")
    assert report["photo_path"] and report["audio_path"] and report["text"] == "Deep pothole near the school gate"
    assert report["cluster_id"] in graph.last


def test_duplicate_report_gets_a_friendly_reply(bot, graph, store):
    send(bot, text("Street light not working near Sony World junction"), location(*SONY))
    [first] = rows(store, "reports")
    send(bot, text("Street light not working near Sony World junction"), location(SONY[0] + 0.0005, SONY[1]))
    assert len(rows(store, "reports")) == 1
    assert "already reported" in graph.last and first["cluster_id"] in graph.last
    assert rows(store, "wa_sessions") == []


def test_phone_numbers_are_never_stored_or_logged(bot, graph, store, jpeg, caplog):
    caplog.set_level(logging.DEBUG)
    graph.media["MEDIA-PHOTO-3"] = (jpeg, "image/jpeg")
    msgs = [text("Garbage dumped near the Ecospace gate"), location(*ORR), image("MEDIA-PHOTO-3")]  # the photo stays a draft
    for m in msgs:
        send(bot, m)
    assert len(rows(store, "reports")) == 1 and len(rows(store, "wa_sessions")) == 1
    with store._lock:
        tables = [r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
    assert {"reports", "wa_sessions", "wa_seen_messages"} <= set(tables)
    dump = repr({t: rows(store, t) for t in tables})
    for secret in (PHONE, PHONE[-10:], "Asha", *(m["id"] for m in msgs)):
        assert secret not in dump
        assert secret not in caplog.text
    assert wa.sender_key(bot.app.state.settings, PHONE) in dump


def test_media_limits_are_explained(bot, graph, store):
    graph.media["MEDIA-LONG"] = (wav(45), "audio/wav")
    graph.media["MEDIA-GIF"] = (gif(), "image/gif")
    send(bot, location(*ORR), voice("MEDIA-LONG"))
    assert rows(store, "reports") == []
    assert "45 s" in graph.last and "30 s" in graph.last
    [draft] = rows(store, "wa_sessions")
    assert draft["audio_media_id"] is None and (draft["lat"], draft["lng"]) == ORR  # location kept for the retry

    send(bot, image("MEDIA-GIF"))
    assert "JPEG, PNG or WebP" in graph.last and rows(store, "reports") == []
    send(bot, image("MEDIA-MISSING"))
    assert "couldn't download" in graph.last and rows(store, "reports") == []


def test_greetings_commands_and_unsupported_messages(bot, graph, store):
    send(bot, text("Hi!"))
    assert "Namaskara" in graph.last and rows(store, "wa_sessions") == []
    send(bot, message("sticker", id="STICKER-1", mime_type="image/webp"))
    assert "only read" in graph.last
    replies = len(graph.sent)
    send(bot, message("reaction", message_id="wamid.X", emoji="\U0001f44d"))
    assert len(graph.sent) == replies  # reactions are ignored quietly
    send(bot, text("Overflowing drain near the bus stop"))
    assert len(rows(store, "wa_sessions")) == 1
    send(bot, text("cancel"))
    assert rows(store, "wa_sessions") == [] and "discarded" in graph.last.lower()
    send(bot, text("Thank you"))
    assert "welcome" in graph.last.lower() and rows(store, "wa_sessions") == []


def test_redeliveries_receipts_and_other_numbers_are_ignored(bot, graph, store):
    body = delivery(text("Overflowing sewage near the school gate"))
    assert post(bot, body).status_code == 200 and post(bot, body).status_code == 200
    [draft] = rows(store, "wa_sessions")
    assert draft["text"] == "Overflowing sewage near the school gate"  # not appended twice
    assert len(graph.sent) == 1

    assert post(bot, delivery(location(*ORR), phone_number_id="SOME-OTHER-NUMBER")).status_code == 200
    receipt = delivery(text("ignored"))
    value = receipt["entry"][0]["changes"][0]["value"]
    value["statuses"] = [{"id": "wamid.Y", "status": "delivered", "recipient_id": PHONE}]
    del value["messages"]
    assert post(bot, receipt).status_code == 200
    assert rows(store, "reports") == [] and len(graph.sent) == 1


def test_drafts_expire_after_30_minutes(tmp_path, store, ai, graph):
    settings = settings_for(tmp_path)
    t0 = now_utc()
    wa.process_payload(delivery(text("Pothole near the bus stop")), settings=settings, store=store, ai=ai, client=graph, now=t0)
    wa.process_payload(delivery(location(*ORR)), settings=settings, store=store, ai=ai, client=graph, now=t0 + timedelta(minutes=31))
    assert rows(store, "reports") == []
    assert "location saved" in graph.last.lower()


def test_not_a_civic_issue_keeps_the_location(tmp_path, store, graph):
    with TestClient(app_for(tmp_path, store, graph, ResilientAI(None, NotCivicAI()))) as client:
        send(client, text("Happy Deepavali to everyone in the group"), location(*ORR))
    assert rows(store, "reports") == []
    assert "doesn't look like a civic problem" in graph.last
    [draft] = rows(store, "wa_sessions")
    assert (draft["lat"], draft["lng"]) == ORR and not draft["text"]


def test_emergencies_get_112_guidance(tmp_path, store, graph):
    with TestClient(app_for(tmp_path, store, graph, ResilientAI(None, EmergencyAI()))) as client:
        send(client, text("Live wire hanging and sparking near the bus stop"), location(*SONY))
    [report] = rows(store, "reports")
    assert "call 112" in graph.last and report["cluster_id"] in graph.last


def test_graph_client_against_a_local_server(jpeg):
    calls: list[tuple] = []

    class Graph(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            calls.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/v21.0/MEDIA-1":
                meta = {"url": f"{base}/media/MEDIA-1?ext=1", "mime_type": "image/jpeg", "file_size": len(jpeg), "id": "MEDIA-1"}
                self._send(200, json.dumps(meta).encode())
            elif self.path.startswith("/media/MEDIA-1"):
                self._send(200, jpeg, "image/jpeg")
            else:
                self._send(400, json.dumps({"error": {"message": f"Unsupported get request from {PHONE}", "code": 100}}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("POST", self.path, self.headers.get("Authorization"), body))
            self._send(200, b'{"messages": [{"id": "wamid.OK"}]}')

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Graph)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = wa.GraphClient("tok", PNID, "v21.0", base_url=base)
        assert client.fetch_media("MEDIA-1") == (jpeg, "image/jpeg")
        assert calls == [("GET", "/v21.0/MEDIA-1", "Bearer tok"), ("GET", "/media/MEDIA-1?ext=1", "Bearer tok")]

        assert client.send_text(PHONE, "Report filed") is True
        expected = {"messaging_product": "whatsapp", "to": PHONE, "type": "text", "text": {"body": "Report filed"}}
        assert calls[-1] == ("POST", f"/v21.0/{PNID}/messages", "Bearer tok", expected)

        with pytest.raises(wa.GraphError) as err:
            client.fetch_media("NOPE")
        assert "HTTP 400" in str(err.value) and PHONE not in str(err.value)
        with pytest.raises(wa.MediaTooLarge):
            wa.GraphClient("tok", PNID, base_url=base, max_media_bytes=100).fetch_media("MEDIA-1")
        made = len(calls)
        assert wa.GraphClient("", PNID, base_url=base).send_text(PHONE, "x") is False  # not configured: no call at all
        assert len(calls) == made
    finally:
        server.shutdown()
        server.server_close()
    assert wa.GraphClient("tok", PNID, base_url=base, timeout_s=2).send_text(PHONE, "x") is False  # unreachable: no exception
