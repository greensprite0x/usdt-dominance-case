"""
diagnose_jumps.py

Ищет аномальные дневные скачки в рядах капитализаций отдельных монет,
из-за которых знаменатель (капитализация рынка) может прыгнуть на десятки
процентов за сутки.

Что делает:
  A) находит все дневные изменения отдельных монет больше порога;
  B) показывает дни, когда сам знаменатель прыгнул больше порога,
     и раскладывает прыжок по монетам - кто именно его дал;
  C) считает, как выглядел бы ряд рынка без монет-виновников.

Данные: data/coin_caps_wide.csv (скрипт usdt_dominance_refine.py).
Сеть не используется.

Запуск:  python diagnose_jumps.py
Внешних пакетов не требует.
"""

import csv
import os

SRC = "data/coin_caps_wide.csv"
OUT = "data/jump_report.csv"

COIN_JUMP = 0.30      # порог для отдельной монеты: 30% за сутки
MARKET_JUMP = 0.05    # порог для рынка в целом: 5% за сутки
TOP_CONTRIB = 6       # сколько главных вкладчиков показывать в дне-аномалии


def main():
    if not os.path.exists(SRC):
        print(f"Нет файла {SRC}. Сначала запусти usdt_dominance_refine.py")
        return

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    coins = [c for c in rows[0].keys() if c != "date"]
    dates = [r["date"] for r in rows]
    series = {c: {r["date"]: float(r[c]) for r in rows if r[c]} for c in coins}

    # устойчивый состав, как во втором скрипте
    first = dates[0]
    stable = [c for c in coins
              if first in series[c] and len(series[c]) / len(dates) >= 0.95]

    print(f"Монет в файле: {len(coins)}, в устойчивом составе: {len(stable)}")
    print(f"Период: {dates[0]} - {dates[-1]}, дней: {len(dates)}")

    # ---------- A. скачки отдельных монет ----------
    print(f"\nA. Дневные изменения отдельных монет больше {COIN_JUMP:.0%}")
    jumps = []
    for c in stable:
        for prev, cur in zip(dates, dates[1:]):
            a, b = series[c].get(prev), series[c].get(cur)
            if not a or not b:
                continue
            ch = b / a - 1
            if abs(ch) >= COIN_JUMP:
                jumps.append({
                    "date": cur,
                    "coin": c,
                    "change_pct": round(100 * ch, 1),
                    "cap_before_musd": round(a / 1e6, 1),
                    "cap_after_musd": round(b / 1e6, 1),
                    "delta_musd": round((b - a) / 1e6, 1),
                })

    if not jumps:
        print("   не найдено")
    else:
        jumps.sort(key=lambda j: -abs(j["delta_musd"]))
        print(f"   {'дата':<12}{'монета':<18}{'изменение':>12}{'было, $млн':>14}{'стало, $млн':>14}{'вклад, $млн':>14}")
        for j in jumps[:20]:
            print(f"   {j['date']:<12}{j['coin']:<18}{j['change_pct']:>11}%"
                  f"{j['cap_before_musd']:>14,}{j['cap_after_musd']:>14,}{j['delta_musd']:>14,}")
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(jumps[0].keys()))
            w.writeheader()
            w.writerows(jumps)
        print(f"   полный список: {OUT}")

    # ---------- B. скачки самого знаменателя ----------
    print(f"\nB. Дни, когда знаменатель изменился больше чем на {MARKET_JUMP:.0%}")
    totals = {d: sum(series[c][d] for c in stable if d in series[c]) for d in dates}
    suspects = {}
    found = False
    for prev, cur in zip(dates, dates[1:]):
        a, b = totals[prev], totals[cur]
        if not a or abs(b / a - 1) < MARKET_JUMP:
            continue
        found = True
        print(f"\n   {cur}: рынок {a / 1e9:,.0f} -> {b / 1e9:,.0f} млрд $  ({100 * (b / a - 1):+.1f}%)")
        contrib = []
        for c in stable:
            x, y = series[c].get(prev), series[c].get(cur)
            if x is None or y is None:
                continue
            contrib.append((c, y - x, 100 * (y / x - 1) if x else 0))
        contrib.sort(key=lambda t: -abs(t[1]))
        for c, delta, pct in contrib[:TOP_CONTRIB]:
            share = 100 * delta / (b - a) if b != a else 0
            print(f"      {c:<18}{delta / 1e9:>+9,.1f} млрд $   ({pct:+7.1f}% монеты,  {share:5.1f}% прыжка)")
            if abs(share) > 25 and abs(pct) > 50:
                suspects[c] = suspects.get(c, 0) + 1
    if not found:
        print("   не найдено")

    # ---------- C. ряд рынка без подозрительных монет ----------
    if suspects:
        bad = sorted(suspects)
        print(f"\nC. Пересчёт без монет: {', '.join(bad)}")
        clean = [c for c in stable if c not in bad]
        t0 = sum(series[c][dates[0]] for c in clean if dates[0] in series[c])
        t1 = sum(series[c][dates[-1]] for c in clean if dates[-1] in series[c])
        print(f"   рынок без них: {t0 / 1e9:,.0f} -> {t1 / 1e9:,.0f} млрд $  ({100 * (t1 / t0 - 1):+.1f}%)")
        print(f"   для сравнения, текущий расчёт: "
              f"{totals[dates[0]] / 1e9:,.0f} -> {totals[dates[-1]] / 1e9:,.0f} млрд $  "
              f"({100 * (totals[dates[-1]] / totals[dates[0]] - 1):+.1f}%)")
        worst = 0.0
        for prev, cur in zip(dates, dates[1:]):
            a = sum(series[c][prev] for c in clean if prev in series[c])
            b = sum(series[c][cur] for c in clean if cur in series[c])
            if a:
                worst = max(worst, abs(b / a - 1))
        print(f"   максимальное дневное изменение очищенного ряда: {100 * worst:.1f}%")
    else:
        print("\nC. Монет, объясняющих прыжок знаменателя, не выявлено — "
              "возможно, скачок распределён или порог стоит понизить")


if __name__ == "__main__":
    main()
