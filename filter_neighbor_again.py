#!/usr/bin/env python3
"""
detect_handover.py

检测 TARGET 基站的负载(traffic / 用户数 / PRB 利用率等)在某时刻"掉到 0",
同时周围 candidate 基站出现"时间上明显关联的异常升高"——即流量被切换过去。

提供两套互补的检测器:
  1) 事件型 (event-based):
     先找出 target 的"掉到 0"事件,再对每个事件,给每个 candidate 打分:
       - 该 candidate 相对自身基线的升高有多异常 (z-score)
       - 升高与 target 下掉在时间上对得有多齐 (lag)
       - 该 candidate 吸收的量占总升高的比例 (share)
       - 所有 candidate 总升高 vs target 下掉量是否守恒 (conservation)
  2) 连续型 (continuous):
     全序列上做"target 下掉信号"与"candidate 升高信号"的滞后互相关,
     能抓到那种不是干净瞬时掉 0、但时间关联很明显的情况。

把你自己的数据接到 load_data() 里即可,其余全部由 Config 驱动。
"""

from dataclasses import dataclass
import numpy as np
import pandas as pd


# ============================================================
# 配置:按你数据的采样间隔和量纲调这里
# 下面的"窗口"单位都是"采样点数",不是分钟。
# 如果你的数据是 1 分钟一个点、想看前后 10 分钟,就把 pre/post 设成 10。
# 如果是 15 分钟一个点,就设成对应的点数。
# ============================================================
@dataclass
class Config:
    # --- target "掉到 0" 的判定 ---
    active_threshold: float = 30.0   # target 高于此值算"活跃"(掉之前要够忙)
    zero_threshold: float = 5.0      # target 低于此值算"≈0"(掉之后要够空)
    smooth: int = 3                  # 平滑窗口(点数),抑制毛刺;1=不平滑
    pre: int = 10                    # 事件前用多少点确认 target 之前是活跃的
    post: int = 15                   # 事件后用多少点确认 target 维持在 0,并观察 candidate
    zero_persist: float = 0.7        # 事件后 post 窗口内至少这么大比例的点要 ≈0

    # --- candidate 异常升高的判定 ---
    baseline: int = 30               # candidate 基线用事件前多少点估计(均值/方差)
    z_ref: float = 4.0               # z-score 归一化参考值(越大越严)
    z_thr: float = 3.0               # 标记为"异常升高"的 z-score 阈值
    max_lag: int = 20                # 连续型互相关里 candidate 滞后 target 的最大点数

    eps: float = 1e-9


# ============================================================
# 数据加载:把这里换成你自己的数据
# 约定:返回 (target, cand)
#   target: pd.Series, 按时间排好序,index 是时间戳(或整数)
#   cand:   pd.DataFrame, 每列是一个 candidate 基站,index 与 target 对齐
# 两者必须在同一个时间轴上、等间隔、缺失值已处理(见下方 align_to_grid 辅助)
# ============================================================
def load_data_from_csv(path: str,
                       time_col: str,
                       target_col: str,
                       candidate_cols=None,
                       freq: str | None = None):
    """
    宽表 CSV: 一列时间戳 + 每个基站一列。
    candidate_cols=None 表示除 time_col / target_col 外的所有列都当 candidate。
    freq 给定时(如 '1min','15min')会把时间轴对齐到规则网格并前向填充。
    """
    df = pd.read_csv(path)
    df[time_col] = pd.to_datetime(df[time_col])
    df = df.sort_values(time_col).set_index(time_col)

    if candidate_cols is None:
        candidate_cols = [c for c in df.columns if c != target_col]

    if freq is not None:
        df = df.resample(freq).mean()

    df = df.ffill().fillna(0.0)
    target = df[target_col].astype(float)
    cand = df[candidate_cols].astype(float)
    return target, cand


