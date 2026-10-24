"""
export_chart_01_series.py

Готовит данные под график 1 кейса: предложение USDT, капитализация рынка
и доминация USDT, приведённые к 100 на начало периода.

Построение графика делается отдельно, по этому файлу.

На выходе:
  data/chart_01_series.csv   - дневные ряды, индексы и исходные величины
  сводка в консоли           - итоговые изменения за период

Источник: data/usdt_dominance_stable.csv (скрипт usdt_dominance_refine.py).
Сеть не используется.

Запуск:  python export_chart_01_series.py
Внешних пакетов не требует.
"""

import csv
import os

SRC = "data/usdt_dominance_stable.csv"
OUT = "data/chart_01_series.csv"


def main():
    if not os.path.exists(SRC):
        print(f"Нет файла {SRC}. Сначала запусти usdt_dominance_refine.py")
        return

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    usdt0 = float(rows[0]["usdt_cap"])
    market0 = float(rows[0]["total_stable"])
    dom0 = float(rows[0]["dominance_stable_pct"])

    out = []
    for r in rows:
        usdt = float(r["usdt_cap"])
        market = float(r["total_stable"])
        dom = float(r["dominance_stable_pct"])
        out.append({
            "date": r["date"],
            "usdt_supply_index": round(100 * usdt / usdt0, 3),
            "market_cap_index": round(100 * market / market0, 3),
            "dominance_index": round(100 * dom / dom0, 3),
            "usdt_supply_bln_usd": round(usdt / 1e9, 3),
            "market_cap_bln_usd": round(market / 1e9, 3),
            "dominance_pct": round(dom, 4),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    a, b = out[0], out[-1]
    print(f"Сохранено: {OUT}  ({len(out)} дней)")
    print(f"Период: {a['date']} - {b['date']}\n")
    print(f"   Предложение USDT:     {a['usdt_supply_bln_usd']:.1f} -> {b['usdt_supply_bln_usd']:.1f} млрд $   "
          f"({b['usdt_supply_index'] - 100:+.1f}%)")
    print(f"   Капитализация рынка:  {a['market_cap_bln_usd']:.0f} -> {b['market_cap_bln_usd']:.0f} млрд $   "
          f"({b['market_cap_index'] - 100:+.1f}%)")
    print(f"   Доминация USDT:       {a['dominance_pct']:.3f}% -> {b['dominance_pct']:.3f}%   "
          f"({b['dominance_index'] - 100:+.1f}%)")
    print("\n   Колонки с индексами уже приведены к 100 на начало периода,")
    print("   пересчитывать при построении ничего не нужно.")


if __name__ == "__main__":
    main()
