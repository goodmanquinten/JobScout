import httpx
import pytest

from jobscout.telegram import TelegramError, get_updates, send_message

TOKEN = "123:abc"


def test_get_updates_passes_offset(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]', "offset": 42},
        ),
        json={"ok": True, "result": [{"update_id": 42, "message": {"text": "/list"}}]},
    )
    assert get_updates(TOKEN, 42) == [{"update_id": 42, "message": {"text": "/list"}}]


def test_get_updates_without_offset(httpx_mock):
    httpx_mock.add_response(
        url=httpx.URL(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"timeout": 0, "allowed_updates": '["message"]'},
        ),
        json={"ok": True, "result": []},
    )
    assert get_updates(TOKEN, None) == []


def test_get_updates_error(httpx_mock):
    httpx_mock.add_response(json={"ok": False, "description": "Conflict"})
    with pytest.raises(TelegramError, match="Conflict"):
        get_updates(TOKEN, None)


def test_send_message_posts_html(httpx_mock):
    httpx_mock.add_response(json={"ok": True, "result": {}})
    send_message(TOKEN, "99", "<b>hi</b>")
    body = httpx_mock.get_requests()[0].read()
    assert b'"parse_mode":"HTML"' in body.replace(b" ", b"")
