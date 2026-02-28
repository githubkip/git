#!/usr/bin/env python3
"""Telegram query bot for Plain City parcel data.

Commands:
- /help
- /parcel <PARCEL_ID>
- /house <house number or address fragment>
- /changes
- /change <PARCEL_ID>
- /watched
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

DATA_PARCELS = Path("data/plain_city_parcels.geojson")
DATA_SUMMARY = Path("data/plain_city_changes_summary.json")
DATA_WATCHED = Path("data/watched_parcels.txt")
OFFSET_FILE = Path("data/telegram_offset.txt")

POLL_TIMEOUT_SECONDS = 30
SLEEP_ON_ERROR_SECONDS = 5
MAX_HOUSE_RESULTS = 10


class Bot:
    def __init__(self) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        self.token = token
        self.api_base = f"https://api.telegram.org/bot{token}"

    def api_post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.api_base}/{method}"
        req = urllib.request.Request(url, data=urllib.parse.urlencode(payload).encode("utf-8"))
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                raise RuntimeError(f"Telegram API error: {body}")
            return body

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: Dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        payload: Dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        self.api_post("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self.api_post("answerCallbackQuery", payload)

    def get_updates(self, offset: int | None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "timeout": str(POLL_TIMEOUT_SECONDS),
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        if offset is not None:
            payload["offset"] = str(offset)
        resp = self.api_post("getUpdates", payload)
        return resp.get("result", [])


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_parcels() -> List[Dict[str, Any]]:
    raw = load_json(DATA_PARCELS)
    return raw.get("features", []) if isinstance(raw, dict) else []


def load_summary() -> Dict[str, Any]:
    return load_json(DATA_SUMMARY)


def load_watchlist() -> List[str]:
    if not DATA_WATCHED.exists():
        return []
    out: List[str] = []
    for line in DATA_WATCHED.read_text(encoding="utf-8").splitlines():
        v = line.strip()
        if not v or v.startswith("#"):
            continue
        out.append(v)
    return out


def read_offset() -> int | None:
    if not OFFSET_FILE.exists():
        return None
    s = OFFSET_FILE.read_text(encoding="utf-8").strip()
    if not s:
        return None
    return int(s)


def write_offset(offset: int) -> None:
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def parcel_properties_by_id(parcel_id: str) -> Dict[str, Any] | None:
    for ft in load_parcels():
        props = ft.get("properties", {})
        if str(props.get("PARCEL_ID", "")) == parcel_id:
            return props
    return None


def format_parcel(props: Dict[str, Any]) -> str:
    keys = ["PARCEL_ID", "NAME_ONE", "STREET", "CITY_STATE", "ZIPCODE", "PROP_STREET", "PROP_CITY", "PROP_ZIP"]
    lines = ["Parcel details:"]
    for k in keys:
        v = props.get(k)
        if v not in (None, ""):
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def find_house_matches(query: str) -> List[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []
    matches: List[Dict[str, Any]] = []
    for ft in load_parcels():
        props = ft.get("properties", {})
        prop_street = str(props.get("PROP_STREET") or "")
        haystack = prop_street.lower()
        if q in haystack:
            matches.append(props)
    return matches


def get_change_for_parcel(parcel_id: str) -> Dict[str, Any] | None:
    summary = load_summary()
    details = summary.get("details", {}) if isinstance(summary, dict) else {}
    for item in details.get("changed", []):
        if str(item.get("parcel_id")) == parcel_id:
            return item
    return None


def handle_parcel_command(bot: Bot, chat_id: int | str, parcel_id: str, reply_to: int | None = None) -> None:
    props = parcel_properties_by_id(parcel_id)
    if not props:
        bot.send_message(chat_id, f"No parcel found for PARCEL_ID {parcel_id}", reply_to_message_id=reply_to)
        return

    message = format_parcel(props)
    change = get_change_for_parcel(parcel_id)
    if change:
        lines = ["", "Latest recorded change fields:"]
        for field, diff in change.get("changes", {}).items():
            lines.append(f"- {field}: {diff.get('before')!r} -> {diff.get('after')!r}")
        message += "\n" + "\n".join(lines)

    bot.send_message(chat_id, message, reply_to_message_id=reply_to)


def handle_changes_command(bot: Bot, chat_id: int | str, reply_to: int | None = None) -> None:
    summary = load_summary()
    if not summary:
        bot.send_message(chat_id, "No change summary file found yet.", reply_to_message_id=reply_to)
        return
    stats = summary.get("stats", {})
    samples = summary.get("samples", {})
    lines = [
        "Latest parcel change summary:",
        f"- Current parcels: {stats.get('current_total', 'n/a')}",
        f"- Added: {stats.get('added_count', 'n/a')}",
        f"- Removed: {stats.get('removed_count', 'n/a')}",
        f"- Changed: {stats.get('changed_count', 'n/a')}",
    ]
    if samples.get("changed"):
        lines.append(f"- Sample changed IDs: {', '.join(samples['changed'])}")
    bot.send_message(chat_id, "\n".join(lines), reply_to_message_id=reply_to)


def handle_watched_command(bot: Bot, chat_id: int | str, reply_to: int | None = None) -> None:
    watched = load_watchlist()
    if not watched:
        bot.send_message(chat_id, "No watched parcels configured.", reply_to_message_id=reply_to)
        return
    preview = watched[:30]
    lines = [f"Watched parcels ({len(watched)} total):", *[f"- {p}" for p in preview]]
    if len(watched) > len(preview):
        lines.append(f"... and {len(watched)-len(preview)} more")
    bot.send_message(chat_id, "\n".join(lines), reply_to_message_id=reply_to)


def handle_house_command(bot: Bot, chat_id: int | str, query: str, reply_to: int | None = None) -> None:
    matches = find_house_matches(query)
    if not matches:
        bot.send_message(chat_id, f"No address matches for: {query}", reply_to_message_id=reply_to)
        return

    top = matches[:MAX_HOUSE_RESULTS]
    keyboard = []
    for props in top:
        pid = str(props.get("PARCEL_ID", ""))
        address = str(props.get("PROP_STREET") or "(no PROP_STREET)")
        keyboard.append([{"text": f"{address} ({pid})", "callback_data": f"parcel:{pid}"}])

    bot.send_message(
        chat_id,
        f"Found {len(matches)} match(es) for '{query}'. Showing first {len(top)}. Tap one:",
        reply_markup={"inline_keyboard": keyboard},
        reply_to_message_id=reply_to,
    )


def handle_help(bot: Bot, chat_id: int | str, reply_to: int | None = None) -> None:
    bot.send_message(
        chat_id,
        "Commands:\n"
        "/parcel <PARCEL_ID> - parcel details\n"
        "/house <number or address> - search address and select a match\n"
        "/changes - latest change summary\n"
        "/change <PARCEL_ID> - latest change details for parcel\n"
        "/watched - list watched parcel IDs\n"
        "/help - show this help",
        reply_to_message_id=reply_to,
    )


def parse_command(text: str) -> tuple[str, str]:
    txt = (text or "").strip()
    if not txt:
        return "", ""
    parts = txt.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return cmd, arg


def handle_message(bot: Bot, msg: Dict[str, Any]) -> None:
    chat_id = msg.get("chat", {}).get("id")
    if chat_id is None:
        return
    text = msg.get("text", "")
    reply_to = msg.get("message_id")
    cmd, arg = parse_command(text)

    if cmd in ("/start", "/help"):
        handle_help(bot, chat_id, reply_to)
    elif cmd == "/parcel":
        if not arg:
            bot.send_message(chat_id, "Usage: /parcel <PARCEL_ID>", reply_to_message_id=reply_to)
        else:
            handle_parcel_command(bot, chat_id, arg, reply_to)
    elif cmd == "/house":
        if not arg:
            bot.send_message(chat_id, "Usage: /house <house number or address>", reply_to_message_id=reply_to)
        else:
            handle_house_command(bot, chat_id, arg, reply_to)
    elif cmd == "/changes":
        handle_changes_command(bot, chat_id, reply_to)
    elif cmd == "/change":
        if not arg:
            bot.send_message(chat_id, "Usage: /change <PARCEL_ID>", reply_to_message_id=reply_to)
        else:
            change = get_change_for_parcel(arg)
            if not change:
                bot.send_message(chat_id, f"No latest-run change details for PARCEL_ID {arg}", reply_to_message_id=reply_to)
            else:
                lines = [f"Latest change details for {arg}:"]
                for field, diff in change.get("changes", {}).items():
                    lines.append(f"- {field}: {diff.get('before')!r} -> {diff.get('after')!r}")
                bot.send_message(chat_id, "\n".join(lines), reply_to_message_id=reply_to)
    elif cmd == "/watched":
        handle_watched_command(bot, chat_id, reply_to)


def handle_callback_query(bot: Bot, cq: Dict[str, Any]) -> None:
    data = cq.get("data", "")
    qid = cq.get("id")
    message = cq.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    reply_to = message.get("message_id")

    if qid:
        bot.answer_callback_query(qid)

    if chat_id is None:
        return

    if data.startswith("parcel:"):
        pid = data.split(":", 1)[1].strip()
        if pid:
            handle_parcel_command(bot, chat_id, pid, reply_to)


def main() -> int:
    bot = Bot()
    offset = read_offset()
    print("Telegram query bot started")

    while True:
        try:
            updates = bot.get_updates(offset)
            for upd in updates:
                uid = upd.get("update_id")
                if uid is not None:
                    offset = int(uid) + 1
                    write_offset(offset)

                if "message" in upd:
                    handle_message(bot, upd["message"])
                elif "callback_query" in upd:
                    handle_callback_query(bot, upd["callback_query"])
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"Bot loop error: {exc}")
            time.sleep(SLEEP_ON_ERROR_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
