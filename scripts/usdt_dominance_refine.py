"""
usdt_dominance_refine.py

Второй шаг разбора доминации USDT. Решает две задачи:

  A) Пересчитывает ряд доминации по устойчивому составу монет.
     В первом прогоне топ-30 взят по сегодняшней капитализации, из-за чего
     знаменатель в начале периода занижен монетами, которых тогда почти не было.

  B) Событийный анализ по предложению USDT.
     Находит дни с самыми крупными эмиссиями и погашениями USDT и смотрит,
     что происходило с рынком в этот день и в следующие три.
     Это проверка второго слоя: даже если доля бесполезна, само предложение
     стейблкоина может нести сигнал.

Данные по монетам при первом запуске скачиваются и сохраняются в
data/coin_caps_wide.csv. При повторных запусках берутся из этого файла,
сеть больше не нужна.

Запуск:  python usdt_dominance_refine.py
Нужен тот же requests. Файл кладётся рядом с папкой data из первого скрипта.
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
PAUSE = 12            # пауза увеличена: при 6 c публичный API резал каждый пятый запрос
OUT_DIR = "data"
WIDE = f"{OUT_DIR}/coin_caps_wide.csv"
UA = {"User-Agent": "dominance-research/1.0"}

MIN_COVERAGE = 0.95   # монета считается устойчивой, если есть в 95% дней
EVENTS_TOP = 10       # сколько крупнейших движений предложения разбирать
HORIZON = 3           # на сколько дней вперёд смотрим после события


def get(url, params=None, tries=6):
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


def download_wide():
    print(f"Скачивание дневных капитализаций топ-{TOP_N}, пауза {PAUSE} c между запросами")
    markets = get(f"{CG}/coins/markets", {
        "vs_currency": "usd", "order": "market_cap_desc",
        "per_page": TOP_N, "page": 1, "sparkline": "false",
    })
    ids = [c["id"] for c in markets]
    if "tether" not in ids:
        ids.append("tether")

    series = {}
    for i, cid in enumerate(ids, 1):
        print(f"   [{i}/{len(ids)}] {cid}")
        data = get(f"{CG}/coins/{cid}/market_chart", {
            "vs_currency": "usd", "days": DAYS, "interval": "daily",
        })
        series[cid] = {day(ts): float(cap) for ts, cap in data.get("market_caps", []) if cap}
        time.sleep(PAUSE)

    dates = sorted({d for s in series.values() for d in s})
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(WIDE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date"] + ids)
        for d in dates:
            w.writerow([d] + [series[c].get(d, "") for c in ids])
    print(f"   сохранено в {WIDE}")
    return ids, dates, series


def load_wide():
    with open(WIDE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [k for k in rows[0].keys() if k != "date"]
    dates = [r["date"] for r in rows]
    series = {c: {r["date"]: float(r[c]) for r in rows if r[c]} for c in ids}
    print(f"Данные взяты из {WIDE}, сеть не используется")
    return ids, dates, series


def llama_series():
    data = get(LLAMA_USDT)
    out = {}
    for row in data:
        d = datetime.fromtimestamp(int(row["date"]), tz=timezone.utc).strftime("%Y-%m-%d")
        val = (row.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if val:
            out[d] = float(val)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(WIDE):
        ids, dates, series = load_wide()
    else:
        ids, dates, series = download_wide()

    n = len(dates)
    first = dates[0]

    # ---------- A. устойчивый состав ----------
    stable, dropped = [], []
    for c in ids:
        has_first = first in series[c]
        coverage = len(series[c]) / n
        (stable if (has_first and coverage >= MIN_COVERAGE) else dropped).append(c)

    print(f"\nA. Состав знаменателя")
    print(f"   всего монет: {len(ids)}, устойчивых: {len(stable)}")
    if dropped:
        print(f"   исключены (нет данных на начало периода или пропуски): {', '.join(dropped)}")

    rows = []
    for d in dates:
        full = sum(series[c][d] for c in ids if d in series[c])
        stab = sum(series[c][d] for c in stable if d in series[c])
        usdt = series["tether"].get(d)
        if not usdt or not stab:
            continue
        rows.append({
            "date": d,
            "usdt_cap": usdt,
            "total_all30": full,
            "total_stable": stab,
            "dominance_all30_pct": 100 * usdt / full,
            "dominance_stable_pct": 100 * usdt / stab,
            "market_ex_usdt_stable": stab - usdt,
        })

    with open(f"{OUT_DIR}/usdt_dominance_stable.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    a, b = rows[0], rows[-1]
    print(f"   доминация по топ-30 как есть:      {a['dominance_all30_pct']:.3f}%  ->  {b['dominance_all30_pct']:.3f}%")
    print(f"   доминация по устойчивому составу:  {a['dominance_stable_pct']:.3f}%  ->  {b['dominance_stable_pct']:.3f}%")
    delta_art = (a["dominance_all30_pct"] - a["dominance_stable_pct"])
    print(f"   искажение стартовой точки составом выборки: {delta_art:+.3f} п.п.")

    # пересчёт разложения на устойчивом составе
    num = den = 0.0
    for p, q in zip(rows, rows[1:]):
        num += abs(math.log(q["usdt_cap"] / p["usdt_cap"]))
        den += abs(math.log(q["total_stable"] / p["total_stable"]))
    print(f"   доля знаменателя в движении доли (устойчивый состав): {100 * den / (num + den):.1f}%")

    # ---------- B. событийный анализ по предложению ----------
    print(f"\nB. Дни крупнейших изменений предложения USDT")
    llama = llama_series()
    idx = {r["date"]: i for i, r in enumerate(rows)}

    changes = []
    for p, q in zip(rows, rows[1:]):
        s0, s1 = llama.get(p["date"]), llama.get(q["date"])
        if not s0 or not s1:
            continue
        changes.append({
            "date": q["date"],
            "supply_change_usd": s1 - s0,
            "supply_change_pct": 100 * (s1 / s0 - 1),
        })

    if not changes:
        print("   нет пересечения дат с DefiLlama, событийный анализ пропущен")
        return

    def fwd_return(d, h):
        i = idx.get(d)
        if i is None or i + h >= len(rows):
            return None
        return 100 * (rows[i + h]["market_ex_usdt_stable"] / rows[i]["market_ex_usdt_stable"] - 1)

    events = sorted(changes, key=lambda c: abs(c["supply_change_usd"]), reverse=True)[:EVENTS_TOP]
    events.sort(key=lambda c: c["date"])

    out = []
    for e in events:
        row = {
            "date": e["date"],
            "supply_change_musd": round(e["supply_change_usd"] / 1e6, 1),
            "supply_change_pct": round(e["supply_change_pct"], 3),
            "market_same_day_pct": None,
            **{f"market_plus{h}d_pct": None for h in range(1, HORIZON + 1)},
        }
        i = idx.get(e["date"])
        if i is not None and i > 0:
            row["market_same_day_pct"] = round(
                100 * (rows[i]["market_ex_usdt_stable"] / rows[i - 1]["market_ex_usdt_stable"] - 1), 2)
        for h in range(1, HORIZON + 1):
            r = fwd_return(e["date"], h)
            row[f"market_plus{h}d_pct"] = round(r, 2) if r is not None else ""
        out.append(row)

    with open(f"{OUT_DIR}/usdt_supply_events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    print(f"   {'дата':<12}{'изм. предл., $млн':>18}{'%':>8}{'рынок в тот же день':>22}{'+1д':>8}{'+2д':>8}{'+3д':>8}")
    for r in out:
        print(f"   {r['date']:<12}{r['supply_change_musd']:>18}{r['supply_change_pct']:>8}"
              f"{str(r['market_same_day_pct']):>22}{str(r['market_plus1d_pct']):>8}"
              f"{str(r['market_plus2d_pct']):>8}{str(r['market_plus3d_pct']):>8}")

    # корреляция изменения предложения с будущей доходностью рынка, все дни
    print("\n   Корреляция изменения предложения USDT с доходностью рынка (все дни периода):")
    base = [c for c in changes if c["date"] in idx]
    for h in range(0, HORIZON + 1):
        xs, ys = [], []
        for c in base:
            i = idx[c["date"]]
            if i == 0 or i + h >= len(rows):
                continue
            ref = rows[i - 1] if h == 0 else rows[i]
            tgt = rows[i] if h == 0 else rows[i + h]
            xs.append(c["supply_change_pct"])
            ys.append(100 * (tgt["market_ex_usdt_stable"] / ref["market_ex_usdt_stable"] - 1))
        if len(xs) < 3:
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        corr = cov / (dx * dy) if dx and dy else float("nan")
        label = "тот же день" if h == 0 else f"+{h} дн."
        print(f"     {label:<14} корреляция {corr:+.3f}   наблюдений {len(xs)}")

    print(f"\n   Файлы записаны в папку {OUT_DIR}/")


if __name__ == "__main__":
    main()
