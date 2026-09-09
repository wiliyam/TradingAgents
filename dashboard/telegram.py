"""Explicitly enabled channel notifications; tokens and provider errors stay private."""

import contextlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TOKEN = re.compile(r"\d{5,20}:[A-Za-z0-9_-]{20,100}\Z")
CHANNEL = re.compile(r"(?:@[A-Za-z][A-Za-z0-9_]{4,31}|-?\d{5,20})\Z")


def send_message(config, message):
    if not TOKEN.fullmatch(config.get("token", "")) or not CHANNEL.fullmatch(
        config.get("channel", "")
    ):
        return "Configure a valid bot token and channel first."
    payload = json.dumps(
        {
            "chat_id": config["channel"],
            "text": message[:4000],
            "link_preview_options": {"is_disabled": True},
        }
    ).encode()
    req = Request(
        "https://api.telegram.org/bot" + config["token"] + "/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as response:
            value = json.loads(response.read(65536))
        return (
            "sent" if value.get("ok") else "Telegram rejected delivery. Check channel permissions."
        )
    except HTTPError as exc:
        description = ""
        with contextlib.suppress(ValueError, OSError, AttributeError):
            description = str(json.loads(exc.read(65536)).get("description", "")).lower()
        # Match known failure categories; never return raw Telegram response text.
        if "send messages to bots" in description or "itself" in description:
            return "The destination is a bot username. Enter your channel's @username or numeric chat ID, and add your bot as a channel administrator."
        if exc.code == 401:
            return "The bot token is invalid or revoked. Copy a current token from BotFather and save it in Settings."
        if "chat not found" in description:
            return "Telegram cannot find that channel. Check its @username or numeric chat ID and add your bot as an administrator."
        if (
            "not enough rights" in description
            or "not a member" in description
            or "chat_write_forbidden" in description
        ):
            return "The bot cannot post in that channel. Add it as an administrator and enable Post Messages."
        if "blocked" in description:
            return (
                "The destination has blocked the bot. Unblock it, or choose your intended channel."
            )
        if exc.code == 429:
            return "Telegram is rate-limiting messages. Wait before trying again."
        return "Telegram rejected delivery. Check the channel ID and the bot's permission to post."
    except (URLError, TimeoutError, OSError, ValueError):
        return "Telegram delivery could not be confirmed. Check the channel before retrying."


def notify_completed(store, job):
    try:
        config = store.telegram()
        if not config.get("enabled"):
            return
        from dashboard.presentation import present

        view = present(job)
        snapshot = view["snapshot"]
        message = (
            f"TradingAgents · {job['symbol']}\nResearch date: {job['day']}\n"
            f"{'AI assessment' if job['mode'] == 'ai' else 'Market snapshot'}: {view['signal']}\n"
            f"Adjusted close: INR {snapshot.get('close', 'unavailable')} (bar {snapshot.get('latest_bar_date', 'unavailable')})\n"
            f"Agent outputs: {view['completion']['completed']}/{view['completion']['total']}\n"
            f"https://at.arkbytetech.com/?job={job['id']}\n"
            "Research only. Prices may be delayed; no order has been placed."
        )
        store.notification(job["id"], send_message(config, message))
    except Exception:
        # Notification failure must never change a completed analysis into a failed job.
        with contextlib.suppress(Exception):
            store.notification(
                job["id"], "Notification could not be completed. Check Telegram settings."
            )
