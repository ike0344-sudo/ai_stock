"""슈팅 전조 스캔 고속 경로 — 종목·일자 파일당 O(n), 창 집계는 O(1).

lead 가 실측한 것(2026-08-31):
  parquet 전체 읽기      2017파일 / 77M행 →  5초   (I/O 는 병목이 아니다)
  아래 방식으로 라벨+창집계 전체        → 16초
  backtest-agent 최초 추정                → 40~60분

차이는 전부 "t 마다 틱을 다시 훑느냐"다. t 가 종목·일당 ~390개, 파일이 2017개면
틱 재스캔은 80만 번이다. 1초 격자로 한 번 접어두면 어떤 창이든 누적합 뺄셈 한 번이다.

핵심 3가지만 가져가면 된다:
  1. 1초 격자로 접기 (np.bincount) — 틱 수와 무관하게 이후 비용이 23401 로 고정
  2. 누적합 한 번 → 임의 창 합계는 cv[t+w]-cv[t] (창 길이 3분/10분 추가 비용 0)
  3. 미래 최대는 역순 rolling max 한 번 — t 마다 앞을 보지 않는다
"""
import numpy as np, pandas as pd

SESSION_START, SESSION_END = 32400, 55800   # 09:00:00 ~ 15:30:00
N = SESSION_END - SESSION_START + 1


def to_grid(path):
    """틱 parquet → 1초 격자. 정규장 밖은 여기서 버린다.

    **backtest-agent 검증 수정(2026-08-31)**: 원래 이 함수는 `d`를 뒤집지 않고
    바로 sec을 뽑은 뒤 argsort(stable)만 걸었다 — 그러면 같은 초 안에 여러 체결이
    있을 때(원본이 역순=최신이 먼저라서) stable sort가 tie 안의 순서를 "역시간순
    그대로" 보존해버려, 같은 초의 마지막 원소로 남는 게 실제로는 그 초의 *첫*
    체결이 되는 경우가 생긴다. 000150/2026-08-04 한 파일로 직접 대조: 같은 초에
    2건 이상 체결된 4,192초 중 1,914초(45.7%)가 "진짜 마지막 체결가"와 달랐다.
    수정: `d.iloc[::-1]`로 먼저 시간순(오름차순)으로 뒤집은 뒤 정렬 — 같은 파일로
    재검증하니 4,192초 전부(0건 불일치) 일치했다. `vol`/`cnt`(bincount 합산)는
    순서 무관이라 원래도 안 틀렸었다 — 영향은 `px`(따라서 라벨·드리프트·
    변동성·고가위치)에만 있었다."""
    d = pd.read_parquet(path)
    d = d.iloc[::-1]                                     # 원본이 역시간순이라 먼저 뒤집는다
    t = d["time"].astype("int64")
    sec = t // 10000 * 3600 + t // 100 % 100 * 60 + t % 100
    m = ((sec >= SESSION_START) & (sec <= SESSION_END)).to_numpy()
    raw_rows, kept_rows = len(d), int(m.sum())          # 필터 전후 행수 (리포트용)
    if kept_rows == 0:
        return None
    sec = sec.to_numpy()[m] - SESSION_START
    prc = d["cur_prc"].to_numpy()[m]
    qty = d["trde_qty"].to_numpy()[m]
    o = np.argsort(sec, kind="stable")                  # 이제는 안정정렬이 tie도 시간순으로 보존
    sec, prc, qty = sec[o], prc[o], qty[o]

    last = np.zeros(N)
    last[sec] = prc                                     # 같은 초에 여러 체결이면 마지막이 남는다
    px = pd.Series(np.where(last > 0, last, np.nan)).ffill().bfill().to_numpy()

    return dict(
        px=px,
        vol=np.bincount(sec, weights=qty, minlength=N),
        cnt=np.bincount(sec, minlength=N).astype(float),
        raw_rows=raw_rows, kept_rows=kept_rows,
        tick_sec=sec, tick_prc=prc, tick_qty=qty,       # 틱룰 방향 판정용 원본
    )


def label_shoot(px, horizon=600, thresh=0.03):
    """max(px[t..t+horizon])/px[t]-1 >= thresh. 역순 rolling max 한 번이면 끝."""
    fut = pd.Series(px[::-1]).rolling(horizon, min_periods=1).max().to_numpy()[::-1]
    lab = (fut / px - 1) >= thresh
    lab[N - horizon:] = False                           # 미래창이 장 끝을 넘는 t 는 버린다
    return lab


def window_sum(series, w):
    """[t-w, t) 합계. 앞 w 개는 창이 안 차므로 NaN."""
    cs = np.concatenate(([0.0], np.cumsum(series)))
    out = np.full(len(series), np.nan)
    out[w:] = cs[w:len(series)] - cs[:len(series) - w]
    return out


def cluster(lab, gap=600):
    """겹치는 슈팅을 한 건으로. 연속 True 덩어리의 첫 t 만 남긴다."""
    idx = np.flatnonzero(lab)
    if len(idx) == 0:
        return idx
    keep = [idx[0]]
    for i in idx[1:]:
        if i - keep[-1] >= gap:
            keep.append(i)
    return np.array(keep)


if __name__ == "__main__":
    import glob, time
    fs = sorted(glob.glob("data/stocks/tick_al/*/*.parquet"))
    t0 = time.time()
    events = raw = kept = 0
    for f in fs:
        g = to_grid(f)
        if g is None:
            continue
        raw += g["raw_rows"]; kept += g["kept_rows"]
        lab = label_shoot(g["px"])
        for w in (180, 600):                            # 창을 늘려도 비용이 안 는다
            window_sum(g["vol"], w); window_sum(g["cnt"], w)
        events += len(cluster(lab))
    dt = time.time() - t0
    print(f"{len(fs)}파일 {dt:.1f}초 | 원본 {raw:,}행 → 정규장 {kept:,}행 "
          f"(시간외 {100*(1-kept/raw):.1f}%) | 클러스터 슈팅 {events:,}건")
    assert kept < raw, "정규장 필터가 아무것도 안 걸렀다 — 시간 파싱이 틀렸다"
    assert events > 0, "슈팅이 0건 — 라벨 로직이 틀렸다"