def load_data_from_long_csv(path: str,
                            time_col: str,
                            station_col: str,
                            value_col: str,
                            target_station,
                            freq: str | None = None):
    """
    长表 CSV: 三列 时间戳 / 基站ID / 数值。会自动 pivot 成宽表。
    target_station 指明哪一个 station 是 target。
    """
    df = pd.read_csv(path)
    df[time_col] = pd.to_datetime(df[time_col])
    wide = df.pivot_table(index=time_col, columns=station_col,
                          values=value_col, aggfunc="mean").sort_index()
    if freq is not None:
        wide = wide.resample(freq).mean()
    wide = wide.ffill().fillna(0.0)
    target = wide[target_station].astype(float)
    cand = wide.drop(columns=[target_station]).astype(float)
    return target, cand


# ============================================================
# 1) 事件型检测
# ============================================================
def detect_target_drops(target: pd.Series, cfg: Config):
    """找出 target 从'活跃'掉到'≈0'的下降沿,返回事件在序列中的整数位置列表。"""
    s = target.rolling(cfg.smooth, min_periods=1, center=True).mean().to_numpy()
    near_zero = s <= cfg.zero_threshold
    active = s >= cfg.active_threshold

    events = []
    for i in range(1, len(s)):
        # i 这一点刚跨入 ≈0,而上一点还不是 ≈0 -> 下降沿
        if near_zero[i] and not near_zero[i - 1]:
            lo = max(0, i - cfg.pre)
            if not active[lo:i].any():
                continue  # 掉之前并不忙,跳过
            hi = min(len(s), i + cfg.post)
            if near_zero[i:hi].mean() >= cfg.zero_persist:
                events.append(i)
    return events


def analyze_event(e: int, target: pd.Series, cand: pd.DataFrame, cfg: Config):
    """对单个事件 e,给每个 candidate 算升高/异常度/滞后/占比,并算守恒比。"""
    n = len(target)
    tvals = target.to_numpy()

    target_pre = tvals[max(0, e - cfg.pre):e].mean()
    post_hi = min(n, e + cfg.post)
    target_post = tvals[e:post_hi].mean()
    drop = max(0.0, target_pre - target_post)

    rows = []
    for c in cand.columns:
        x = cand[c].to_numpy()
        b_lo = max(0, e - cfg.pre - cfg.baseline)
        b_hi = max(0, e - cfg.pre)
        if b_hi - b_lo < 3:                      # 基线太短就退而用事件前 baseline 个点
            b_lo, b_hi = max(0, e - cfg.baseline), e
        base = x[b_lo:b_hi]
        b_mean = base.mean() if len(base) else 0.0
        b_std = base.std() if len(base) else 0.0

        resp = x[e:post_hi]
        if len(resp) == 0:
            continue
        peak_val = resp.max()
        rise = peak_val - b_mean
        z = rise / (b_std + cfg.eps)

        # 滞后 = 升高的"起始点":resp 中第一个明显超过基线(b_mean + z_thr*std)的点
        thresh = b_mean + cfg.z_thr * (b_std + cfg.eps)
        crossings = np.where(resp >= thresh)[0]
        onset_lag = int(crossings[0]) if len(crossings) else int(resp.argmax())

        rows.append(dict(candidate=c, baseline=round(b_mean, 2),
                         peak=round(peak_val, 2), rise=round(rise, 2),
                         z=round(z, 2), lag=onset_lag))

    df = pd.DataFrame(rows)
    if df.empty:
        return df, drop, 0.0

    df["flag"] = (df.z >= cfg.z_thr) & (df.rise > 0)
    total_rise = df.loc[df.rise > 0, "rise"].sum()
    df["share"] = np.where(df.rise > 0, df.rise / (total_rise + cfg.eps), 0.0)
    df["time_score"] = np.clip(1 - df.lag / max(1, cfg.post), 0, 1)
    df["score"] = (
        np.clip(df.z / cfg.z_ref, 0, 1)          # 越异常越高
        * df.time_score                          # 时间越齐越高
        * np.clip(df.rise, 0, None) / (drop + cfg.eps)  # 吸收量相对 target 掉量
    )
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    # 守恒比:只统计被标记为异常的 candidate,≈1 说明掉的量基本被它们吃下
    flagged_rise = df.loc[df.flag, "rise"].sum()
    conservation = flagged_rise / (drop + cfg.eps)
    return df, drop, conservation


