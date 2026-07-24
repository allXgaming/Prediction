# ================================================================
#                WINGO BOT (No External Libraries)
#        শুধু Python স্ট্যান্ডার্ড লাইব্রেরি ব্যবহার করে
# ================================================================

import json
import sqlite3
import time
import threading
import math
import urllib.request
import urllib.error
from collections import deque, Counter
from typing import Optional, Dict, Any, List, Set

# ------------------------ কনফিগ ------------------------
BOT_TOKEN = "7768747736:AAHRFAiemrbWwo2aCY0geWyBBY385gPJcZ8"   # ← আপনার টোকেন দিন
SUPER_ADMIN_ID = 5824157133   # ← আপনার টেলিগ্রাম আইডি দিন

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts={}"

# ------------------------------------------------------
#                  HTTP রিকুয়েস্ট ফাংশন
# ------------------------------------------------------
def http_get(url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data)
    except Exception:
        return None


def http_post(url: str, json_data: Dict[str, Any], timeout: int = 10) -> bool:
    try:
        data = json.dumps(json_data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def http_get_text(url: str, timeout: int = 10) -> Optional[str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None

# ------------------------------------------------------
#                    অথোরাইজেশন
# ------------------------------------------------------
AUTHORIZED_USER_IDS: Set[int] = {SUPER_ADMIN_ID}
waiting_for_user_id = {}  # {chat_id: True/False}

def is_authorized(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    return user_id in AUTHORIZED_USER_IDS

def add_authorized_user(user_id: int) -> None:
    AUTHORIZED_USER_IDS.add(user_id)

def remove_authorized_user(user_id: int) -> None:
    AUTHORIZED_USER_IDS.discard(user_id)


# ------------------------------------------------------
#                    ডেটাবেস
# ------------------------------------------------------
class GameDataManager:
    def __init__(self, db_file: str = "predictions.db"):
        self.db_file = db_file
        self._init_tables()

    def connect(self):
        return sqlite3.connect(self.db_file)

    def _init_tables(self):
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rounds (
                    period TEXT PRIMARY KEY,
                    number INTEGER,
                    size TEXT,
                    prediction TEXT,
                    result TEXT,
                    range_pred TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS authorized_users (
                    user_id INTEGER PRIMARY KEY
                )
            """)
            conn.commit()

    def save_round(self, period: str, number: int, size: str,
                   prediction: Optional[str], result: Optional[str],
                   range_pred: Optional[str]) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO rounds
                    (period, number, size, prediction, result, range_pred)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (str(period), number, size, prediction, result, range_pred))
                conn.commit()
            return True
        except sqlite3.Error:
            return False

    def get_recent_history(self, limit: int = 300) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM rounds ORDER BY period DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def add_authorized_user(self, user_id: int) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)", (user_id,))
                conn.commit()
            return True
        except sqlite3.Error:
            return False

    def remove_authorized_user(self, user_id: int) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("DELETE FROM authorized_users WHERE user_id = ?", (user_id,))
                conn.commit()
            return True
        except sqlite3.Error:
            return False

    def get_authorized_users(self) -> List[int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT user_id FROM authorized_users").fetchall()
            return [r[0] for r in rows]


db = GameDataManager()
AUTHORIZED_USER_IDS.update(db.get_authorized_users())
AUTHORIZED_USER_IDS.add(SUPER_ADMIN_ID)


# ------------------------------------------------------
#                    UI ফরম্যাট
# ------------------------------------------------------
def format_prediction_ui(pred_data: Dict[str, Any], period: str) -> str:
    size = pred_data["size"]
    conf = pred_data["confidence"]
    num_range = pred_data["range"]
    ma_val = pred_data.get("ma", "BULLISH")
    rsi_val = pred_data.get("rsi", 63.8)
    std_val = pred_data.get("std", "LOW")
    pattern = pred_data.get("pattern", "ALTERNATING")
    cycle = pred_data.get("cycle", "STABLE")
    big_pct = pred_data.get("big_pct", 78)
    small_pct = pred_data.get("small_pct", 22)
    signal = "HIGH 🟢" if conf >= 85 else "MEDIUM 🟡"
    volatility = "LOW" if conf >= 85 else "MEDIUM"
    risk = "LOW" if conf >= 85 else "MEDIUM"

    size_emoji = "🐘" if size == "BIG" else "🐭"
    level = "🔥 LEVEL 1" if conf >= 92 else "⚡ LEVEL 2" if conf >= 85 else "⚠️ LEVEL 3"

    big_bar = "█" * int(big_pct / 10) + "░" * (10 - int(big_pct / 10))
    small_bar = "█" * int(small_pct / 10) + "░" * (10 - int(small_pct / 10))

    return f"""
━━━━━━━━━━━━━━━━━━━━━━
🧠 AI ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━
📈 MA           : {ma_val}
📊 RSI          : {rsi_val:.1f}
📉 STD DEV      : {std_val}
🔄 PATTERN      : {pattern}
🎯 CYCLE        : {cycle}

━━━━━━━━━━━━━━━━━━━━━━
🗳️ AI VOTING
━━━━━━━━━━━━━━━━━━━━━━
🐘 BIG          {big_bar} {big_pct}%
🐭 SMALL        {small_bar} {small_pct}%

🏆 FINAL EDGE   : {size_emoji} {size}

━━━━━━━━━━━━━━━━━━━━━━
📡 AI METRICS
━━━━━━━━━━━━━━━━━━━━━━
🎯 CONFIDENCE   : {conf}%
📶 SIGNAL       : {signal}
🎲 VOLATILITY   : {volatility}
⚖️ RISK         : {risk}

━━━━━━━━━━━━━━━━━━━━━━
🆔 PERIOD       : {period}
🎯 RANGE        : {num_range}
📊 LEVEL        : {level}
━━━━━━━━━━━━━━━━━━━━━━
⚡ AI STATUS : ACTIVE
🧠 ENGINE    : SUBHA AI
🔥 MODE      : LIVE
━━━━━━━━━━━━━━━━━━━━━━
"""


def format_result_ui(period: str, number: int, actual_size: str,
                     result: str, pred: str, range_pred: str) -> str:
    if result == "WIN":
        status_emoji, status_text, bg = "✅", "WIN 🎉", "🟢"
    else:
        status_emoji, status_text, bg = "❌", "LOSS 😞", "🔴"
    actual_emoji = "🐘" if actual_size == "BIG" else "🐭"
    return f"""
{status_emoji} {status_text}  {bg}
━━━━━━━━━━━━━━━━━━━━━━
📊 RESULT
━━━━━━━━━━━━━━━━━━━━━━
📅 PERIOD    : {period}
🎯 PREDICT   : {pred}
✅ ACTUAL    : {actual_emoji} {actual_size} [{number}]
📊 RANGE     : {range_pred}
━━━━━━━━━━━━━━━━━━━━━━
"""


# ------------------------------------------------------
#                    প্রেডিক্টর ক্লাস
# ------------------------------------------------------
class Predictor:
    def __init__(self):
        self.history: deque = deque(maxlen=300)
        self.wins = 0
        self.losses = 0
        self.streak = 0
        self.best_streak = 0
        self.total_predictions = 0
        self.running = False
        self.chat_id: Optional[int] = None
        self._load_from_db()

    def _load_from_db(self):
        rows = db.get_recent_history(300)
        for row in rows:
            num = row.get("number")
            if num is not None:
                self.history.append(num)

    def update(self, num: int, period: str, prediction: Optional[str] = None,
               result: Optional[str] = None, range_pred: Optional[str] = None):
        size = "BIG" if num >= 5 else "SMALL"
        self.history.append(num)
        db.save_round(period, num, size, prediction, result, range_pred)

    def fetch_data(self) -> List[Dict[str, Any]]:
        ts = int(time.time() * 1000)
        url = API_URL.format(ts)
        data = http_get(url, timeout=10)
        if data:
            return data.get("data", {}).get("list", [])
        return []

    # ---------- ইন্ডিকেটর ----------
    def ma(self, data: List[int], w: int) -> float:
        if len(data) >= w:
            return sum(data[-w:]) / w
        return sum(data) / len(data) if data else 0

    def rsi(self, data: List[int], w: int = 14) -> float:
        if len(data) < w + 1:
            return 50.0
        gain, loss = 0, 0
        for i in range(1, w + 1):
            d = data[-i] - data[-i - 1]
            if d > 0:
                gain += d
            else:
                loss += abs(d)
        if loss == 0:
            return 100.0
        return 100.0 - (100.0 / (1 + (gain / loss)))

    def std_dev(self, data: List[int], w: int = 20) -> float:
        if len(data) < w:
            return 0.0
        recent = data[-w:]
        mean = sum(recent) / w
        return math.sqrt(sum((x - mean) ** 2 for x in recent) / w)

    # ---------- কোর প্রেডিকশন ----------
    def predict_size(self):
        hist = list(self.history)
        if len(hist) < 20:
            return "BIG", 60, "5 • 9", "BULLISH", 50.0, "LOW", "NEUTRAL", "STABLE", 50, 50

        last = hist[-1]
        last_size = "BIG" if last >= 5 else "SMALL"

        streak = 1
        for i in range(len(hist) - 2, -1, -1):
            if (hist[i] >= 5) == (last >= 5):
                streak += 1
            else:
                break

        if streak >= 5:
            pred = last_size
            conf = 99
        elif streak == 4:
            pred = last_size
            conf = 97
        elif streak == 3:
            pred = "SMALL" if last_size == "BIG" else "BIG"
            conf = 90
        elif streak == 2:
            pred = "SMALL" if last_size == "BIG" else "BIG"
            conf = 85
        else:
            def is_alt(length: int) -> bool:
                if len(hist) < length:
                    return False
                for i in range(1, length):
                    if (hist[-i] >= 5) == (hist[-i - 1] >= 5):
                        return False
                return True

            if is_alt(8):
                pred = "SMALL" if last_size == "BIG" else "BIG"
                conf = 92
            elif is_alt(6):
                pred = "SMALL" if last_size == "BIG" else "BIG"
                conf = 88
            elif is_alt(5):
                pred = last_size
                conf = 85
            else:
                ma5 = self.ma(hist, 5)
                ma10 = self.ma(hist, 10)
                ma20 = self.ma(hist, 20)
                ma_trend = "BULLISH" if ma5 > ma10 and ma10 > ma20 else "BEARISH" if ma5 < ma10 and ma10 < ma20 else "NEUTRAL"

                rsi_val = self.rsi(hist, 14)
                rsi_trend = "BULLISH" if rsi_val < 30 else "BEARISH" if rsi_val > 70 else "NEUTRAL"

                recent_30 = hist[-30:] if len(hist) >= 30 else hist
                big_c = sum(1 for x in recent_30 if x >= 5)
                small_c = len(recent_30) - big_c

                votes = {"BIG": 0, "SMALL": 0}
                if streak == 1:
                    votes["SMALL" if last_size == "BIG" else "BIG"] += 1
                if ma_trend == "BULLISH":
                    votes["BIG"] += 3
                elif ma_trend == "BEARISH":
                    votes["SMALL"] += 3
                if rsi_trend == "BULLISH":
                    votes["BIG"] += 2
                elif rsi_trend == "BEARISH":
                    votes["SMALL"] += 2
                if big_c > small_c + 3:
                    votes["SMALL"] += 2
                elif small_c > big_c + 3:
                    votes["BIG"] += 2

                pred = max(votes, key=votes.get)
                total = sum(votes.values())
                diff = votes[pred] - (total - votes[pred])
                if diff >= 4:
                    conf = 92
                elif diff >= 2:
                    conf = 85
                else:
                    conf = 70

        std = self.std_dev(hist, 20)
        std_text = "LOW" if std < 1.5 else "MEDIUM" if std < 2.5 else "HIGH"

        ma5 = self.ma(hist, 5)
        ma10 = self.ma(hist, 10)
        ma20 = self.ma(hist, 20)
        ma_text = "BULLISH" if ma5 > ma10 and ma10 > ma20 else "BEARISH" if ma5 < ma10 and ma10 < ma20 else "NEUTRAL"

        rsi_val = self.rsi(hist, 14)
        pattern_text = "ALTERNATING" if self._is_alt(hist, 4) else "RANDOM"
        cycle_text = "STABLE" if std < 1.5 else "UNSTABLE"

        recent_30 = hist[-30:] if len(hist) >= 30 else hist
        big_c = sum(1 for x in recent_30 if x >= 5)
        small_c = len(recent_30) - big_c
        total = big_c + small_c
        big_pct = int((big_c / total) * 100) if total else 50
        small_pct = 100 - big_pct

        recent_20 = hist[-20:] if len(hist) >= 20 else hist
        if pred == "BIG":
            nums = [x for x in recent_20 if x >= 5]
        else:
            nums = [x for x in recent_20 if x < 5]
        if len(nums) >= 2:
            cnt = Counter(nums)
            top = cnt.most_common(2)
            rng = f"{top[0][0]} • {top[1][0]}"
        else:
            rng = "5 • 9" if pred == "BIG" else "0 • 4"

        return (
            pred,
            conf,
            rng,
            ma_text,
            rsi_val,
            std_text,
            pattern_text,
            cycle_text,
            big_pct,
            small_pct,
        )

    def _is_alt(self, hist: List[int], length: int) -> bool:
        if len(hist) < length:
            return False
        for i in range(1, length):
            if (hist[-i] >= 5) == (hist[-i - 1] >= 5):
                return False
        return True

    def get_next_prediction(self) -> Dict[str, Any]:
        (
            size,
            conf,
            rng,
            ma,
            rsi,
            std,
            pattern,
            cycle,
            big_pct,
            small_pct,
        ) = self.predict_size()
        return {
            "size": size,
            "confidence": conf,
            "range": rng,
            "ma": ma,
            "rsi": rsi,
            "std": std,
            "pattern": pattern,
            "cycle": cycle,
            "big_pct": big_pct,
            "small_pct": small_pct,
        }

    def update_result(self, won: bool):
        if won:
            self.wins += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
        else:
            self.losses += 1
            self.streak = 0
        self.total_predictions += 1

    def send_message(self, text: str):
        if self.chat_id:
            url = TELEGRAM_API + "sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
            http_post(url, payload, timeout=10)

    def start(self, chat_id: int):
        if self.running:
            return
        self.running = True
        self.chat_id = chat_id
        self.send_message("✅ প্রেডিকশন শুরু! (শুধু LEVEL 1-2: ≥85%)")
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False
        self.send_message("⏹ বন্ধ করা হয়েছে।")

    def _loop(self):
        seen = set()
        current_prediction: Optional[Dict[str, Any]] = None

        while self.running:
            try:
                data = self.fetch_data()
                if not data:
                    time.sleep(1)
                    continue

                latest = data[0]
                period = latest.get("issueNumber", "")
                num_str = latest.get("number", "")
                try:
                    number = int(num_str)
                except:
                    number = None

                if not period or not period.isdigit():
                    time.sleep(1)
                    continue

                if period not in seen:
                    if number is not None:
                        self.update(number, period)
                    seen.add(period)

                    next_period = str(int(period) + 1)
                    pred_data = self.get_next_prediction()

                    if pred_data["confidence"] >= 85:
                        current_prediction = {
                            "period": next_period,
                            "size": pred_data["size"],
                            "range": pred_data["range"],
                        }
                        self.send_message(format_prediction_ui(pred_data, next_period))

                if (
                    current_prediction
                    and current_prediction["period"] == period
                    and number is not None
                ):
                    actual_size = "BIG" if number >= 5 else "SMALL"
                    won = actual_size == current_prediction["size"]
                    res = "WIN" if won else "LOSS"
                    self.update_result(won)
                    self.update(
                        number,
                        period,
                        prediction=current_prediction["size"],
                        result=res,
                        range_pred=current_prediction["range"],
                    )
                    self.send_message(
                        format_result_ui(
                            period,
                            number,
                            actual_size,
                            res,
                            current_prediction["size"],
                            current_prediction["range"],
                        )
                    )
                    current_prediction = None

                time.sleep(1)
            except Exception as e:
                print("Loop error:", e)
                time.sleep(2)


# ------------------------------------------------------
#                 টেলিগ্রাম হ্যান্ডলার
# ------------------------------------------------------
predictor = Predictor()
last_update_id = 0


def get_updates(offset: Optional[int] = None) -> List[Dict[str, Any]]:
    url = TELEGRAM_API + "getUpdates"
    params = ""
    if offset is not None:
        params = f"?offset={offset}"
    full_url = url + params
    text = http_get_text(full_url, timeout=35)
    if text:
        try:
            data = json.loads(text)
            return data.get("result", [])
        except json.JSONDecodeError:
            pass
    return []


def main():
    global last_update_id
    print("🤖 বট চালু হচ্ছে... (No External Libs v2.2 - With Add User)")
    print("📊 শুধুমাত্র অনুমোদিত ব্যবহারকারীরা ব্যবহার করতে পারবেন।")

    while True:
        try:
            updates = get_updates(last_update_id + 1 if last_update_id else None)
            for update in updates:
                last_update_id = update["update_id"]

                msg = update.get("message")
                if msg:
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    # চেক করুন ইউজার ইনপুট দিচ্ছে কিনা
                    if chat_id in waiting_for_user_id and waiting_for_user_id[chat_id]:
                        if text.isdigit():
                            new_id = int(text)
                            db.add_authorized_user(new_id)
                            add_authorized_user(new_id)
                            predictor.send_message(f"✅ ইউজার {new_id} যোগ করা হয়েছে।")
                            waiting_for_user_id[chat_id] = False
                        else:
                            predictor.send_message("⚠️ দয়া করে শুধু নাম্বার দিন (যেমন: 123456789)")
                        continue

                    if text.startswith("/"):
                        if not is_authorized(chat_id):
                            http_post(
                                TELEGRAM_API + "sendMessage",
                                {
                                    "chat_id": chat_id,
                                    "text": "⛔ আপনি এই বট ব্যবহার করার অনুমতি পাননি।",
                                },
                            )
                            continue

                    if text == "/start":
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "▶️ START", "callback_data": "start"}],
                                [{"text": "⏹ STOP", "callback_data": "stop"}],
                                [{"text": "📊 STATUS", "callback_data": "status"}],
                                [{"text": "👥 USERS", "callback_data": "users"}],
                                [{"text": "➕ ADD USER", "callback_data": "adduser"}],
                                [{"text": "📞 CONTACT", "url": "https://t.me/your_username"}],
                            ]
                        }
                        http_post(
                            TELEGRAM_API + "sendMessage",
                            {
                                "chat_id": chat_id,
                                "text": "🤖 *SUBHA v2.2 (No External Libs)*\n\n✅ প্রতি পিরিয়ডে প্রেডিকশন\n✅ LEVEL 1 (≥92%) | LEVEL 2 (≥85%)\n✅ অথোরাইজেশন + ডেটাবেস\n✅ বাটনে ইউজার অ্যাড\n\nনিচের বোতাম চাপুন।",
                                "reply_markup": keyboard,
                                "parse_mode": "Markdown",
                            },
                        )
                        continue

                    if text.startswith("/adduser"):
                        if chat_id != SUPER_ADMIN_ID:
                            predictor.send_message("⛔ এই কমান্ড শুধুমাত্র সুপার অ্যাডমিনের জন্য।")
                            continue
                        parts = text.split()
                        if len(parts) != 2 or not parts[1].isdigit():
                            predictor.send_message("⚠️ ব্যবহার: /adduser <user_id>")
                            continue
                        new_id = int(parts[1])
                        db.add_authorized_user(new_id)
                        add_authorized_user(new_id)
                        predictor.send_message(f"✅ ইউজার {new_id} যোগ করা হয়েছে।")
                        continue

                    if text.startswith("/removeuser"):
                        if chat_id != SUPER_ADMIN_ID:
                            predictor.send_message("⛔ এই কমান্ড শুধুমাত্র সুপার অ্যাডমিনের জন্য।")
                            continue
                        parts = text.split()
                        if len(parts) != 2 or not parts[1].isdigit():
                            predictor.send_message("⚠️ ব্যবহার: /removeuser <user_id>")
                            continue
                        rem_id = int(parts[1])
                        if rem_id == SUPER_ADMIN_ID:
                            predictor.send_message("⛔ সুপার অ্যাডমিনকে সরানো যাবে না।")
                            continue
                        db.remove_authorized_user(rem_id)
                        remove_authorized_user(rem_id)
                        predictor.send_message(f"✅ ইউজার {rem_id} সরানো হয়েছে।")
                        continue

                    if text == "/users":
                        if chat_id != SUPER_ADMIN_ID:
                            predictor.send_message("⛔ এই কমান্ড শুধুমাত্র সুপার অ্যাডমিনের জন্য।")
                            continue
                        users = db.get_authorized_users()
                        if users:
                            txt = "📋 *অনুমোদিত ব্যবহারকারী:*\n" + "\n".join(str(u) for u in users)
                        else:
                            txt = "📋 কোনো অনুমোদিত ব্যবহারকারী নেই।"
                        predictor.send_message(txt)
                        continue

                cb = update.get("callback_query")
                if cb:
                    chat_id = cb["message"]["chat"]["id"]
                    data = cb["data"]
                    cb_id = cb["id"]

                    if not is_authorized(chat_id):
                        http_post(
                            TELEGRAM_API + "answerCallbackQuery",
                            {"callback_query_id": cb_id, "text": "⛔ অনুমতি নেই"},
                        )
                        continue

                    http_post(
                        TELEGRAM_API + "answerCallbackQuery",
                        {"callback_query_id": cb_id},
                    )

                    if data == "start":
                        if not predictor.running:
                            predictor.start(chat_id)
                        else:
                            predictor.send_message("⏳ ইতিমধ্যে চলছে...")
                    elif data == "stop":
                        predictor.stop()
                    elif data == "status":
                        stats = (
                            f"📊 *পরিসংখ্যান*\n"
                            f"✅ জয়: {predictor.wins}\n"
                            f"❌ হার: {predictor.losses}\n"
                            f"🔥 স্ট্রিক: {predictor.streak}\n"
                            f"🏆 সেরা: {predictor.best_streak}\n"
                            f"📈 মোট: {predictor.total_predictions}"
                        )
                        predictor.send_message(stats)
                    elif data == "users":
                        if chat_id != SUPER_ADMIN_ID:
                            predictor.send_message("⛔ এই অপশন শুধুমাত্র সুপার অ্যাডমিনের জন্য।")
                            continue
                        users = db.get_authorized_users()
                        if users:
                            txt = "📋 *অনুমোদিত ব্যবহারকারী:*\n" + "\n".join(str(u) for u in users)
                        else:
                            txt = "📋 কোনো অনুমোদিত ব্যবহারকারী নেই।"
                        predictor.send_message(txt)
                    elif data == "adduser":
                        if chat_id != SUPER_ADMIN_ID:
                            predictor.send_message("⛔ এই অপশন শুধুমাত্র সুপার অ্যাডমিনের জন্য।")
                            continue
                        
                        waiting_for_user_id[chat_id] = True
                        predictor.send_message("📝 দয়া করে ইউজার আইডি টাইপ করে পাঠান (শুধু নাম্বার):")

            time.sleep(1)
        except Exception as e:
            print("Main error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()