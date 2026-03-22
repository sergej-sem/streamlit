import pandas as pd


def build_overview_stats(
    df: pd.DataFrame,
    *,
    done_mask: pd.Series,
    total_mask: pd.Series | None = None,
    value_label: str,
) -> pd.DataFrame:
    if "Bereich" not in df.columns:
        return pd.DataFrame(columns=["Bereich", value_label, "Gesamt", "Fortschritt"])

    if total_mask is None:
        total_mask = pd.Series(True, index=df.index)

    base = df.loc[total_mask.astype(bool), ["Bereich"]].copy()
    if base.empty:
        return pd.DataFrame(columns=["Bereich", value_label, "Gesamt", "Fortschritt"])

    base[value_label] = done_mask.loc[base.index].astype(bool).astype(int)
    base["_row_count"] = 1
    stats = (
        base.groupby("Bereich", as_index=False)
        .agg({value_label: "sum", "_row_count": "sum"})
    )
    stats = stats.rename(columns={"_row_count": "Gesamt"})
    stats["Fortschritt"] = (
        stats[value_label] / stats["Gesamt"].clip(lower=1) * 100
    ).round(0).astype(int)

    total_row = pd.DataFrame(
        {
            "Bereich": ["Gesamt"],
            value_label: [int(base[value_label].sum())],
            "Gesamt": [len(base)],
        }
    )
    total_row["Fortschritt"] = (
        total_row[value_label] / total_row["Gesamt"].clip(lower=1) * 100
    ).round(0).astype(int)

    return pd.concat([stats.sort_values("Bereich"), total_row], ignore_index=True)
