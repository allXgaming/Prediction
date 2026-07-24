# ============================================================
#                   SINGLE FILE – WINGO PREDICTION BOT
#                   (auth + db + bot একত্রে)
# ============================================================

import time
import threading
import math
import sqlite3
from collections import deque, Counter
from typing import Optional, Dict, Any, List, Set

import requests

# ---------------------- AUTH PART ----------------------------
AUTHORIZED_USER_IDS: Set[int] = {
    7237785856,   # ← আপনার টেলিগ্রাম আইডি দিন (সুপার অ্যাডমিন)
}

def is_authorized(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    return user_id in AUTHORIZED_USER_IDS

def add_authorized_user(user_id: int) -> None:
    AUTHORIZED_USER_IDS.add(user_id)

def remove_authorized_user(user_id: int) -> None:
    AUTHORIZED_USER_IDS.discard(user_id)


# ---------------------- DB PART ------------------------------
class UniversalDataManager:
    """সাধারণ SQLite ডেটা ম্যানেজার"""

    def __init__(
        self,
        db_file: str = "data.db",
        table_name: str = "records",
        primary_key: str = "id",
        columns: Optional[Dict[str, str]] = None,
    ):
        self.db_file = db_file
        self.table_name = table_name
        self.primary_key = primary_key
        self.columns = columns or {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        self._init_table()

    def connect(self):
        return sqlite3.connect(self.db_file)

    def _init_table(self):
        col_sql = ", ".join(f"{name} {dtype}" for name, dtype in self.columns.items())
        with self.connect() as conn:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {self.table_name} ({col_sql})")
            conn.commit()

    def insert(self, data: Dict[str, Any]) -> bool:
        if not data:
            return False
        cols = list(data.keys())
        q = f"INSERT INTO {self.table_name} ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
        try:
            with self.connect() as conn:
                conn.execute(q, [data[c] for c in cols])
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Insert Error: {e}")
            return False

    def insert_many(self, data_list: List[Dict[str, Any]]) -> int:
        if not data_list:
            return 0
        cols = list(data_list[0].keys())
        q = f"INSERT INTO {self.table_name} ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
        values = [[d.get(c) for c in cols] for d in data_list]
        try:
            with self.connect() as conn:
                cur = conn.executemany(q, values)
                conn.commit()
                return cur.rowcount
        except sqlite3.Error as e:
            print(f"Insert Many Error: {e}")
            return 0

    def upsert(self, data: Dict[str, Any], conflict_column: Optional[str] = None) -> bool:
        if not data:
            return False
        conflict_column = conflict_column or self.primary_key
        cols = list(data.keys())
        update_cols = [c for c in cols if c != conflict_column]
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        q = f"""
            INSERT INTO {self.table_name} ({', '.join(cols)})
            VALUES ({', '.join(['?']*len(cols))})
            ON CONFLICT({conflict_column}) DO UPDATE SET {set_clause}
        """
        try:
            with self.connect() as conn:
                conn.execute(q, [data[c] for c in cols])
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Upsert Error: {e}")
            return False

    def get_one(self, column: str, value: Any) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(f"SELECT * FROM {self.table_name} WHERE {column}=?", (value,)).fetchone()
            return dict(row) if row else None

    def get_many(
        self,
        column: Optional[str] = None,
        value: Any = None,
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
        descending: bool = False,
    ) -> List[Dict[str, Any]]:
        q = f"SELECT * FROM {self.table_name}"
        params = []
        if column is not None:
            q += f" WHERE {column}=?"
            params.append(value)
        if order_by:
            q += f" ORDER BY {order_by} {'DESC' if descending else 'ASC'}"
        if limit:
            q += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    def get_all(self) -> List[Dict[str, Any]]:
        return self.get_many()

    def update(self, where_column: str, where_value: Any, data: Dict[str, Any]) -> bool:
        if not data:
            return False
        set_clause = ", ".join(f"{k}=?" for k in data.keys())
        q = f"UPDATE {self.table_name} SET {set_clause} WHERE {where_column}=?"
        try:
            with self.connect() as conn:
                conn.execute(q, list(data.values()) + [where_value])
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Update Error: {e}")
            return False

    def delete(self, column: str, value: Any) -> bool:
        try:
            with self.connect() as conn:
                conn.execute(f"DELETE FROM {self.table_name} WHERE {column}=?", (value,))
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Delete Error: {e}")
            return False

    def count(self) -> int:
        with self.connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {self.table_name}").fetchone()[0]

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def execute_write(self, query: str, params: tuple = ()) -> bool:
        try:
            with self.connect() as conn:
                conn.execute(query, params)
                conn.commit()
            return True
        except sqlite3.Error as e:
            print(f"Write Error: {e}")
            return False


class GameDataManager(UniversalDataManager):
    """Wingo বটের জন্য বিশেষায়িত ডেটা ম্যানেজার"""

    def __init__(self, db_file: str = "predictions.db"):
        super().__init__(
            db_file=db_file,
            table_name="rounds",
            primary_key="period",
            columns={
                "period": "TEXT PRIMARY KEY",
                "number": "INTEGER",
                "size": "TEXT",
                "prediction": "TEXT",
                "result": "TEXT",
                "range_pred": "TEXT",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
        self._init_auth_table()

    def _init_auth_table(self):
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS authorized_users (user_id INTEGER PRIMARY KEY)"
            )
            conn.commit()

    def save_round(
        self,
        period: str,
        number: int,
        size: str,
        prediction: Optional[str],
        result: Optional[str],
        range_pred: Optional[str],
    ) -> bool:
        return self.upsert(
            {
                "period": str(period),
                "number": number,
                "size": size,
                "prediction": prediction,
                "result": result,
                "range_pred": range_pred,
            },
            conflict_column="period",
        )

    def get_recent_history(self, limit: int = 300) -> List[Dict[str, Any]]:
        return self.execute_query(
            f"SELECT * FROM {self.table_name} ORDER BY period DESC LIMIT ?",
            (limit,),
        )

    def get_last_round(self) -> Optional[Dict[str, Any]]:
        rows = self.execute_query(
            f"SELECT * FROM {self.table_name} ORDER BY period DESC LIMIT 1"
        )
        return rows[0] if rows else None

    def add_authorized_user(self, user_id: int) -> bool:
        return self.execute_write(
            "INSERT OR IGNORE INTO authorized_users (user_id) VALUES (?)",
            (user_id,),
        )

    def remove_authorized_user(self, user_id: int) -> bool:
        return self.execute_write(
            "DELETE FROM authorized_users WHERE user_id = ?",
            (user_id,),
        )

    def get_authorized_users(self) -> List[int]:
        rows = self.execute_query("SELECT user_id FROM authorized_users")
        return [r["user_id"] for r in rows]

    def is_authorized_db(self, user_id: int) -> bool:
        rows = self.execute_query(
            "SELECT 1 FROM authorized_users WHERE user_id = ? LIMIT 1",
            (user_id,),
        )
        return len(rows) > 0


# ---------------------- BOT PART ------------------------------
# কনফিগ
BOT_TOKEN = "7768747736:AAHRFAiemrbWwo2aCY0geWyBBY385gPJcZ8"   # ← আপনার টোকেন দিন
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/"
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts={}"
SUPER_ADMIN_ID = 5824157133   # ← আপনার টেলিগ্রাম আইডি দিন

# ডেটাবেস অবজেক্ট
db = GameDataManager("predictions.db")
AUTHORIZED_USER_IDS.update(db.get_authorized_users())
AUTHORIZED_USER_IDS.add(SUPER_ADMIN_ID)


# UI ফরম্যাট ফাংশন
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


def format_result_ui(
    period: str,
    number: int,
    actual_size: str,
    result: str,
    pred: str,
    range_pred: str,
) -> str:
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


# প্রেডিক্টর ক্লাস
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

    def update(
        self,
        num: int,
        period: str,
        prediction: Optional[str] = None,
        result: Optional[str] = None,
        range_pred: Optional[str] = None,
    ):
        size = "BIG" if num >= 5 else "SMALL"
        self.history.append(num)
        db.save_round(period, num, size, prediction, result, range_pred)

    def fetch_data(self) -> List[Dict[str, Any]]:
        try:
            ts = int(time.time() * 1000)
            r = requests.get(API_URL.format(ts), timeout=10)
            if r.status_code == 200:
                return r.json().get("data", {}).get("list", [])
        except Exception:
            pass
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

        # স্ট্রিক কাউন্ট
        streak = 1
        for i in range(len(hist) - 2, -1, -1):
            if (hist[i] >= 5) == (last >= 5):
                streak += 1
            else:
                break

        # ------- স্ট্রিক-ভিত্তিক সিদ্ধান্ত -------
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
            # অল্টারনেটিং প্যাটার্ন চেক
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
                pred = last_size  # Trap
                conf = 85
            else:
                # ইন্ডিকেটর ভিত্তিক ভোটিং
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
                # স্ট্রিক ব্রেক ভোট (যদি ১ স্ট্রিক হয়)
                if streak == 1:
                    votes["SMALL" if last_size == "BIG" else "BIG"] += 1
                # ট্রেন্ড
                if ma_trend == "BULLISH":
                    votes["BIG"] += 3
                elif ma_trend == "BEARISH":
                    votes["SMALL"] += 3
                if rsi_trend == "BULLISH":
                    votes["BIG"] += 2
                elif rsi_trend == "BEARISH":
                    votes["SMALL"] += 2
                # সাম্প্রতিক ডিস্ট্রিবিউশন
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

        # ------------------ মেট্রিক্স ------------------
        std = self.std_dev(hist, 20)
        std_text = "LOW" if std < 1.5 else "MEDIUM" if std < 2.5 else "HIGH"

        ma5 = self.ma(hist, 5)
        ma10 = self.ma(hist, 10)
        ma20 = self.ma(hist, 20)
        ma_text = "BULLISH" if ma5 > ma10 and ma10 > ma20 else "BEARISH" if ma5 < ma10 and ma10 < ma20 else "NEUTRAL"

        rsi_val = self.rsi(hist, 14)
        pattern_text = "ALTERNATING" if self._is_alt(hist, 4) else "RANDOM"
        cycle_text = "STABLE" if std < 1.5 else "UNSTABLE"

        # বিগ/স্মল শতাংশ (ভোট অনুযায়ী)
        recent_30 = hist[-30:] if len(hist) >= 30 else hist
        big_c = sum(1 for x in recent_30 if x >= 5)
        small_c = len(recent_30) - big_c
        total = big_c + small_c
        big_pct = int((big_c / total) * 100) if total else 50
        small_pct = 100 - big_pct

        # রেঞ্জ
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
            try:
                requests.post(
                    TELEGRAM_API + "sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=10,
                )
            except Exception:
                pass

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

    # ---------- লুপ ----------
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

                # নতুন পিরিয়ড
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

                # রেজাল্ট চেক
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


# ---------------------- টেলিগ্রাম হ্যান্ডলার -----------------
predictor = Predictor()
last_update_id = 0


def get_updates(offset: Optional[int] = None) -> List[Dict[str, Any]]:
    url = TELEGRAM_API + "getUpdates"
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=35)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception:
        pass
    return []


def main():
    global last_update_id
    print("🤖 বট চালু হচ্ছে... (Single File v2.1 - Python 3.8+ compatible)")
    print("📊 শুধুমাত্র অনুমোদিত ব্যবহারকারীরা ব্যবহার করতে পারবেন।")

    while True:
        try:
            updates = get_updates(last_update_id + 1 if last_update_id else None)
            for update in updates:
                last_update_id = update["update_id"]

                # ---------- মেসেজ ----------
                msg = update.get("message")
                if msg:
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    # অথোরাইজেশন চেক (শুধু /start ও /help বাদে সব কমান্ডের আগে)
                    if text.startswith("/"):
                        if not is_authorized(chat_id):
                            requests.post(
                                TELEGRAM_API + "sendMessage",
                                json={
                                    "chat_id": chat_id,
                                    "text": "⛔ আপনি এই বট ব্যবহার করার অনুমতি পাননি।",
                                },
                                timeout=5,
                            )
                            continue

                    if text == "/start":
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "▶️ START", "callback_data": "start"}],
                                [{"text": "⏹ STOP", "callback_data": "stop"}],
                                [{"text": "📊 STATUS", "callback_data": "status"}],
                                [{"text": "👥 USERS", "callback_data": "users"}],
                                [{"text": "📞 CONTACT", "url": "https://t.me/your_username"}],
                            ]
                        }
                        requests.post(
                            TELEGRAM_API + "sendMessage",
                            json={
                                "chat_id": chat_id,
                                "text": "🤖 *SUBHA v2.1 (Single File)*\n\n✅ প্রতি পিরিয়ডে প্রেডিকশন\n✅ LEVEL 1 (≥92%) | LEVEL 2 (≥85%)\n✅ নতুন UI + অথোরাইজেশন\n✅ ডেটাবেস সংযুক্ত\n\nনিচের বোতাম চাপুন।",
                                "reply_markup": keyboard,
                                "parse_mode": "Markdown",
                            },
                            timeout=10,
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

                # ---------- কলব্যাক ----------
                cb = update.get("callback_query")
                if cb:
                    chat_id = cb["message"]["chat"]["id"]
                    data = cb["data"]
                    cb_id = cb["id"]

                    if not is_authorized(chat_id):
                        requests.post(
                            TELEGRAM_API + "answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": "⛔ অনুমতি নেই"},
                            timeout=5,
                        )
                        continue

                    requests.post(
                        TELEGRAM_API + "answerCallbackQuery",
                        json={"callback_query_id": cb_id},
                        timeout=5,
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

            time.sleep(1)
        except Exception as e:
            print("Main error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()