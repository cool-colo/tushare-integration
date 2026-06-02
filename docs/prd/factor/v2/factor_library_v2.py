# -*- coding: utf-8 -*-
"""
Factor Library (qlib-expression compatible)
============================================

实现 outputs/factor_mining/factor_mapping_readable.csv 中所有因子。

设计:
    1) 实现 qlib 风格的算子(Mean/Std/Ref/Slope/Corr/...),全部基于 pandas;
       每个算子作用于单只股票的时序 Series(按日期升序)。
    2) 因子表达式以字符串形式存储,运行时用受限的 eval 解析,
       将 $field 替换为内部字段表的 Series。
    3) 因子复权类型(adj_type):每个因子标记 前复权/不复权/后复权;
       compute_by_adj_type() 按复权类型路由到对应的数据源。
    4) 大数据平台调用模式:
           df 必须按 (ticker, date) 排序;按 ticker groupby,
           组内调用 FactorEngine.compute(df_group, factor_ids)。

公共 API:
    - FactorEngine.list_factors()       -> pd.DataFrame (含 adj_type 列)
    - FactorEngine.required_fields(...) -> Set[str]
    - FactorEngine.adj_type(factor_id)  -> str
    - FactorEngine.factors_by_adj_type(adj_type) -> List[str]
    - FactorEngine.compute_one(df, factor_id) -> pd.Series
    - FactorEngine.compute(df, factor_ids=None) -> pd.DataFrame
    - FactorEngine.compute_by_adj_type(data_dict, factor_ids=None) -> pd.DataFrame
    - FactorEngine.compute_panel(panel_df, factor_ids=None, group_col='ticker')

输入 df 字段:索引或列必须包含表达式中引用的 $field(去掉 $ 前缀)。
最常见的基础字段:open / close / high / low / volume / amount / vwap / turnover。
宽表因子还需要对应的财务/筹码/情绪字段(见 FactorEngine.required_fields)。
"""

from __future__ import annotations

import ast
import os
import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Set, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Operators (qlib-compatible). All operate on pandas.Series (single ticker TS)
# ---------------------------------------------------------------------------

_EPS = 1e-12


def _as_series(x) -> pd.Series:
    if isinstance(x, pd.Series):
        return x
    # broadcast scalar/array to a Series; caller must ensure shape
    return pd.Series(x)


def op_Ref(x: pd.Series, n: int) -> pd.Series:
    """Lag by n periods (qlib Ref(x, n) == x.shift(n))."""
    return x.shift(int(n))


