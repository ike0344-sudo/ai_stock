"""미래 참조 차단 검증 — 명세 §26·§42가 가장 중요하다고 한 테스트.

## 방식: 돌연변이 테스트

날짜창 경계만 확인하는 정적 검증보다 강하다. **미래 시점 데이터를 실제로 크게 바꿔놓고,
그보다 과거 시점의 Feature 값이 하나도 안 변하는지** 직접 증명한다.

이 방식은 이 저장소에서 이미 효과가 입증됐다 — `backtesting/ml/features.py`에 같은 형태의
테스트가 있고, 그걸 8개 전략으로 확장했을 때 회귀 안전망이 됐다.

## 왜 이게 제일 중요한가

미래 참조는 **터지지 않는다.** 성적이 좋아질 뿐이다. 그래서 테스트가 없으면
"잘 되는 전략을 찾았다"고 착각한 채 실거래까지 간다. 이 프로젝트의 선행 연구에서
유니버스 선정에 미래 정보가 섞였을 때 성적이 **3배 부풀려진** 사례가 실측됐다.
"""
import numpy as np
import polars as pl
import pytest

from src.data.ingest import normalize
from src.features.engine import compute
from src.features.grid import to_grid
from src.features.windows import (expanding_mean_per_window, lookback_change,
                                   prev_window_sum, ratio, window_sum)


def _ticks(prices, start_sec=0, step=1):
    """가격 배열 → 표준 스키마 DataFrame (09:00:00 + start_sec 부터 step초 간격)."""
    times, base = [], 9 * 3600 + start_sec
    for i in range(len(prices)):
        s = base + i * step
        times.append(f"{s // 3600:02d}{s % 3600 // 60:02d}{s % 60:02d}")
    raw = pl.DataFrame({"time": times, "cur_prc": list(prices),
                        "trde_qty": [10] * len(prices),
                        "pred_pre_sig": [2] * len(prices)}).reverse()   # 원본은 역순
    return normalize(raw, "005930", "2026-08-04", 1000)


# ---------------------------------------------------------------- 창 primitives

def test_window_sum_excludes_current_second():
    """창은 `[t-w, t)` — **t 자신을 포함하면 미래 참조**다."""
    x = np.array([1.0, 2.0, 4.0, 8.0, 16.0])

    out = window_sum(x, 2)

    assert np.isnan(out[0]) and np.isnan(out[1])      # 창이 안 참
    assert out[2] == 1 + 2                            # t=2 → x[0:2], x[2]는 제외
    assert out[3] == 2 + 4
    assert out[4] == 4 + 8


def test_lookback_change_uses_t_minus_1():
    """가격 변화율도 t를 안 본다 — t 가격은 그 순간 체결의 결과다."""
    px = np.array([100.0, 110.0, 121.0, 133.1])

    out = lookback_change(px, 1)

    assert np.isnan(out[0]) and np.isnan(out[1])
    assert out[2] == pytest.approx(110 / 100 - 1)     # t=2 → px[1]/px[0], px[2] 미사용
    assert out[3] == pytest.approx(121 / 110 - 1)


def test_prev_window_is_strictly_before_current_window():
    x = np.array([1.0, 1.0, 5.0, 5.0, 9.0, 9.0])

    assert prev_window_sum(x, 2)[4] == 1 + 1          # [0:2], 현재창 [2:4]보다 앞


def test_expanding_mean_is_causal():
    """확장평균도 `t-w` 이전까지만 본다."""
    x = np.ones(20)

    out = expanding_mean_per_window(x, 5)

    assert np.isnan(out[5])                           # 지나간 창이 1개 미만
    assert out[10] == pytest.approx(5.0)              # [0:5] 합 5 ÷ 창 1개
    assert out[15] == pytest.approx(5.0)


def test_ratio_never_returns_inf():
    """[회귀] 분모 0으로 inf가 나와 470만 행 스캔 후 죽은 사고가 실제로 있었다."""
    out = ratio(np.array([1.0, 1.0, np.nan]), np.array([0.0, 2.0, 2.0]))

    assert np.isnan(out[0]) and out[1] == 0.5 and np.isnan(out[2])
    assert np.isfinite(out[~np.isnan(out)]).all()


# ---------------------------------------------------------------- 엔진 전체 (돌연변이)

def test_all_features_unchanged_when_future_is_mutated():
    """**핵심 테스트.** 미래를 통째로 바꿔도 과거 시점 Feature가 하나도 안 변해야 한다."""
    base = [1000 + (i % 7) for i in range(400)]
    mutated = list(base)
    for i in range(200, 400):                          # t=150 기준 미래를 폭파
        mutated[i] = 99999

    f_base, specs = compute(to_grid(_ticks(base)))
    f_mut, _ = compute(to_grid(_ticks(mutated)))

    t = 150
    changed = []
    for s in specs:
        a, b = f_base[s.name][t], f_mut[s.name][t]
        if a is None and b is None:
            continue
        if (a != a) and (b != b):                      # 둘 다 NaN
            continue
        if a != pytest.approx(b, nan_ok=True):
            changed.append(s.name)

    assert not changed, f"미래 변조에 영향받은 Feature: {changed}"


def test_features_at_t_do_not_see_trade_at_t():
    """t초에 일어난 체결이 t의 Feature에 반영되면 안 된다(창이 `[t-w, t)`이므로)."""
    a = [1000] * 100
    b = list(a)
    b[60] = 5000                                       # t=60의 체결만 바꾼다

    fa, specs = compute(to_grid(_ticks(a)))
    fb, _ = compute(to_grid(_ticks(b)))

    for s in specs:
        x, y = fa[s.name][60], fb[s.name][60]
        if (x != x) and (y != y):
            continue
        assert x == pytest.approx(y, nan_ok=True), f"{s.name}이 t 시점 체결을 봤다"


def test_mutation_does_change_later_features():
    """음성 대조 — 변조가 **미래 시점에서는** 실제로 반영돼야 한다.
    (전부 안 변하면 테스트가 아무것도 검증 못 하는 것이다)"""
    a = [1000] * 400
    b = list(a)
    for i in range(200, 400):
        b[i] = 5000

    fa, specs = compute(to_grid(_ticks(a)))
    fb, _ = compute(to_grid(_ticks(b)))

    diff = [s.name for s in specs
            if not (fa[s.name][300] != fa[s.name][300] and fb[s.name][300] != fb[s.name][300])
            and fa[s.name][300] != pytest.approx(fb[s.name][300], nan_ok=True)]
    assert diff, "변조가 미래 Feature에도 반영되지 않았다 — 테스트가 무의미하다"
