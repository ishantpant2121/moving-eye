"""
v5/indicators/adx.py
====================
Average Directional Index (ADX) and Directional Movement (DMI) calculation.
"""

from typing import List, Sequence


def compute_adx(candles: Sequence[Sequence[float]], period: int = 14) -> List[float]:
    """
    Computes Wilder's smoothed ADX matching legacy regime.py.
    """
    if len(candles) < 2 * period + 1 or period <= 0:
        return []

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(candles)):
        h = float(candles[i][2])
        l = float(candles[i][3])
        prev_h = float(candles[i - 1][2])
        prev_l = float(candles[i - 1][3])
        prev_close = float(candles[i - 1][4])

        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        tr_list.append(tr)

        up_move = h - prev_h
        down_move = prev_l - l

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    def wilder_smooth(values, p):
        if len(values) < p:
            return []
        smoothed = [sum(values[:p])]
        for v in values[p:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / p + v)
        return smoothed

    smooth_tr = wilder_smooth(tr_list, period)
    smooth_plus_dm = wilder_smooth(plus_dm_list, period)
    smooth_minus_dm = wilder_smooth(minus_dm_list, period)

    n = min(len(smooth_tr), len(smooth_plus_dm), len(smooth_minus_dm))
    if n == 0:
        return []

    plus_di = []
    minus_di = []
    for i in range(n):
        if smooth_tr[i] == 0:
            plus_di.append(0.0)
            minus_di.append(0.0)
        else:
            plus_di.append(100.0 * smooth_plus_dm[i] / smooth_tr[i])
            minus_di.append(100.0 * smooth_minus_dm[i] / smooth_tr[i])

    dx_list = []
    for i in range(n):
        di_sum = plus_di[i] + minus_di[i]
        if di_sum == 0:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * abs(plus_di[i] - minus_di[i]) / di_sum)

    if len(dx_list) < period:
        return []

    adx_values = [sum(dx_list[:period]) / period]
    for dx in dx_list[period:]:
        adx_values.append((adx_values[-1] * (period - 1) + dx) / period)

    return adx_values
