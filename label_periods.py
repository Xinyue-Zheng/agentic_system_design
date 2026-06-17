import pandas as pd


def label_periods(df, start_col="start", end_col="end"):
    """Add 'period' and 'duration' columns to df based on the [start, end] interval.

    period   -> the time-of-day bucket(s) the interval covers, comma-joined
                (early_morning 0-6, morning 6-12, afternoon 12-18, night 18-24),
                or "cross-day" if the interval lasts 24 hours or more.
    duration -> total length of the interval as a Timedelta.
    """
    bounds = [(0, "early_morning"), (6, "morning"), (12, "afternoon"), (18, "night")]

    def classify(start, end):
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        duration = end - start
        if duration >= pd.Timedelta(hours=24):
            return "cross-day", duration

        seen, t = [], start
        while t < end:
            name = bounds[0][1]
            for h, n in bounds:
                if t.hour >= h:
                    name = n
            if not seen or seen[-1] != name:
                seen.append(name)
            nxt = next(h for h in (6, 12, 18, 24) if t.hour < h)  # next boundary
            t = t.normalize() + pd.Timedelta(hours=nxt)
        return ", ".join(seen), duration

    df = df.copy()
    df[start_col] = pd.to_datetime(df[start_col])
    df[end_col] = pd.to_datetime(df[end_col])
    res = df.apply(lambda r: classify(r[start_col], r[end_col]), axis=1, result_type="expand")
    df["period"], df["duration"] = res[0], res[1]
    return df


if __name__ == "__main__":
    sample = pd.DataFrame({
        "start": ["2024-01-01 09:00", "2024-01-01 11:00", "2024-01-01 23:00", "2024-01-01 08:00"],
        "end":   ["2024-01-01 10:30", "2024-01-01 14:00", "2024-01-02 02:00", "2024-01-03 10:00"],
    })
    print(label_periods(sample).to_string())
