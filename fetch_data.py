# -*- coding: utf-8 -*-
"""
比特币多渠道成交量监控 - 每日数据抓取脚本

渠道划分（与看板一致）:
  1. 原生加密现货   : CoinGecko /coins/markets 接口 (BTC 24h 全所现货成交额, 免 Key)
  2. 原生加密衍生品 : CoinGlass API (可选, 需设置环境变量 COINGLASS_API_KEY);
                     未配置时按行业惯例以现货量的 2.5 倍估算
  3. CME 合规期货   : Yahoo Finance chart 接口抓取 BTC=F 日线 (合约乘数 5 BTC/张)
  4. 美股现货 ETF   : Yahoo Finance chart 接口抓取主要 BTC 现货 ETF 日线 (成交量 x 收盘价)

说明: 不使用 yfinance 库, 直接调用 Yahoo v8 chart 接口 (仅需 requests, 无证书路径问题)

输出: data.json (当日汇总 + 最多 180 天历史, 供前端渲染趋势图)
容错: 单一渠道失败时沿用最近一次成功数据, 不阻塞整体更新
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
HISTORY_DAYS = 180

# 美股主要比特币现货 ETF
ETF_TICKERS = [
    "IBIT",  # 贝莱德
    "FBTC",  # 富达
    "GBTC",  # 灰度
    "ARKB",  # ARK 21Shares
    "BITB",  # Bitwise
    "BTCO",  # Invesco Galaxy
    "EZBC",  # Franklin
    "BRRR",  # Valkyrie
    "HODL",  # VanEck
    "BTCW",  # WisdomTree
]

CME_CONTRACT_BTC = 5  # CME 比特币期货合约乘数: 1 张 = 5 BTC
DERIV_ESTIMATE_RATIO = 2.5  # 无 CoinGlass Key 时, 衍生品/现货 估算倍数

CHANNELS = ["crypto_spot", "crypto_derivatives", "cme_futures", "us_etf"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_existing():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"history": []}


def last_known(history, channel):
    """从历史中取该渠道最近一次成功值"""
    for row in reversed(history):
        if row.get("raw_usd", {}).get(channel, 0):
            return row["raw_usd"][channel]
    return 0


# ---------------------------------------------------------------- 渠道 1: 加密现货
def get_btc_spot_volume():
    """CoinGecko: BTC 24 小时全市场现货成交额 (USD)"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "ids": "bitcoin"}
    headers = {"User-Agent": "Mozilla/5.0 (btc-volume-tracker)"}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            if data and "total_volume" in data[0]:
                return float(data[0]["total_volume"])
        except Exception as e:
            log(f"CoinGecko attempt {attempt + 1} failed: {e}")
    return None


# ---------------------------------------------------------------- 渠道 2: 加密衍生品
def get_crypto_derivatives_volume(spot_vol):
    """CoinGlass 全局衍生品成交量; 无 Key 时按比例估算"""
    api_key = os.environ.get("COINGLASS_API_KEY", "")
    if api_key:
        try:
            url = "https://open-api-v4.coinglass.com/api/futures/volume"
            headers = {"CG-API-KEY": api_key}
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            body = r.json()
            if body.get("code") == "0" and body.get("data"):
                return float(body["data"])
        except Exception as e:
            log(f"CoinGlass failed, fallback to estimate: {e}")
    if spot_vol:
        return spot_vol * DERIV_ESTIMATE_RATIO
    return None


# ---------------------------------------------------------------- 渠道 3 & 4: Yahoo Finance
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def yahoo_daily(ticker, days="5d", exclude_today=False):
    """Yahoo v8 chart 接口: 返回最近一个【完整】交易日 (date, volume, close)

    exclude_today: CME 期货等近 24 小时滚动的品种, 当日 K 线尚未走完,
    需要剔除当日(UTC)K 线, 取上一个完整交易日。
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": days, "interval": "1d"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            r.raise_for_status()
            result = r.json()["chart"]["result"][0]
            ts = result.get("timestamp") or []
            quote = result["indicators"]["quote"][0]
            vols, closes = quote["volume"], quote["close"]
            rows = [
                (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), v, c)
                for t, v, c in zip(ts, vols, closes)
                if v is not None and c is not None and v > 0
            ]
            if exclude_today:
                # 从后往前找第一条非当日的完整 K 线
                rows = [x for x in rows if x[0] != today] or rows
            if rows:
                return rows[-1]
        except Exception as e:
            log(f"Yahoo {ticker} attempt {attempt + 1} failed: {e}")
    return None


def get_etf_and_cme_volumes():
    """返回 (etf_total_usd, cme_notional_usd)"""
    etf_total, cme_total = None, None

    # ---- ETF 成交额 (最近一个交易日, 成交量 x 收盘价)
    total = 0.0
    for t in ETF_TICKERS:
        row = yahoo_daily(t)
        if row:
            total += row[1] * row[2]
    if total > 0:
        etf_total = total

    # ---- CME 期货名义成交额 (合约张数 x 5 BTC x 结算价)
    # CME 近 24 小时滚动交易, 当日 K 线未走完, 取上一个完整交易日
    row = yahoo_daily("BTC=F", exclude_today=True)
    if row:
        cme_total = row[1] * CME_CONTRACT_BTC * row[2]

    return etf_total, cme_total


# ---------------------------------------------------------------- 主流程
def main():
    existing = load_existing()
    history = existing.get("history", [])

    spot = get_btc_spot_volume()
    if spot is None:
        spot = last_known(history, "crypto_spot")
        log(f"spot fallback to last known: {spot}")
    deriv = get_crypto_derivatives_volume(spot)
    if deriv is None:
        deriv = last_known(history, "crypto_derivatives")
    etf, cme = get_etf_and_cme_volumes()
    if etf is None:
        etf = last_known(history, "us_etf")
    if cme is None:
        cme = last_known(history, "cme_futures")

    total = spot + deriv + cme + etf

    def share(v):
        return round(v / total * 100, 2) if total else 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = {
        "date": today,
        "raw_usd": {
            "crypto_spot": round(spot),
            "crypto_derivatives": round(deriv),
            "cme_futures": round(cme),
            "us_etf": round(etf),
        },
        "shares": {
            "crypto_spot": share(spot),
            "crypto_derivatives": share(deriv),
            "cme_futures": share(cme),
            "us_etf": share(etf),
        },
    }

    # 同日重复运行则覆盖
    history = [h for h in history if h.get("date") != today]
    history.append(entry)
    history = sorted(history, key=lambda x: x["date"])[-HISTORY_DAYS:]

    data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "summary": {
            "total_volume_usd": round(total),
            "shares": entry["shares"],
            "raw_usd": entry["raw_usd"],
        },
        "history": history,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log(f"done. total=${total:,.0f}  " + "  ".join(
        f"{k}={v}%" for k, v in entry["shares"].items()))


if __name__ == "__main__":
    sys.exit(main())
