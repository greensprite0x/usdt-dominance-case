"""
usdt_chain_breakdown.py

Третий шаг. Отвечает на два вопроса:

  A) Что произошло 11-12 августа: реальное погашение на миллиард и возврат
     или переезд предложения между блокчейнами.
     Скрипт разбирает изменение предложения USDT по сетям по дням.

  B) Какого масштаба крупнейшие движения предложения USDT относительно
     капитализации всего рынка. Это арифметический аргумент о том,
     может ли эмиссия стейблкоина механически двигать цены.

Один запрос к DefiLlama плюс данные из data/usdt_dominance_stable.csv,
полученные вторым скриптом. CoinGecko не используется.

Запуск:  python usdt_chain_breakdown.py
"""

import csv
import json
import os
import time
from datetime import datetime, timezone

import requests

LLAMA_TETHER = "https://stablecoins.llama.fi/stablecoin/1"
OUT_DIR = "data"
STABLE_CSV = f"{OUT_DIR}/usdt_dominance_stable.csv"
UA = {"User-Agent": "dominance-research/1.0"}

FOCUS = ("2026-08-08", "2026-08-16")   # окно для разбора августовского события
EVENTS_TOP = 10
MIN_CHAIN_DELTA = 20_000_000           # в разбивке показываем сети с изменением от $20 млн


def get(url, tries=4):
    delay = 10
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            print(f"   ошибка: {e}; пауза {delay} c (попытка {attempt})")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"не удалось получить {url}")


def to_day(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def pegged(block):
    """Достаёт число из вложенного словаря DefiLlama, не завязываясь на имя ключа."""
    if isinstance(block, dict):
        for key in ("peggedUSD", "peggedVar", "peggedEUR"):
            if key in block:
                return float(block[key])
    return None


def parse_chains(data):
    """chain -> {date: circulating_usd}"""
    out = {}
    chains = data.get("chainBalances") or {}
    for chain, body in chains.items():
        tokens = body.get("tokens") if isinstance(body, dict) else None
        if not tokens:
            continue
        series = {}
        for row in tokens:
            d = to_day(row.get("date"))
            val = None
            for key in ("circulating", "totalCirculatingUSD", "totalCirculating"):
                if key in row:
                    val = pegged(row[key])
                    if val is not None:
                        break
            if val is not None:
                series[d] = val
        if series:
            out[chain] = series
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("1/3  Загрузка разбивки USDT по сетям с DefiLlama")
    data = get(LLAMA_TETHER)
    chains = parse_chains(data)
    if not chains:
        print("   не удалось разобрать структуру ответа, сохраняю сырой JSON для разбора")
        with open(f"{OUT_DIR}/usdt_raw.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return
    print(f"   сетей с данными: {len(chains)}")

    all_dates = sorted({d for s in chains.values() for d in s})
    chain_names = sorted(chains, key=lambda c: -max(chains[c].values()))

    with open(f"{OUT_DIR}/usdt_by_chain.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date"] + chain_names + ["total"])
        for d in all_dates:
            vals = [chains[c].get(d, "") for c in chain_names]
            total = sum(v for v in vals if v != "")
            w.writerow([d] + vals + [total])

    totals = {d: sum(chains[c].get(d, 0) for c in chain_names) for d in all_dates}

    # ---------- A. августовское окно ----------
    print(f"\nA. Разбор окна {FOCUS[0]} - {FOCUS[1]} по сетям")
    window = [d for d in all_dates if FOCUS[0] <= d <= FOCUS[1]]
    focus_rows = []
    for prev, cur in zip(window, window[1:]):
        deltas = []
        for c in chain_names:
            a, b = chains[c].get(prev), chains[c].get(cur)
            if a is None or b is None:
                continue
            if abs(b - a) >= MIN_CHAIN_DELTA:
                deltas.append((c, b - a))
        deltas.sort(key=lambda t: -abs(t[1]))
        total_delta = totals[cur] - totals[prev]
        print(f"\n   {cur}:  суммарно {total_delta / 1e6:+,.1f} млн $")
        if not deltas:
            print("      заметных изменений по отдельным сетям нет")
        for c, v in deltas:
            print(f"      {c:<20}{v / 1e6:>+12,.1f} млн $")
            focus_rows.append({"date": cur, "chain": c, "change_musd": round(v / 1e6, 1)})
        gross_plus = sum(v for _, v in deltas if v > 0)
        gross_minus = sum(v for _, v in deltas if v < 0)
        if gross_plus and gross_minus:
            offset = min(gross_plus, -gross_minus)
            print(f"      встречные движения компенсируют друг друга на {offset / 1e6:,.1f} млн $")

    if focus_rows:
        with open(f"{OUT_DIR}/usdt_focus_window.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "chain", "change_musd"])
            w.writeheader()
            w.writerows(focus_rows)

    # ---------- B. масштаб относительно рынка ----------
    print("\nB. Масштаб крупнейших движений предложения относительно рынка")
    if not os.path.exists(STABLE_CSV):
        print(f"   файл {STABLE_CSV} не найден, запусти сначала usdt_dominance_refine.py")
        return
    with open(STABLE_CSV, encoding="utf-8") as f:
        market = {r["date"]: float(r["total_stable"]) for r in csv.DictReader(f)}

    changes = []
    for prev, cur in zip(all_dates, all_dates[1:]):
        if cur not in market:
            continue
        changes.append({
            "date": cur,
            "supply_change_musd": round((totals[cur] - totals[prev]) / 1e6, 1),
            "pct_of_usdt": round(100 * (totals[cur] / totals[prev] - 1), 3),
            "pct_of_market_cap": round(100 * (totals[cur] - totals[prev]) / market[cur], 4),
        })

    top = sorted(changes, key=lambda c: abs(c["supply_change_musd"]), reverse=True)[:EVENTS_TOP]
    top.sort(key=lambda c: c["date"])
    with open(f"{OUT_DIR}/usdt_supply_scale.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "supply_change_musd", "pct_of_usdt", "pct_of_market_cap"])
        w.writeheader()
        w.writerows(top)

    print(f"   {'дата':<12}{'изменение, $млн':>18}{'% от USDT':>12}{'% от капитализации рынка':>28}")
    for r in top:
        print(f"   {r['date']:<12}{r['supply_change_musd']:>18,}{r['pct_of_usdt']:>12}{r['pct_of_market_cap']:>28}")

    biggest = max(changes, key=lambda c: abs(c["pct_of_market_cap"]))
    print(f"\n   Максимум за период: {biggest['date']}, {biggest['supply_change_musd']:,} млн $, "
          f"или {biggest['pct_of_market_cap']}% капитализации рынка")
    print(f"\n   Файлы записаны в папку {OUT_DIR}/")


if __name__ == "__main__":
    main()