def op_Mean(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 1:
        return x.astype(float)
    return x.rolling(n, min_periods=1).mean()


def op_Sum(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 1:
        return x.astype(float)
    return x.rolling(n, min_periods=1).sum()


def op_Std(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 1:
        return pd.Series(np.zeros(len(x)), index=x.index)
    return x.rolling(n, min_periods=2).std(ddof=0)


def op_Max(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(int(n), min_periods=1).max()


def op_Min(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(int(n), min_periods=1).min()


def op_Quantile(x: pd.Series, n: int, q: float) -> pd.Series:
    return x.rolling(int(n), min_periods=1).quantile(float(q))


def op_Rank(x: pd.Series, n: int) -> pd.Series:
    """qlib Rank: 当前值在最近 n 期窗口中的百分位 (0~1)。"""
    n = int(n)
    return x.rolling(n, min_periods=1).apply(
        lambda a: (np.sum(a <= a[-1]) - 1) / max(len(a) - 1, 1), raw=True
    )


def op_IdxMax(x: pd.Series, n: int) -> pd.Series:
    """窗口内最大值的位置(0..n-1, 0=窗口最早)。"""
    n = int(n)
    return x.rolling(n, min_periods=1).apply(lambda a: float(np.argmax(a)), raw=True)


def op_IdxMin(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return x.rolling(n, min_periods=1).apply(lambda a: float(np.argmin(a)), raw=True)


def op_Abs(x: pd.Series) -> pd.Series:
    return x.abs()


def op_Log(x: pd.Series) -> pd.Series:
    arr = np.asarray(x, dtype=float)
    # log of non-positive -> NaN (consistent with qlib behavior of safe log)
    out = np.where(arr > 0, np.log(arr, where=arr > 0), np.nan)
    return pd.Series(out, index=x.index if isinstance(x, pd.Series) else None)


def op_Greater(a, b) -> pd.Series:
    """Element-wise max (qlib Greater)."""
    a = _as_series(a)
    b = _as_series(b) if not np.isscalar(b) else b
    return np.maximum(a, b) if np.isscalar(b) else a.where(a >= b, b)


def op_Less(a, b) -> pd.Series:
    """Element-wise min (qlib Less)."""
    a = _as_series(a)
    b = _as_series(b) if not np.isscalar(b) else b
    return np.minimum(a, b) if np.isscalar(b) else a.where(a <= b, b)


def op_If(cond, a, b) -> pd.Series:
    """qlib If(cond, a, b) — element-wise where."""
    if isinstance(cond, pd.Series):
        c = cond.astype(bool)
        idx = cond.index
    else:
        c = np.asarray(cond, dtype=bool)
        idx = a.index if isinstance(a, pd.Series) else (
            b.index if isinstance(b, pd.Series) else None
        )
    a_v = a.values if isinstance(a, pd.Series) else a
    b_v = b.values if isinstance(b, pd.Series) else b
    return pd.Series(np.where(c, a_v, b_v), index=idx)


def op_Corr(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return a.rolling(n, min_periods=2).corr(b)


def op_Cov(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return a.rolling(n, min_periods=2).cov(b)


def op_Skew(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(int(n), min_periods=3).skew()


def op_Kurt(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(int(n), min_periods=4).kurt()


def op_EMA(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=int(n), adjust=False, min_periods=1).mean()


def op_SMA(x: pd.Series, n: int, m: int = 1) -> pd.Series:
    """Smoothed moving average: SMA(x, n, m) = (x*m + prev*(n-m)) / n."""
    n, m = int(n), int(m)
    out = np.empty(len(x))
    out[:] = np.nan
    arr = x.values.astype(float)
    first_valid = 0
    for i in range(len(arr)):
        if not np.isnan(arr[i]):
            first_valid = i
            break
    out[first_valid] = arr[first_valid]
    for i in range(first_valid + 1, len(arr)):
        if np.isnan(arr[i]):
            out[i] = out[i - 1]
        else:
            out[i] = (arr[i] * m + out[i - 1] * (n - m)) / n
    return pd.Series(out, index=x.index)


def op_WMA(x: pd.Series, n: int) -> pd.Series:
    """Weighted moving average with linearly increasing weights 1..n."""
    n = int(n)
    weights = np.arange(1, n + 1, dtype=float)
    return x.rolling(n, min_periods=1).apply(
        lambda a: np.dot(a, weights[-len(a):]) / weights[-len(a):].sum(), raw=True
    )


def op_DecayLinear(x: pd.Series, n: int) -> pd.Series:
    """Linearly decaying weighted mean: weight = n, n-1, ..., 1."""
    n = int(n)
    weights = np.arange(n, 0, -1, dtype=float)
    return x.rolling(n, min_periods=1).apply(
        lambda a: np.dot(a, weights[-len(a):]) / weights[-len(a):].sum(), raw=True
    )


def op_Sign(x: pd.Series) -> pd.Series:
    return pd.Series(np.sign(x.values), index=x.index)


def op_Product(x: pd.Series, n: int) -> pd.Series:
    """Rolling product over window n."""
    n = int(n)
    return x.rolling(n, min_periods=1).apply(np.prod, raw=True)


def op_CSRank(x: pd.Series) -> pd.Series:
    """Time-series expanding percentile rank (single-ticker approximation of cross-section rank)."""
    return x.expanding(min_periods=1).apply(
        lambda a: (np.sum(a <= a[-1]) - 1) / max(len(a) - 1, 1), raw=True
    )


def _rolling_regression(y_window: np.ndarray, kind: str) -> float:
    """对自变量 t = 0..n-1 做最小二乘:y = a + b t。
    kind in {"slope", "resi", "rsquare"}.
    """
    n = len(y_window)
    if n < 2 or np.isnan(y_window).any():
        return np.nan
    t = np.arange(n, dtype=float)
    t_mean = t.mean()
    y_mean = y_window.mean()
    dt = t - t_mean
    dy = y_window - y_mean
    denom = np.dot(dt, dt)
    if denom == 0:
        return np.nan
    slope = np.dot(dt, dy) / denom
    if kind == "slope":
        return slope
    intercept = y_mean - slope * t_mean
    y_hat = intercept + slope * t
    if kind == "resi":
        # qlib 的 Resi(x, N) 返回窗口末端样本的残差
        return float(y_window[-1] - y_hat[-1])
    if kind == "rsquare":
        ss_tot = np.dot(dy, dy)
        if ss_tot == 0:
            return np.nan
        ss_res = np.dot(y_window - y_hat, y_window - y_hat)
        return 1.0 - ss_res / ss_tot
    raise ValueError(kind)


def op_Slope(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    if n <= 1:
        return pd.Series(np.zeros(len(x)), index=x.index)
    return x.rolling(n, min_periods=2).apply(
        lambda a: _rolling_regression(a, "slope"), raw=True
    )


def op_Resi(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return x.rolling(n, min_periods=2).apply(
        lambda a: _rolling_regression(a, "resi"), raw=True
    )


def op_Rsquare(x: pd.Series, n: int) -> pd.Series:
    n = int(n)
    return x.rolling(n, min_periods=2).apply(
        lambda a: _rolling_regression(a, "rsquare"), raw=True
    )


# Function name -> implementation
OPERATORS = {
    "Ref": op_Ref,
    "Mean": op_Mean,
    "Sum": op_Sum,
    "Std": op_Std,
    "Max": op_Max,
    "Min": op_Min,
    "Quantile": op_Quantile,
    "Rank": op_Rank,
    "IdxMax": op_IdxMax,
    "IdxMin": op_IdxMin,
    "Abs": op_Abs,
    "Log": op_Log,
    "Greater": op_Greater,
    "Less": op_Less,
    "If": op_If,
    "Corr": op_Corr,
    "Cov": op_Cov,
    "Skew": op_Skew,
    "Kurt": op_Kurt,
    "EMA": op_EMA,
    "SMA": op_SMA,
    "WMA": op_WMA,
    "DecayLinear": op_DecayLinear,
    "Sign": op_Sign,
    "Product": op_Product,
    "CSRank": op_CSRank,
    "Slope": op_Slope,
    "Resi": op_Resi,
    "Rsquare": op_Rsquare,
    "DELAY": op_Ref,
}


# ---------------------------------------------------------------------------
# Expression compiler (qlib expression -> python AST)
# ---------------------------------------------------------------------------

_FIELD_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Name, ast.Load, ast.Call, ast.Compare, ast.BoolOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.And, ast.Or, ast.Not,
    ast.Subscript, ast.Index,
)


def _normalize_expression(expr: str) -> str:
    """$field -> _F["field"];并校验表达式中字段名集合。"""
    return _FIELD_RE.sub(r'_F["\1"]', expr)


def extract_fields(expr: str) -> Set[str]:
    return set(_FIELD_RE.findall(expr))


def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"expression contains disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in OPERATORS:
                raise ValueError(f"unknown operator: {ast.dump(node.func)}")


@lru_cache(maxsize=4096)
def _compile_expression(expr: str):
    py_expr = _normalize_expression(expr)
    tree = ast.parse(py_expr, mode="eval")
    _validate_ast(tree)
    return compile(tree, "<factor-expr>", "eval")


# ---------------------------------------------------------------------------
# Factor registry & engine
# ---------------------------------------------------------------------------

_DEFAULT_MAPPING_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "factor_mapping_readable.csv"
)


class FactorEngine:
    """从因子映射表加载并计算因子。"""

    def __init__(self, mapping_csv: Optional[str] = None,
                 mapping_df: Optional[pd.DataFrame] = None):
        if mapping_df is not None:
            self._mapping = mapping_df.copy()
        else:
            path = mapping_csv or _DEFAULT_MAPPING_CSV
            self._mapping = pd.read_csv(path)
        required_cols = {"factor_id", "expression"}
        missing = required_cols - set(self._mapping.columns)
        if missing:
            raise ValueError(f"factor mapping missing columns: {missing}")
        self._mapping = self._mapping.drop_duplicates(subset=["factor_id"]).reset_index(drop=True)
        self._by_id: Dict[str, Dict[str, str]] = {
            row["factor_id"]: row.to_dict() for _, row in self._mapping.iterrows()
        }

    # ---------------- metadata ----------------
    def list_factors(self) -> pd.DataFrame:
        return self._mapping.copy()

    def factor_ids(self) -> List[str]:
        return list(self._by_id.keys())

    def expression(self, factor_id: str) -> str:
        return self._by_id[factor_id]["expression"]

    def required_fields(self, factor_ids: Optional[Iterable[str]] = None) -> Set[str]:
        ids = list(factor_ids) if factor_ids is not None else self.factor_ids()
        fields: Set[str] = set()
        for fid in ids:
            fields |= extract_fields(self._by_id[fid]["expression"])
        return fields

    def adj_type(self, factor_id: str) -> str:
        """返回因子的复权类型: 前复权/不复权/后复权。"""
        return self._by_id[factor_id].get("adj_type", "不复权")

    def factors_by_adj_type(self, adj_type: str) -> List[str]:
        """按复权类型筛选因子ID列表。"""
        return [fid for fid, info in self._by_id.items()
                if info.get("adj_type", "不复权") == adj_type]

    # ---------------- compute ----------------
    def _evaluate(self, expr: str, fields: Dict[str, pd.Series]) -> pd.Series:
        code = _compile_expression(expr)
        env = {"__builtins__": {}, "_F": fields, **OPERATORS}
        result = eval(code, env, {})
        if np.isscalar(result):
            # 标量退化为长度匹配的 Series
            any_series = next(iter(fields.values()))
            result = pd.Series(np.full(len(any_series), float(result)), index=any_series.index)
        elif not isinstance(result, pd.Series):
            any_series = next(iter(fields.values()))
            result = pd.Series(np.asarray(result, dtype=float), index=any_series.index)
        return result.astype(float)

    @staticmethod
    def _prepare_fields(df: pd.DataFrame, needed: Set[str]) -> Dict[str, pd.Series]:
        fields: Dict[str, pd.Series] = {}
        for name in needed:
            if name not in df.columns:
                fields[name] = pd.Series(np.full(len(df), np.nan), index=df.index)
            else:
                fields[name] = df[name].astype(float)
        return fields

    def compute_one(self, df: pd.DataFrame, factor_id: str) -> pd.Series:
        """对单只股票时序计算单个因子。df 必须按时间升序。"""
        expr = self.expression(factor_id)
        fields = self._prepare_fields(df, extract_fields(expr))
        s = self._evaluate(expr, fields)
        s.name = factor_id
        return s

    def compute(self, df: pd.DataFrame,
                factor_ids: Optional[Iterable[str]] = None) -> pd.DataFrame:
        """对单只股票时序批量计算因子。返回 DataFrame, 列为 factor_id。"""
        ids = list(factor_ids) if factor_ids is not None else self.factor_ids()
        all_fields = self.required_fields(ids)
        fields = self._prepare_fields(df, all_fields)
        out: Dict[str, pd.Series] = {}
        for fid in ids:
            expr = self._by_id[fid]["expression"]
            try:
                out[fid] = self._evaluate(expr, fields)
            except Exception as e:  # noqa: BLE001
                # 出错的因子返回 NaN 列,记录到列名;避免单个因子拖垮整个批次
                out[fid] = pd.Series(np.full(len(df), np.nan), index=df.index)
                out[fid].attrs["error"] = repr(e)
        return pd.DataFrame(out, index=df.index)

    def compute_panel(self, panel_df: pd.DataFrame,
                      factor_ids: Optional[Iterable[str]] = None,
                      group_col: str = "ticker",
                      date_col: str = "date") -> pd.DataFrame:
        """面板数据计算:按 group_col 分组,组内按 date_col 排序后计算。

        返回 DataFrame, 索引与输入一致, 列为 [group_col, date_col, factor_id...]。
        """
        if group_col not in panel_df.columns or date_col not in panel_df.columns:
            raise ValueError(f"panel_df must contain '{group_col}' and '{date_col}' columns")
        ids = list(factor_ids) if factor_ids is not None else self.factor_ids()

        def _per_group(g: pd.DataFrame) -> pd.DataFrame:
            g_sorted = g.sort_values(date_col)
            factors = self.compute(g_sorted, ids)
            return pd.concat([g_sorted[[group_col, date_col]], factors], axis=1)

        return (panel_df
                .groupby(group_col, group_keys=False, sort=False)
                .apply(_per_group)
                .reset_index(drop=True))

    def compute_by_adj_type(
        self,
        data_dict: Dict[str, pd.DataFrame],
        factor_ids: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        """按复权类型路由到对应数据源计算因子（单只股票时序）。

        Args:
            data_dict: {"前复权": df_qfq, "不复权": df_raw, "后复权": df_hfq}
                       至少包含所需复权类型的 DataFrame，索引需一致。
            factor_ids: 要计算的因子列表，默认全部。

        Returns:
            DataFrame, 列为 factor_id, 索引与任一输入 df 一致。
        """
        ids = list(factor_ids) if factor_ids is not None else self.factor_ids()
        groups: Dict[str, List[str]] = {}
        for fid in ids:
            at = self.adj_type(fid)
            groups.setdefault(at, []).append(fid)

        results: Dict[str, pd.Series] = {}
        for at, fids in groups.items():
            df = data_dict.get(at)
            if df is None:
                ref_df = next(iter(data_dict.values()))
                for fid in fids:
                    results[fid] = pd.Series(np.full(len(ref_df), np.nan),
                                             index=ref_df.index)
                continue
            part = self.compute(df, fids)
            for fid in fids:
                results[fid] = part[fid]

        ref_df = next(iter(data_dict.values()))
        return pd.DataFrame({fid: results[fid] for fid in ids}, index=ref_df.index)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_DEFAULT_ENGINE: Optional[FactorEngine] = None


def get_engine(mapping_csv: Optional[str] = None) -> FactorEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None or mapping_csv is not None:
        _DEFAULT_ENGINE = FactorEngine(mapping_csv=mapping_csv)
    return _DEFAULT_ENGINE


def compute_factor(df: pd.DataFrame, factor_id: str) -> pd.Series:
    return get_engine().compute_one(df, factor_id)


def compute_factors(df: pd.DataFrame,
                    factor_ids: Optional[Iterable[str]] = None) -> pd.DataFrame:
    return get_engine().compute(df, factor_ids)


__all__ = [
    "FactorEngine",
    "OPERATORS",
    "get_engine",
    "compute_factor",
    "compute_factors",
    "extract_fields",
]


if __name__ == "__main__":
    import pandas as pd, numpy as np
    rng = np.random.default_rng(0)
    n = 80
    df = pd.DataFrame({
        "open":   100 + rng.normal(0, 1, n).cumsum(),
        "high":   None, "low": None, "close": None,
        "vol": rng.integers(1e6, 5e6, n),
        "amount": rng.integers(1e8, 5e8, n),
        "turn_over": rng.random(n),
    })
    df["close"] = df["open"] + rng.normal(0, 0.5, n)
    df["high"]  = df[["open", "close"]].max(axis=1) + rng.random(n)
    df["low"]   = df[["open", "close"]].min(axis=1) - rng.random(n)
    df["avg_price"] = (df["open"] + df["close"] + df["high"] + df["low"]) / 4

    eng = FactorEngine()
    print(f"Total factors: {len(eng.factor_ids())}")
    print(f"Columns: {list(eng.list_factors().columns)}")

    for at in ["前复权", "不复权", "后复权"]:
        fids = eng.factors_by_adj_type(at)
        print(f"  {at}: {len(fids)} factors")

    sample_ids = ["a158_ma5", "a158_std10", "ms_intraday_pos", "pv_obv_slope", "a158_resi10"]
    out = eng.compute(df, sample_ids)
    print(f"\nSample compute ({len(sample_ids)} factors):")
    print(out.tail())
    print("\nRequired fields:", sorted(eng.required_fields(sample_ids)))
    print("\nAdj types:", {fid: eng.adj_type(fid) for fid in sample_ids})
