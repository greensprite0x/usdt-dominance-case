"""
export_chart_02_series.py

Готовит данные под график 2 кейса: две точечные диаграммы.

  Панель А - изменение доминации USDT против доходности рынка в тот же день.
             Точки должны лечь почти на прямую: это тождество, а не связь.
  Панель Б  - то же самое, но доходность рынка берётся за следующий день.
             Точки должны рассыпаться в облако: опережения нет.

Доходность рынка считается по капитализации без USDT, чтобы числитель
дроби не попадал в обе оси одновременно.

На выходе:
  data/chart_02_scatter.csv  - по строке на день, обе панели
  сводка в консоли           - корреляции и границы осей для подписей

Источник: data/usdt_dominance_stable.csv (скрипт usdt_dominance_refine.py).
Сеть не используется.

Запуск:  python export_chart_02_series.py
Внешних пакетов не требует.
"""

import csv
import math
import os

SRC = "data/usdt_dominance_stable.csv"
OUT = "data/chart_02_scatter.csv"


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
    if not os.path.exists(SRC):
        print(f"Нет файла {SRC}. Сначала запусти usdt_dominance_refine.py")
        return

    with open(SRC, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    dom = [float(r["dominance_stable_pct"]) for r in rows]
    mkt = [float(r["market_ex_usdt_stable"]) for r in rows]
    dates = [r["date"] for r in rows]

    # дневные изменения
    d_dom = [100 * (dom[i] / dom[i - 1] - 1) for i in range(1, len(rows))]
    d_mkt = [100 * (mkt[i] / mkt[i - 1] - 1) for i in range(1, len(rows))]
    d_dates = dates[1:]

    out = []
    for i in range(len(d_dom)):
        out.append({
            "date": d_dates[i],
            "dominance_change_pct": round(d_dom[i], 4),
            "market_return_same_day_pct": round(d_mkt[i], 4),
            "market_return_next_day_pct": round(d_mkt[i + 1], 4) if i + 1 < len(d_mkt) else "",
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    # корреляции для подписей
    same_x = [r["dominance_change_pct"] for r in out]
    same_y = [r["market_return_same_day_pct"] for r in out]
    nxt = [(r["dominance_change_pct"], r["market_return_next_day_pct"])
           for r in out if r["market_return_next_day_pct"] != ""]
    next_x = [a for a, _ in nxt]
    next_y = [b for _, b in nxt]

    c_same = pearson(same_x, same_y)
    c_next = pearson(next_x, next_y)

    lo = min(min(same_x), min(same_y), min(next_y))
    hi = max(max(same_x), max(same_y), max(next_y))

    print(f"Сохранено: {OUT}  ({len(out)} строк)")
    print(f"Период: {out[0]['date']} - {out[-1]['date']}\n")
    print(f"   Панель А, тот же день:      корреляция {c_same:+.3f}   точек {len(same_x)}")
    print(f"   Панель Б, следующий день:   корреляция {c_next:+.3f}   точек {len(next_x)}")
    print(f"\n   Диапазон значений по обеим осям: от {lo:.2f}% до {hi:.2f}%")
    print(f"   Порог статистической значимости при таком числе наблюдений: примерно 0,21")
    print(f"\n   Колонки: dominance_change_pct - ось X обеих панелей;")
    print(f"            market_return_same_day_pct - ось Y панели А;")
    print(f"            market_return_next_day_pct - ось Y панели Б.")


if __name__ == "__main__":
    main()
