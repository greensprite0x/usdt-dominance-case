"""
usdt_dominance_collect.py

Собирает дневные ряды за 90 дней и проверяет, чем на самом деле двигается
"доминация USDT": изменением предложения USDT или изменением цены всего рынка.

Источники:
  1) CoinGecko, публичный API  - дневная капитализация USDT и топ-30 монет
  2) DefiLlama, stablecoins    - дневное предложение USDT, независимая сверка

На выходе три CSV в папке data/ и сводка в консоли.

Запуск:  python usdt_dominance_collect.py
Нужен только пакет requests:  pip install requests
"""

import csv
import math
import os
import time
from datetime import datetime, timezone

import requests

CG = "https://api.coingecko.com/api/v3"
LLAMA_USDT = "https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1"
DAYS = 90
TOP_N = 30
PAUSE = 6          # пауза между запросами к CoinGecko, секунды
OUT_DIR = "data"
UA = {"User-Agent": "dominance-research/1.0"}


def get(url, params=None, tries=5):
    """GET с повторами: публичный API периодически отдаёт 429."""
    delay = PAUSE
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            if r.status_code == 429:
                print(f"   лимит запросов, пауза {delay} c (попытка {attempt})")
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"   ошибка: {e}; пауза {delay} c (попытка {attempt})")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"не удалось получить {url}")


def day(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def top_ids():
    print(f"1/4  Список топ-{TOP_N} монет по капитализации")
    data = get(f"{CG}/coins/markets", {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": TOP_N,
        "page": 1,
        "sparkline": "false",
    })
    ids = [c["id"] for c in data]
    if "tether" not in ids:
        ids.append("tether")
    print("     получено:", ", ".join(ids))
    return ids


def caps_by_day(coin_id):
    data = get(f"{CG}/coins/{coin_id}/market_chart", {
        "vs_currency": "usd",
        "days": DAYS,
        "interval": "daily",
    })
    out = {}
    for ts, cap in data.get("market_caps", []):
        if cap:
            out[day(ts)] = float(cap)
    return out


def llama_usdt():
    print("3/4  Сверка предложения USDT по DefiLlama")
    data = get(LLAMA_USDT)
    out = {}
    for row in data:
        d = datetime.fromtimestamp(int(row["date"]), tz=timezone.utc).strftime("%Y-%m-%d")
        circ = row.get("totalCirculatingUSD") or {}
        val = circ.get("peggedUSD")
        if val:
            out[d] = float(val)
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else float("nan")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ids = top_ids()

    print(f"2/4  Дневные капитализации, {len(ids)} запросов, пауза {PAUSE} c")
    series = {}
    for i, cid in enumerate(ids, 1):
        print(f"     [{i}/{len(ids)}] {cid}")
        series[cid] = caps_by_day(cid)
        time.sleep(PAUSE)

    llama = llama_usdt()

    usdt = series["tether"]
    dates = sorted(d for d in usdt if sum(1 for c in ids if d in series[c]) >= len(ids) - 2)

    rows = []
    for d in dates:
        total = sum(series[c][d] for c in ids if d in series[c])
        cover = sum(1 for c in ids if d in series[c])
        rows.append({
            "date": d,
            "usdt_cap": usdt[d],
            "total_cap_top": total,
            "total_ex_usdt": total - usdt[d],
            "dominance_pct": 100 * usdt[d] / total,
            "coins_covered": cover,
            "usdt_supply_llama": llama.get(d, ""),
        })

    with open(f"{OUT_DIR}/usdt_dominance_daily.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # --- разложение: изменение доли = изменение числителя минус изменение знаменателя
    print("4/4  Разложение дневных изменений доли")
    steps = []
    for a, b in zip(rows, rows[1:]):
        d_usdt = math.log(b["usdt_cap"] / a["usdt_cap"])
        d_total = math.log(b["total_cap_top"] / a["total_cap_top"])
        d_dom = math.log(b["dominance_pct"] / a["dominance_pct"])
        d_ex = math.log(b["total_ex_usdt"] / a["total_ex_usdt"])
        steps.append({
            "date": b["date"],
            "d_dominance_pct": 100 * d_dom,
            "d_usdt_cap_pct": 100 * d_usdt,
            "d_total_cap_pct": 100 * d_total,
            "d_market_ex_usdt_pct": 100 * d_ex,
            "share_numerator": abs(d_usdt) / (abs(d_usdt) + abs(d_total)) if (d_usdt or d_total) else "",
            "share_denominator": abs(d_total) / (abs(d_usdt) + abs(d_total)) if (d_usdt or d_total) else "",
        })

    with open(f"{OUT_DIR}/usdt_dominance_decomposition.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(steps[0].keys()))
        w.writeheader()
        w.writerows(steps)

    num = sum(abs(s["d_usdt_cap_pct"]) for s in steps)
    den = sum(abs(s["d_total_cap_pct"]) for s in steps)
    print(f"\n     Период: {rows[0]['date']} - {rows[-1]['date']}, {len(rows)} дней")
    print(f"     Доминация: {rows[0]['dominance_pct']:.3f}% -> {rows[-1]['dominance_pct']:.3f}%")
    print(f"     Сумма дневных движений числителя (USDT):     {num:7.2f} п.п. лог-изменений")
    print(f"     Сумма дневных движений знаменателя (рынок):  {den:7.2f} п.п. лог-изменений")
    print(f"     Доля знаменателя в общем движении доли:      {100 * den / (num + den):5.1f}%")

    # --- опережает ли доминация рынок
    dd = [s["d_dominance_pct"] for s in steps]
    mk = [s["d_market_ex_usdt_pct"] for s in steps]
    lag_rows = []
    print("\n     Связь изменения доли и доходности рынка без USDT:")
    for lag in range(-3, 4):
        if lag < 0:
            x, y = dd[-lag:], mk[:lag]
        elif lag > 0:
            x, y = dd[:-lag], mk[lag:]
        else:
            x, y = dd, mk
        c = pearson(x, y)
        tag = "доля опережает рынок" if lag > 0 else ("рынок опережает долю" if lag < 0 else "один и тот же день")
        lag_rows.append({"lag_days": lag, "correlation": round(c, 4), "note": tag})
        print(f"       сдвиг {lag:+d} дн.: корреляция {c:+.3f}  ({tag})")

    with open(f"{OUT_DIR}/usdt_dominance_leadlag.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["lag_days", "correlation", "note"])
        w.writeheader()
        w.writerows(lag_rows)

    # --- сверка двух источников по предложению USDT
    diffs = [(r["date"], 100 * (r["usdt_cap"] - float(r["usdt_supply_llama"])) / float(r["usdt_supply_llama"]))
             for r in rows if r["usdt_supply_llama"]]
    if diffs:
        worst = max(diffs, key=lambda t: abs(t[1]))
        print(f"\n     Сверка CoinGecko и DefiLlama по USDT: {len(diffs)} общих дней, "
              f"макс. расхождение {worst[1]:+.2f}% ({worst[0]})")

    print(f"\n     Файлы записаны в папку {OUT_DIR}/")


if __name__ == "__main__":
    main()