# ============================================================
# 2) 连续型:滞后互相关
# ============================================================
def lagged_xcorr(target: pd.Series, cand: pd.DataFrame, cfg: Config):
    """
    全序列上:target 的'下掉'(负 delta 取正) 与 candidate 的'升高'(正 delta)
    在 candidate 滞后 0..max_lag 时的最大相关。corr 越接近 1,关联越强。
    """
    drop_sig = (-target.diff().fillna(0.0)).to_numpy()   # target 掉时为正
    rows = []
    for c in cand.columns:
        rise_sig = cand[c].diff().fillna(0.0).to_numpy()  # candidate 升时为正
        best_lag, best_r = 0, -np.inf
        for lag in range(0, cfg.max_lag + 1):
            a = drop_sig if lag == 0 else drop_sig[:-lag]
            b = rise_sig if lag == 0 else rise_sig[lag:]
            if len(a) < 5 or a.std() < cfg.eps or b.std() < cfg.eps:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            if r > best_r:
                best_r, best_lag = r, lag
        rows.append(dict(candidate=c, best_lag=best_lag, corr=round(best_r, 3)))
    return pd.DataFrame(rows).sort_values("corr", ascending=False).reset_index(drop=True)


# ============================================================
# 跑一遍 + 打印报告
# ============================================================
def run(target: pd.Series, cand: pd.DataFrame, cfg: Config, top_k: int = 5):
    events = detect_target_drops(target, cfg)
    print(f"检测到 {len(events)} 个 target 掉到 0 的事件: "
          f"{[str(target.index[e]) for e in events]}\n")

    for e in events:
        df, drop, cons = analyze_event(e, target, cand, cfg)
        t = target.index[e]
        print(f"=== 事件 @ {t} (序号 {e}) | target 掉量≈{drop:.1f} | "
              f"总升高/掉量(守恒比)≈{cons:.2f} ===")
        show = df.head(top_k)[["candidate", "baseline", "peak", "rise",
                               "z", "lag", "share", "score", "flag"]]
        print(show.to_string(index=False))
        print()

    print("=== 全序列滞后互相关排名 (corr 越高,与 target 下掉关联越强) ===")
    xc = lagged_xcorr(target, cand, cfg)
    print(xc.head(top_k).to_string(index=False))
    return events


# ============================================================
# 合成数据(用于演示/自测;接真实数据时删掉或忽略)
# ============================================================
def make_synthetic(seed: int = 0):
    rng = np.random.default_rng(seed)
    n = 500
    idx = pd.date_range("2026-01-01", periods=n, freq="1min")

    # target: 忙(~100) -> 200 处掉到 ~0 -> 360 处又起来一会儿
    target = np.full(n, 100.0) + rng.normal(0, 4, n)
    target[200:360] = rng.normal(2, 1.5, 160).clip(0)     # 掉到 ~0
    target[360:] = 90 + rng.normal(0, 4, n - 360)

    cand = {}
    # cand_03: 事件同时刻吸收一大半,基线 20 -> 升到 ~65
    c3 = 20 + rng.normal(0, 2, n)
    c3[200:360] += 45
    cand["cand_03"] = c3
    # cand_07: 滞后 4 个点吸收另一部分,基线 12 -> 升到 ~42
    c7 = 12 + rng.normal(0, 2, n)
    c7[204:360] += 30
    cand["cand_07"] = c7
    # 其余 18 个:各种基线的噪声,不应被选中
    for k in range(20):
        name = f"cand_{k:02d}"
        if name in cand:
            continue
        base = rng.uniform(5, 40)
        cand[name] = base + rng.normal(0, 3, n)

    target = pd.Series(target, index=idx, name="target")
    cand = pd.DataFrame(cand, index=idx).sort_index(axis=1)
    return target, cand


if __name__ == "__main__":
    cfg = Config()
    # --- 演示:合成数据 ---
    target, cand = make_synthetic()
    # --- 接真实数据时改成:
    # target, cand = load_data_from_csv("your.csv", time_col="ts",
    #                                   target_col="target", freq="1min")
    run(target, cand, cfg)
