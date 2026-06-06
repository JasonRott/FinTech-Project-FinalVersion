"""智能 ETF 投資組合主系統的滾動回測模組。

這個檔案刻意放在原本 Stage 0 ~ Stage 3 之外：
1. 盡量重用既有資料與工具函式。
2. 回測產物全部寫到 backtest/ 與 png/backtest_*，避免覆蓋正常主流程輸出。
3. 回測時每個再平衡日只使用該日期以前的價格資料，避免未來資料洩漏。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.optimize import linprog, minimize
from yahooquery import Ticker

import parameters
from functions import (
    TRUE_MDD_TIME_WARNING_SECONDS,
    USE_TRUE_MDD_OPTIMIZATION,
    VOL_SCORE_CAP,
    VOL_SCORE_FLOOR,
    build_sector_matrix,
    calculate_individual_maxdd_bounds,
    calculate_true_maxdd_score,
    build_quality_constraints,
    compute_benchmark_cov_vector,
    compute_cov_annual,
    compute_feasible_vol_budget,
    custom_minmax_scaler,
    derive_params_from_weights,
    robust_scale,
    shrink_mean_returns,
)
from sentiment_engine.store import get_sentiment_map_asof, load_daily_sentiment


RebalanceFreq = Literal["M", "Q", "6M", "Y"]


# ==========================================
# 使用者主要調整區：回測參數預設值
# ==========================================
# 若你直接執行 backtest_engine.py 而沒有加命令列參數，系統會使用這一區的設定。
# 若執行時另外加上 --freq、--start-date 等參數，命令列參數會覆蓋這裡的預設值。
DEFAULT_BACKTEST_START_DATE = "2021-01-01"
DEFAULT_BACKTEST_END_DATE = None
DEFAULT_REBALANCE_FREQ: RebalanceFreq = "M"  # 可選："M" 每月、"Q" 每季、"6M" 每半年、"Y" 每年
DEFAULT_LOOKBACK_YEARS = 3
DEFAULT_MIN_HISTORY_YEARS = 8
DEFAULT_INITIAL_CAPITAL = 1_000_000.0
DEFAULT_PERIODIC_CONTRIBUTION = 0.0
DEFAULT_BENCHMARK_TICKER = "VT"  # 主基準/無偏好錨改用 VT（全球市值加權，≈市場組合）；VOO 留在 comparison 當 aspirational 對照
DEFAULT_COMPARISON_BENCHMARKS = ("VOO", "VT")
DEFAULT_FETCH_MISSING_DATA = False
DEFAULT_FETCH_PERIOD = "10y"

# 演算法升級工作的圖片集中輸出資料夾，方便集中檢視（V-1/V-6 及未來 arm 比較圖都鏡像到這裡）。
UPGRADE_FIGURES_DIR = Path("upgrade_figures")

_SECTOR_MATRIX_CACHE: dict[tuple[str, ...], tuple[np.ndarray, list[str]]] = {}


def _get_sector_matrix_cached(tickers: list[str]) -> tuple[np.ndarray, list[str]]:
    """快取產業矩陣，避免回測每一期重複讀取與建立相同 ETF 組合的矩陣。"""
    cache_key = tuple(tickers)
    if cache_key not in _SECTOR_MATRIX_CACHE:
        _SECTOR_MATRIX_CACHE[cache_key] = build_sector_matrix(tickers, parameters.AV_DB_FILE)
    return _SECTOR_MATRIX_CACHE[cache_key]


@dataclass
class BacktestConfig:
    start_date: str = DEFAULT_BACKTEST_START_DATE
    end_date: str | None = DEFAULT_BACKTEST_END_DATE
    lookback_years: int = DEFAULT_LOOKBACK_YEARS
    min_history_years: int = DEFAULT_MIN_HISTORY_YEARS
    rebalance_freq: RebalanceFreq = DEFAULT_REBALANCE_FREQ
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    periodic_contribution: float = DEFAULT_PERIODIC_CONTRIBUTION
    corr_threshold: float = 0.99
    dea_threshold: float = 0.80
    max_weight_limit: float = parameters.MAX_WEIGHT_LIMIT
    close_price_cache_file: str = "csv/backtest_close_price_db.csv"
    price_cache_file: str = "csv/backtest_price_db.csv"
    volume_cache_file: str = "csv/backtest_volume_db.csv"
    legacy_price_file: str = "csv/historical_close_price_db.csv"
    static_feature_file: str = "csv/stage0_final_matrix.csv"
    preference_file: str = "json/stage2_ahp_global_weights.json"
    sentiment_cache_file: str = "sentiment_engine/data/sentiment_daily_cache.csv"
    output_dir: str = "backtest"
    report_output_dir: str = "backtest_report"
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER
    comparison_benchmarks: tuple[str, ...] = DEFAULT_COMPARISON_BENCHMARKS
    risk_free_rate: float = 0.04
    fetch_missing_data: bool = DEFAULT_FETCH_MISSING_DATA
    fetch_period: str = DEFAULT_FETCH_PERIOD
    # 若有給（主系統 prompt 回測會帶入剛產生的 user_results/main_*/ 路徑），
    # 本次回測的彙整資料夾會「巢狀」在該使用者資料夾內；None=獨立執行→自成一夾。
    user_results_parent: str | None = None


def _ensure_output_dirs(config: BacktestConfig) -> None:
    os.makedirs(config.output_dir, exist_ok=True)
    os.makedirs("png", exist_ok=True)
    os.makedirs("csv", exist_ok=True)
    for subdir in ("csv", "png", "report"):
        os.makedirs(Path(config.report_output_dir) / subdir, exist_ok=True)


def _safe_path_token(value: object) -> str:
    """將回測參數轉成可用於資料夾名稱的安全字串。"""
    token = str(value).strip().lower().replace("%", "pct")
    token = token.replace("/", "-").replace("\\", "-").replace(":", "-")
    return re.sub(r"[^a-z0-9._-]+", "-", token).strip("-")


def _backtest_run_id(config: BacktestConfig) -> str:
    """用單次回測設定建立穩定資料夾名稱，方便比較不同頻率與參數。"""
    freq = _safe_path_token(config.rebalance_freq)
    dca = _safe_path_token(f"{config.periodic_contribution:g}")
    return (
        f"backtest_{freq}"
        f"_lookback-{config.lookback_years}y"
        f"_minhist-{config.min_history_years}y"
        f"_dca-{dca}"
    )


def _backtest_output_dirs(config: BacktestConfig) -> tuple[str, Path, Path, Path, Path]:
    """回傳本次回測的 run_id 與分類後的 raw/csv/png/report 輸出資料夾。"""
    run_id = _backtest_run_id(config)
    raw_dir = Path(config.output_dir) / run_id
    csv_dir = Path(config.report_output_dir) / "csv" / run_id
    png_dir = Path(config.report_output_dir) / "png" / run_id
    report_dir = Path(config.report_output_dir) / "report" / run_id
    for directory in (raw_dir, csv_dir, png_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return run_id, raw_dir, csv_dir, png_dir, report_dir


def _div_score_col(df: pd.DataFrame) -> str:
    matches = [col for col in df.columns if col.startswith("Div_Score")]
    if not matches:
        raise KeyError("Cannot find Div_Score column in feature matrix.")
    return matches[0]


def _load_static_features(config: BacktestConfig) -> pd.DataFrame:
    df = pd.read_csv(config.static_feature_file)
    required = [
        "ETF",
        "Return_Div (%)",
        "Cost_ExpRatio (%)",
        "Liq_Volume (M)",
        "Liq_AUM (B)",
        "FinBERT_score",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Static feature file misses required columns: {missing}")
    _div_score_col(df)
    return df.drop_duplicates(subset=["ETF"]).reset_index(drop=True)


def _load_global_weights(config: BacktestConfig) -> dict[str, float]:
    with open(config.preference_file, "r", encoding="utf-8") as f:
        payload = json.load(f)
    weights = payload["Global_Weights"]
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Preference weights must sum to a positive value.")
    return {key: float(value) / total for key, value in weights.items()}


def _read_time_series_cache(path: str) -> pd.DataFrame:
    cache = Path(path)
    if not cache.exists():
        return pd.DataFrame()
    df = pd.read_csv(cache, index_col="date", parse_dates=True)
    df = df.sort_index()
    df.columns = [str(col).strip() for col in df.columns]
    return df


def _write_time_series_cache(df: pd.DataFrame, path: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.sort_index().to_csv(output, index_label="date")


def _merge_time_series_update(existing: pd.DataFrame, update: pd.DataFrame) -> pd.DataFrame:
    if update.empty:
        return existing
    if existing.empty:
        return update.sort_index()

    all_dates = existing.index.union(update.index)
    all_cols = existing.columns.union(update.columns)
    merged = existing.reindex(index=all_dates, columns=all_cols)
    # 只覆蓋這次實際抓到的新格子，保留既有長期歷史。
    merged.loc[update.index, update.columns] = update
    return merged.sort_index()


def _tickers_needing_refresh(
    tickers: list[str],
    prices: pd.DataFrame,
    config: BacktestConfig,
) -> list[str]:
    required_start = pd.Timestamp(config.start_date) - pd.DateOffset(years=config.lookback_years)
    min_obs = int(config.min_history_years * 252 * 0.90)
    needs_refresh = []

    for ticker in tickers:
        if ticker not in prices.columns:
            needs_refresh.append(ticker)
            continue

        series = prices[ticker].dropna()
        if series.empty or series.index.min() > required_start or len(series) < min_obs:
            needs_refresh.append(ticker)

    return needs_refresh


def _fetch_price_and_volume(
    tickers: list[str],
    period: str,
    batch_size: int = 40,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_parts: list[pd.DataFrame] = []
    volume_parts: list[pd.DataFrame] = []

    for start in range(0, len(tickers), batch_size):
        batch = tickers[start : start + batch_size]
        data = Ticker(batch, asynchronous=True).history(period=period, interval="1d")
        if isinstance(data, dict) or data is None or data.empty:
            continue

        # 回測拆分資本利得與股息時，價格報酬必須使用 raw close，不能用 adjclose。
        if "close" not in data.columns:
            continue
        price = data["close"].unstack(level=0)
        volume = data["volume"].unstack(level=0)
        price.index = pd.to_datetime(price.index)
        volume.index = pd.to_datetime(volume.index)
        price_parts.append(price)
        volume_parts.append(volume)

    if not price_parts:
        return pd.DataFrame(), pd.DataFrame()

    prices = pd.concat(price_parts, axis=1)
    volumes = pd.concat(volume_parts, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    volumes = volumes.loc[:, ~volumes.columns.duplicated()]
    return prices, volumes


def load_or_fetch_backtest_data(
    tickers: list[str],
    config: BacktestConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices = _read_time_series_cache(config.close_price_cache_file)
    used_adjusted_fallback = False
    if prices.empty:
        warnings.warn(
            "Close price cache is empty; falling back to the existing adjusted-price cache. "
            "Capital gain and dividend income will not be perfectly separated until close prices are fetched.",
            RuntimeWarning,
        )
        prices = _read_time_series_cache(config.price_cache_file)
        used_adjusted_fallback = True
    volumes = _read_time_series_cache(config.volume_cache_file)

    # 若專用回測快取尚未建立，先只讀取原本主系統的價格快取作為 smoke test 與短期驗證來源。
    # 正式五年回測仍建議用 --fetch-missing-data 建立 10y 的 backtest_price_db.csv。
    legacy_prices = _read_time_series_cache(config.legacy_price_file)
    if not legacy_prices.empty:
        # 專用回測快取優先；舊主系統價格快取只補足缺少欄位，避免重複 ticker 欄位造成 join 失敗。
        missing_legacy_cols = [col for col in legacy_prices.columns if col not in prices.columns]
        if prices.empty:
            prices = legacy_prices
        elif missing_legacy_cols:
            prices = prices.join(legacy_prices[missing_legacy_cols], how="outer")

    refresh_tickers = tickers if used_adjusted_fallback and config.fetch_missing_data else _tickers_needing_refresh(tickers, prices, config)
    if refresh_tickers and config.fetch_missing_data:
        # 只刷新歷史長度不足或完全缺失的 ETF，避免每次回測都重新下載完整資料庫。
        new_prices, new_volumes = _fetch_price_and_volume(refresh_tickers, config.fetch_period)
        if not new_prices.empty:
            prices = _merge_time_series_update(prices, new_prices)
            if not new_volumes.empty:
                volumes = _merge_time_series_update(volumes, new_volumes)
            _write_time_series_cache(prices, config.close_price_cache_file)
            if not volumes.empty:
                _write_time_series_cache(volumes, config.volume_cache_file)

    if config.fetch_missing_data and not prices.empty:
        # 即使長期快取已存在，也補最近 10 天，避免回測資料庫停在第一次下載日期。
        available = [ticker for ticker in tickers if ticker in prices.columns]
        recent_prices, recent_volumes = _fetch_price_and_volume(available, "10d")
        if not recent_prices.empty:
            prices = _merge_time_series_update(prices, recent_prices)
            if not recent_volumes.empty:
                volumes = _merge_time_series_update(volumes, recent_volumes)
            _write_time_series_cache(prices, config.close_price_cache_file)
            if not volumes.empty:
                _write_time_series_cache(volumes, config.volume_cache_file)

    available = [ticker for ticker in tickers if ticker in prices.columns]
    return prices[available].sort_index(), volumes[[t for t in available if t in volumes.columns]].sort_index()


def filter_min_history(
    prices: pd.DataFrame,
    config: BacktestConfig,
) -> list[str]:
    start = pd.Timestamp(config.start_date)
    min_start = start - pd.DateOffset(years=config.lookback_years)
    min_obs = int(config.min_history_years * 252 * 0.90)

    eligible = []
    for ticker in prices.columns:
        series = prices[ticker].dropna()
        if series.empty:
            continue
        if series.index.min() <= min_start and len(series) >= min_obs:
            eligible.append(ticker)
    return eligible


def generate_rebalance_dates(
    prices: pd.DataFrame,
    config: BacktestConfig,
) -> list[pd.Timestamp]:
    start = pd.Timestamp(config.start_date)
    end = pd.Timestamp(config.end_date) if config.end_date else prices.index.max()
    freq_map = {"M": "ME", "Q": "QE", "6M": "2QE", "Y": "YE"}
    if config.rebalance_freq not in freq_map:
        raise ValueError(f"Unsupported rebalance frequency: {config.rebalance_freq}")

    calendar_dates = pd.date_range(start=start, end=end, freq=freq_map[config.rebalance_freq])
    trading_dates = []
    index = prices.loc[(prices.index >= start) & (prices.index <= end)].index
    for date in calendar_dates:
        candidates = index[index >= date]
        if len(candidates) > 0:
            trading_dates.append(candidates[0])

    return sorted(set(trading_dates))


def _lookback_prices(
    prices: pd.DataFrame,
    as_of_date: pd.Timestamp,
    lookback_years: int,
) -> pd.DataFrame:
    start = as_of_date - pd.DateOffset(years=lookback_years)
    window = prices.loc[(prices.index >= start) & (prices.index <= as_of_date)].copy()
    min_obs = int(lookback_years * 252 * 0.90)
    usable_cols = window.columns[window.notna().sum() >= min_obs]
    # 只允許向前填補既有歷史價格，不使用 bfill，避免在回測特徵中偷看到未來價格。
    return window[usable_cols].ffill().dropna(axis=1, how="all")


def _forward_returns(
    prices: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    tickers: list[str],
) -> pd.DataFrame:
    window = prices.loc[(prices.index >= start_date) & (prices.index <= end_date), tickers].ffill()
    returns = window.pct_change(fill_method=None).dropna(how="all")
    return returns.dropna(axis=1, how="any")


def _buy_and_hold_period_returns(
    prices: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    weights: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """
    依照再平衡日給定權重買入 ETF，期間不再調整，直到下一個再平衡日才改變持倉。
    回傳值包含期間每日報酬，以及期末價格漂移後的實際權重。
    """
    if weights.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    tickers = [ticker for ticker in weights.index if ticker in prices.columns]
    if not tickers:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    window = prices.loc[(prices.index >= start_date) & (prices.index <= end_date), tickers].ffill().dropna(how="all")
    if len(window) < 2:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    valid_tickers = [ticker for ticker in tickers if pd.notna(window.iloc[0][ticker]) and window.iloc[0][ticker] > 0]
    if not valid_tickers:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    clean_weights = weights[valid_tickers].astype(float)
    clean_weights = clean_weights[clean_weights > 0]
    if clean_weights.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    clean_weights = clean_weights / clean_weights.sum()

    window = window[clean_weights.index].ffill().dropna(how="any")
    if len(window) < 2:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    relative_prices = window / window.iloc[0]
    portfolio_value = relative_prices.dot(clean_weights)
    period_returns = portfolio_value.pct_change(fill_method=None).dropna()

    end_values = clean_weights * relative_prices.iloc[-1]
    drifted_weights = end_values / end_values.sum()
    return period_returns, drifted_weights


def _buy_and_hold_period_components(
    prices: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    weights: pd.Series,
    dividend_yields: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    回傳單一持有區間的三個績效元件：
    1. price_returns：只反映 raw close 價格變動，代表資本利得。
    2. income_rates：用長期平均殖利率估算每日現金股息，不再投入。
    3. total_returns：資本利得加上現金股息後的總財富日報酬。
    """
    if weights.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    tickers = [ticker for ticker in weights.index if ticker in prices.columns]
    if not tickers:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    window = prices.loc[(prices.index >= start_date) & (prices.index <= end_date), tickers].ffill().dropna(how="all")
    if len(window) < 2:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    valid_tickers = [ticker for ticker in tickers if pd.notna(window.iloc[0][ticker]) and window.iloc[0][ticker] > 0]
    if not valid_tickers:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    clean_weights = weights[valid_tickers].astype(float)
    clean_weights = clean_weights[clean_weights > 0]
    if clean_weights.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty
    clean_weights = clean_weights / clean_weights.sum()

    window = window[clean_weights.index].ffill().dropna(how="any")
    if len(window) < 2:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    relative_prices = window / window.iloc[0]
    price_value = relative_prices.dot(clean_weights)
    price_returns = price_value.pct_change(fill_method=None).dropna()

    # 用前一日的自然漂移權重估算當日配息現金；配息留在現金帳戶，不買回 ETF。
    previous_position_values = relative_prices.shift(1).loc[price_returns.index].mul(clean_weights, axis=1)
    previous_price_value = previous_position_values.sum(axis=1)
    drifted_daily_weights = previous_position_values.div(previous_price_value.replace(0, np.nan), axis=0).fillna(0.0)
    daily_yields = dividend_yields.reindex(clean_weights.index).fillna(0.0).astype(float) / 100.0 / 252.0
    income_rates = drifted_daily_weights.dot(daily_yields).rename("Income_Rate")

    total_returns = _combine_price_income_returns(price_returns, income_rates)
    end_values = clean_weights * relative_prices.iloc[-1]
    drifted_weights = end_values / end_values.sum()
    return price_returns, income_rates, total_returns, drifted_weights


def _combine_price_income_returns(price_returns: pd.Series, income_rates: pd.Series) -> pd.Series:
    """把價格日報酬與現金股息收入合成總財富報酬；股息累積為現金，不再投入。"""
    if price_returns.empty:
        return pd.Series(dtype=float)

    aligned_income = income_rates.reindex(price_returns.index).fillna(0.0)
    price_value = 1.0
    dividend_cash = 0.0
    previous_total_wealth = 1.0
    total_returns = []

    for date, price_return in price_returns.items():
        dividend_cash += price_value * aligned_income.loc[date]
        price_value *= 1.0 + price_return
        total_wealth = price_value + dividend_cash
        total_returns.append(total_wealth / previous_total_wealth - 1.0)
        previous_total_wealth = total_wealth

    return pd.Series(total_returns, index=price_returns.index, name=price_returns.name)


def _returns_from_wealth(wealth: pd.Series, cashflows: pd.Series) -> pd.Series:
    """由含現金流的帳戶價值反推日報酬，避免定期定額被誤當成投資績效。"""
    if wealth.empty:
        return pd.Series(dtype=float)

    cashflows = cashflows.reindex(wealth.index).fillna(0.0)
    returns = []
    previous_wealth = 0.0
    for date, value in wealth.items():
        base = previous_wealth + cashflows.loc[date]
        returns.append(value / base - 1.0 if base > 0 else np.nan)
        previous_wealth = value
    return pd.Series(returns, index=wealth.index).dropna()


def _build_wealth_with_cashflows(
    price_returns: pd.Series,
    income_rates: pd.Series,
    funding_dates: list[pd.Timestamp],
    config: BacktestConfig,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """建立不再投入股息的帳戶路徑：價格部位、累積股息現金、總財富、外部投入現金流。"""
    if price_returns.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty, empty

    price_returns = price_returns.sort_index()
    income_rates = income_rates.reindex(price_returns.index).fillna(0.0)
    cashflows = pd.Series(0.0, index=price_returns.index)
    first_funding = True

    for funding_date in funding_dates:
        future_return_dates = price_returns.index[price_returns.index >= funding_date]
        if len(future_return_dates) == 0:
            continue

        effective_date = future_return_dates[0]
        contribution = config.periodic_contribution
        if first_funding:
            contribution += config.initial_capital
            first_funding = False

        if contribution != 0:
            cashflows.loc[effective_date] += contribution

    price_value = 0.0
    dividend_cash = 0.0
    price_values = []
    dividend_cash_values = []
    total_wealth_values = []

    for date, price_return in price_returns.items():
        price_value += cashflows.loc[date]
        dividend_cash += price_value * income_rates.loc[date]
        price_value *= 1.0 + price_return
        price_values.append(price_value)
        dividend_cash_values.append(dividend_cash)
        total_wealth_values.append(price_value + dividend_cash)

    price_nav = pd.Series(price_values, index=price_returns.index)
    dividend_cash_series = pd.Series(dividend_cash_values, index=price_returns.index)
    total_wealth = pd.Series(total_wealth_values, index=price_returns.index)
    return price_nav, dividend_cash_series, total_wealth, cashflows


def _build_nav_with_cashflows(
    returns: pd.Series,
    funding_dates: list[pd.Timestamp],
    config: BacktestConfig,
) -> tuple[pd.Series, pd.Series]:
    """
    建立含資金流入的帳戶淨值。
    初始資金在第一個有效再平衡期投入；定期定額則在每個有效再平衡期投入。
    """
    if returns.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    returns = returns.sort_index()
    cashflows = pd.Series(0.0, index=returns.index)
    first_funding = True

    for funding_date in funding_dates:
        future_return_dates = returns.index[returns.index >= funding_date]
        if len(future_return_dates) == 0:
            continue

        effective_date = future_return_dates[0]
        contribution = config.periodic_contribution
        if first_funding:
            contribution += config.initial_capital
            first_funding = False

        if contribution != 0:
            cashflows.loc[effective_date] += contribution

    account_value = 0.0
    nav_values = []
    for date, period_return in returns.items():
        # 資金在該期報酬實現前投入，因此會參與當期買入後持有的報酬。
        account_value += cashflows.loc[date]
        account_value *= 1.0 + period_return
        nav_values.append(account_value)

    nav = pd.Series(nav_values, index=returns.index)
    return nav, cashflows


def build_asof_feature_matrix(
    static_features: pd.DataFrame,
    prices: pd.DataFrame,
    volumes: pd.DataFrame,
    as_of_date: pd.Timestamp,
    config: BacktestConfig,
    sentiment_daily_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    lookback = _lookback_prices(prices, as_of_date, config.lookback_years)
    returns = lookback.pct_change(fill_method=None).dropna(how="all")
    if returns.empty:
        return pd.DataFrame()

    rows = []
    static = static_features.set_index("ETF")
    div_col = _div_score_col(static_features)
    min_price_obs = int(config.lookback_years * 252 * 0.90)
    # 每個再平衡日只使用該日以前已存在的情緒分數；cache 起始日前會回傳 0.0。
    sentiment_map = get_sentiment_map_asof(
        lookback.columns.astype(str).tolist(),
        as_of_date,
        daily_df=sentiment_daily_df,
        cache_path=config.sentiment_cache_file,
        neutral_score=0.0,
    )
    for ticker in lookback.columns:
        if ticker not in static.index:
            continue
        price = lookback[ticker].dropna()
        ret = returns[ticker].dropna()
        if len(price) < min_price_obs or ret.empty:
            continue

        years = (price.index[-1] - price.index[0]).days / 365.25
        if years <= 0:
            continue

        cagr = ((price.iloc[-1] / price.iloc[0]) ** (1.0 / years) - 1.0) * 100
        vol = ret.std() * np.sqrt(252) * 100
        cumulative = (1 + ret).cumprod()
        max_dd = ((cumulative - cumulative.cummax()) / cumulative.cummax()).min() * 100

        if ticker in volumes.columns:
            volume_window = volumes.loc[lookback.index.min() : as_of_date, ticker].dropna()
            liq_volume = volume_window.mean() / 1_000_000 if not volume_window.empty else static.loc[ticker, "Liq_Volume (M)"]
        else:
            liq_volume = static.loc[ticker, "Liq_Volume (M)"]

        base = static.loc[ticker]
        rows.append(
            {
                "ETF": ticker,
                "Years_Data": round(years, 1),
                "Date": as_of_date.strftime("%Y-%m-%d"),
                "Return_CAGR (%)": round(cagr, 4),
                "Return_Div (%)": base["Return_Div (%)"],
                "Risk_Vol (%)": round(vol, 4),
                "Risk_MaxDD (%)": round(max_dd, 4),
                "Cost_ExpRatio (%)": base["Cost_ExpRatio (%)"],
                "Liq_Volume (M)": liq_volume,
                "Liq_AUM (B)": base["Liq_AUM (B)"],
                div_col: base[div_col],
                "FinBERT_score": sentiment_map.get(str(ticker).strip().upper(), 0.0),
            }
        )

    return pd.DataFrame(rows)


def build_dea_ready_matrix(feature_df: pd.DataFrame) -> pd.DataFrame:
    if feature_df.empty:
        return pd.DataFrame()

    div_col = _div_score_col(feature_df)
    df_dea = pd.DataFrame({"ETF": feature_df["ETF"]})

    # 拆成資本利得與殖利率兩個獨立 DEA 產出（選項 A），與主系統一致。
    df_dea["Out_CAGR"] = custom_minmax_scaler(feature_df["Return_CAGR (%)"], "CAGR")
    df_dea["Out_Div"] = custom_minmax_scaler(feature_df["Return_Div (%)"], "Div")

    norm_vol = custom_minmax_scaler(np.log1p(feature_df["Liq_Volume (M)"]), "Volume")
    norm_aum = custom_minmax_scaler(np.log1p(feature_df["Liq_AUM (B)"]), "AUM")
    df_dea["Out_Liquidity"] = (norm_vol + norm_aum) / 2

    df_dea["Out_Diversity"] = custom_minmax_scaler(feature_df[div_col], "Diversity")
    df_dea["Out_Sentiment"] = custom_minmax_scaler(
        feature_df["FinBERT_score"],
        "Sentiment",
        lower_bound_q=0.05,
        upper_bound_q=0.95,
    )

    norm_risk_vol = custom_minmax_scaler(feature_df["Risk_Vol (%)"], "Risk_Vol")
    norm_maxdd = custom_minmax_scaler(feature_df["Risk_MaxDD (%)"].abs(), "Risk_MaxDD")
    df_dea["In_Risk"] = (norm_risk_vol + norm_maxdd) / 2
    df_dea["In_Cost"] = custom_minmax_scaler(feature_df["Cost_ExpRatio (%)"], "Cost")

    return df_dea[
        ["ETF", "In_Risk", "In_Cost", "Out_CAGR", "Out_Div", "Out_Liquidity", "Out_Diversity", "Out_Sentiment"]
    ]


def solve_dea_scores(dea_df: pd.DataFrame) -> pd.DataFrame:
    input_cols = ["In_Risk", "In_Cost"]
    output_cols = ["Out_CAGR", "Out_Div", "Out_Liquidity", "Out_Diversity"]
    required = input_cols + output_cols
    if dea_df.empty or any(col not in dea_df.columns for col in ["ETF"] + required):
        return pd.DataFrame()

    df = dea_df.dropna(subset=required).reset_index(drop=True)
    if df.empty:
        return pd.DataFrame()

    X = df[input_cols].values
    Y = df[output_cols].values
    n_dmus = len(df)
    n_inputs = X.shape[1]
    n_outputs = Y.shape[1]
    scores = []

    for k in range(n_dmus):
        c = np.concatenate((np.zeros(n_inputs), -Y[k]))
        A_eq = np.concatenate((X[k].reshape(1, -1), np.zeros((1, n_outputs))), axis=1)
        A_ub = np.hstack((-X, Y))
        res = linprog(
            c,
            A_ub=A_ub,
            b_ub=np.zeros(n_dmus),
            A_eq=A_eq,
            b_eq=np.array([1.0]),
            bounds=[(1e-6, None) for _ in range(n_inputs + n_outputs)],
            method="highs",
        )
        scores.append(min(round(-res.fun, 4), 1.0) if res.success else np.nan)

    df["DEA_Score"] = scores
    return df[["ETF", "DEA_Score"] + input_cols + output_cols].sort_values("DEA_Score", ascending=False)


def solve_cross_efficiency(dea_results: pd.DataFrame, dea_threshold: float) -> pd.DataFrame:
    input_cols = ["In_Risk", "In_Cost"]
    output_cols = ["Out_CAGR", "Out_Div", "Out_Liquidity", "Out_Diversity"]
    if dea_results.empty or "DEA_Score" not in dea_results.columns:
        return pd.DataFrame()

    # 候選池改用「取前 25%」百分位門檻（取代絕對 dea_threshold），與主系統一致。
    top_frac = getattr(parameters, "DEA_TOP_FRACTION", 0.25)
    df_valid = dea_results.dropna().reset_index(drop=True)
    n_keep = max(1, int(np.ceil(len(df_valid) * top_frac)))
    df = df_valid.nlargest(n_keep, "DEA_Score").reset_index(drop=True)
    if df.empty:
        return pd.DataFrame()

    X = df[input_cols].values
    Y = df[output_cols].values
    n_dmus = len(df)
    n_inputs = X.shape[1]
    n_outputs = Y.shape[1]
    cross_matrix = np.zeros((n_dmus, n_dmus))

    for k in range(n_dmus):
        c = np.concatenate((np.zeros(n_inputs), -Y[k]))
        A_eq = np.concatenate((X[k].reshape(1, -1), np.zeros((1, n_outputs))), axis=1)
        A_ub = np.hstack((-X, Y))
        res = linprog(
            c,
            A_ub=A_ub,
            b_ub=np.zeros(n_dmus),
            A_eq=A_eq,
            b_eq=np.array([1.0]),
            bounds=[(1e-6, None) for _ in range(n_inputs + n_outputs)],
            method="highs",
        )
        if not res.success:
            cross_matrix[k, :] = np.nan
            continue
        v_star = res.x[:n_inputs]
        u_star = res.x[n_inputs:]
        for j in range(n_dmus):
            denom = np.dot(v_star, X[j])
            cross_matrix[k, j] = np.dot(u_star, Y[j]) / denom if denom > 0 else np.nan

    df["Cross_Score"] = np.round(np.nanmean(cross_matrix, axis=0), 4)
    return df.sort_values("Cross_Score", ascending=False).reset_index(drop=True)


def build_preference_scores(
    candidates: pd.DataFrame,
    feature_df: pd.DataFrame,
    global_weights: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidates.empty or feature_df.empty or "ETF" not in candidates.columns or "ETF" not in feature_df.columns:
        return pd.DataFrame(), pd.DataFrame()

    df = feature_df[feature_df["ETF"].isin(candidates["ETF"])].reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    scaled = scale_preference_features(df)
    feature_map = {
        "Return_CAGR": "Norm_Return_CAGR",
        "Return_Div": "Norm_Return_Div",
        "Risk_Vol": "Norm_Risk_Vol",
        "Risk_MaxDD": "Norm_Risk_MaxDD",
        "Liq_Volume": "Norm_Liq_Volume",
        "Liq_AUM": "Norm_Liq_AUM",
        "Cost_ExpRatio": "Norm_Cost_ExpRatio",
        "Div_Score": "Norm_Div_Score",
        "FinBERT_score": "Norm_FinBERT",
    }

    scores = np.zeros(len(df))
    for key, weight in global_weights.items():
        if key in feature_map:
            scores += scaled[feature_map[key]].values * weight
    df["User_Pref_Score"] = scores
    return df, scaled


def scale_preference_features(feature_df: pd.DataFrame) -> pd.DataFrame:
    """使用與 Stage 2/3 一致的 robust normalization 建立偏好效用特徵。"""
    div_col = _div_score_col(feature_df)
    scaled = pd.DataFrame({"ETF": feature_df["ETF"]})
    scaled["Norm_Return_CAGR"] = robust_scale(feature_df["Return_CAGR (%)"], upper_quantile=getattr(parameters, "PREF_SCORE_CAGR_UPPER_Q", 0.99), lower_quantile=0.01)  # 放寬上尾，獎勵高成長（展示層；noCAGR 最佳化不受影響）
    scaled["Norm_Return_Div"] = robust_scale(feature_df["Return_Div (%)"])
    scaled["Norm_Div_Score"] = robust_scale(feature_df[div_col].fillna(0), upper_quantile=0.95, lower_quantile=0.05)
    scaled["Norm_FinBERT"] = robust_scale(feature_df["FinBERT_score"].fillna(0), upper_quantile=0.95, lower_quantile=0.05)
    scaled["Norm_Liq_Volume"] = robust_scale(np.log1p(feature_df["Liq_Volume (M)"]))
    scaled["Norm_Liq_AUM"] = robust_scale(np.log1p(feature_df["Liq_AUM (B)"]))
    scaled["Norm_Risk_Vol"] = robust_scale(feature_df["Risk_Vol (%)"], is_reverse=True)
    scaled["Norm_Risk_MaxDD"] = robust_scale(feature_df["Risk_MaxDD (%)"].abs(), is_reverse=True)
    scaled["Norm_Cost_ExpRatio"] = robust_scale(feature_df["Cost_ExpRatio (%)"], is_reverse=True)
    return scaled


def select_cluster_representatives(
    scored_df: pd.DataFrame,
    returns_matrix: pd.DataFrame,
    corr_threshold: float,
) -> pd.DataFrame:
    if scored_df.empty or "ETF" not in scored_df.columns:
        return pd.DataFrame()

    tickers = [ticker for ticker in scored_df["ETF"] if ticker in returns_matrix.columns]
    if not tickers:
        return pd.DataFrame()

    corr_matrix = returns_matrix[tickers].corr()
    processed: set[str] = set()
    selected = []
    sorted_tickers = scored_df.sort_values("User_Pref_Score", ascending=False)["ETF"].tolist()

    for ticker in sorted_tickers:
        if ticker in processed or ticker not in corr_matrix.columns:
            continue
        cluster = corr_matrix.index[corr_matrix[ticker] >= corr_threshold].tolist()
        cluster = [member for member in cluster if member not in processed]
        if not cluster:
            continue
        cluster_df = scored_df[scored_df["ETF"].isin(cluster)]
        selected.append(cluster_df.loc[cluster_df["User_Pref_Score"].idxmax()])
        processed.update(cluster)

    return pd.DataFrame(selected).sort_values("User_Pref_Score", ascending=False).reset_index(drop=True)


def _blended_preference_weights(global_weights: dict[str, float]) -> dict[str, float]:
    """建立與主系統 Stage 3 相同的 baseline/user preference 融合權重。"""
    return {
        key: parameters.ALPHA_BASELINE * parameters.BASELINE_WEIGHTS[key]
        + (1 - parameters.ALPHA_BASELINE) * global_weights.get(key, 0.0)
        for key in parameters.BASELINE_WEIGHTS
    }


def calculate_raw_dimension_metrics(
    weights: pd.Series,
    feature_df: pd.DataFrame,
    returns_matrix: pd.DataFrame,
) -> dict[str, float]:
    """計算非正規化的原始偏好維度，方便和 benchmark 做可解釋比較。"""
    if weights.empty or feature_df.empty:
        return {}

    tickers = [ticker for ticker in weights.index if ticker in feature_df["ETF"].values]
    if not tickers:
        return {}

    clean_weights = weights[tickers].astype(float)
    clean_weights = clean_weights[clean_weights > 0]
    if clean_weights.empty:
        return {}
    clean_weights = clean_weights / clean_weights.sum()
    tickers = clean_weights.index.tolist()

    feature = feature_df.set_index("ETF").loc[tickers]
    w = clean_weights.values
    metrics = {
        "Raw_Return_CAGR_%": float(np.dot(w, feature["Return_CAGR (%)"].fillna(0).values)),
        "Raw_Dividend_Yield_%": float(np.dot(w, feature["Return_Div (%)"].fillna(0).values)),
        "Raw_Expense_Ratio_%": float(np.dot(w, feature["Cost_ExpRatio (%)"].fillna(0).values)),
        "Raw_Liquidity_Volume_M": float(np.dot(w, feature["Liq_Volume (M)"].fillna(0).values)),
        "Raw_Liquidity_AUM_B": float(np.dot(w, feature["Liq_AUM (B)"].fillna(0).values)),
        "Raw_FinBERT_Score": float(np.dot(w, feature["FinBERT_score"].fillna(0).values)),
    }

    usable_returns = returns_matrix[[ticker for ticker in tickers if ticker in returns_matrix.columns]].dropna(how="any")
    if not usable_returns.empty and list(usable_returns.columns) == tickers:
        port_returns = usable_returns.dot(clean_weights)
        cumulative = (1.0 + port_returns).cumprod()
        metrics["Raw_Portfolio_Volatility_%"] = float(port_returns.std() * np.sqrt(252) * 100)
        metrics["Raw_Portfolio_MaxDD_%"] = float(((cumulative - cumulative.cummax()) / cumulative.cummax()).min() * 100)
    else:
        metrics["Raw_Portfolio_Volatility_%"] = np.nan
        metrics["Raw_Portfolio_MaxDD_%"] = np.nan

    sector_matrix, _ = _get_sector_matrix_cached(tickers)
    if sector_matrix is not None:
        sector_exposures = np.dot(w, sector_matrix)
        metrics["Raw_Sector_HHI"] = float(np.sum(sector_exposures**2))
    else:
        metrics["Raw_Sector_HHI"] = np.nan

    return metrics


def calculate_portfolio_utility(
    weights: pd.Series,
    scaled_df: pd.DataFrame,
    returns_matrix: pd.DataFrame,
    global_weights: dict[str, float],
    config: BacktestConfig,
    benchmark_returns: pd.Series | None = None,
    maxdd_bounds: tuple[float, float] | None = None,
) -> dict[str, float]:
    """
    用 functions.py Stage 3 的 calc_utility 同一套邏輯計算投組偏好效用。
    回傳總分與各構面分數，方便檢查系統是否在每個偏好面向都更符合使用者需求。

    `maxdd_bounds`：抗跌(MaxDD)分數的「尺度上下界」。預設 None＝沿用「本投組自身持有標的」
    的 MaxDD 分布建尺度；但這對**單一標的基準（如 VT）會退化**（上界=下界 → 不論實際回撤多大都得滿分 1.0）。
    因此 V-6 比較評分時，呼叫端應傳入「同一個跨截面（評估universe全體）」的共同尺度，讓各策略
    （含 VT）站在同一把尺上比較。此參數只影響評分尺度，不影響各投組『自身』實際回撤的計算。
    """
    if weights.empty or scaled_df.empty or returns_matrix.empty:
        return {}

    tickers = [ticker for ticker in weights.index if ticker in scaled_df["ETF"].values and ticker in returns_matrix.columns]
    if not tickers:
        return {}

    clean_weights = weights[tickers].astype(float)
    clean_weights = clean_weights[clean_weights > 0]
    if clean_weights.empty:
        return {}
    clean_weights = clean_weights / clean_weights.sum()

    tickers = clean_weights.index.tolist()
    scaled = scaled_df.set_index("ETF").loc[tickers]
    returns = returns_matrix[tickers].dropna(how="any")
    if returns.empty:
        return {}

    blended = _blended_preference_weights(global_weights)
    cov_matrix = returns.cov().values * 252
    returns_values_for_true_mdd = np.nan_to_num(returns.values, nan=0.0)
    # 抗跌分數尺度：優先用呼叫端提供的「共同跨截面尺度」（避免單一標的基準退化得滿分）；
    # 未提供時才退回「本投組自身持有標的」的尺度（沿用舊行為）。
    if maxdd_bounds is not None:
        true_mdd_lower_bound, true_mdd_upper_bound = maxdd_bounds
    else:
        true_mdd_lower_bound, true_mdd_upper_bound = calculate_individual_maxdd_bounds(returns)
    w = clean_weights.values

    # 報酬維度評分基礎：cagr（過去 CAGR 排名，現況）或 beta（系統性風險曝險，會持續）。
    # beta 版：報酬分數 = clip(beta_vs_anchor / PREF_BETA_REF, 0, 1)；VT(beta=1)→0.5，高 beta 投組更高。
    score_return_cagr = float(np.dot(w, scaled["Norm_Return_CAGR"].values))
    if str(getattr(parameters, "PREF_RETURN_BASIS", "cagr")).lower() == "beta" and benchmark_returns is not None:
        c_vec, var_b = compute_benchmark_cov_vector(returns, benchmark_returns)
        if c_vec is not None and var_b and var_b > 0:
            beta_vec = c_vec / var_b
            ref = float(getattr(parameters, "PREF_BETA_REF", 2.0))
            # 市場(beta=1)=0.5 基準；高於市場才加分，低於市場不懲罰(floor 0.5)；beta=ref→1.0。
            beta_score = 0.5 + 0.5 * np.clip((beta_vec - 1.0) / max(ref - 1.0, 1e-9), 0.0, 1.0)
            score_return_cagr = float(np.dot(w, beta_score))
    score_return_div = float(np.dot(w, scaled["Norm_Return_Div"].values))
    proxy_risk_maxdd = float(np.dot(w, scaled["Norm_Risk_MaxDD"].values))
    true_risk_maxdd = (
        calculate_true_maxdd_score(w, returns_values_for_true_mdd, true_mdd_lower_bound, true_mdd_upper_bound)
        if USE_TRUE_MDD_OPTIMIZATION
        else None
    )
    score_risk_maxdd = proxy_risk_maxdd if true_risk_maxdd is None else float(true_risk_maxdd)
    score_cost = float(np.dot(w, scaled["Norm_Cost_ExpRatio"].values))
    score_liq_volume = float(np.dot(w, scaled["Norm_Liq_Volume"].values))
    score_liq_aum = float(np.dot(w, scaled["Norm_Liq_AUM"].values))
    score_sentiment = float(np.dot(w, scaled["Norm_FinBERT"].values))
    score_diversification = float(np.dot(w, scaled["Norm_Div_Score"].values))

    sector_matrix, _ = _get_sector_matrix_cached(tickers)
    if parameters.USE_TRUE_HHI_OPTIMIZATION and sector_matrix is not None:
        sector_exposures = np.dot(w, sector_matrix)
        score_diversification = float(1.0 - np.sum(sector_exposures**2))

    portfolio_vol = float(np.sqrt(np.dot(w.T, np.dot(cov_matrix, w))))
    score_risk_vol = float(
        1.0
        - np.clip(
            (portfolio_vol - VOL_SCORE_FLOOR) / (VOL_SCORE_CAP - VOL_SCORE_FLOOR),
            0.0,
            1.0,
        )
    )

    total_score = (
        blended["Return_CAGR"] * score_return_cagr
        + blended["Return_Div"] * score_return_div
        + blended["Risk_Vol"] * score_risk_vol
        + blended["Risk_MaxDD"] * score_risk_maxdd
        + blended["Cost_ExpRatio"] * score_cost
        + blended["Liq_Volume"] * score_liq_volume
        + blended["Liq_AUM"] * score_liq_aum
        + blended["Div_Score"] * score_diversification
        + blended["FinBERT_score"] * score_sentiment
    )

    return {
        "Preference_Score": float(total_score),
        "Score_Return_CAGR": score_return_cagr,
        "Score_Return_Div": score_return_div,
        "Score_Risk_Vol": score_risk_vol,
        "Score_Risk_MaxDD": score_risk_maxdd,
        "Score_Cost": score_cost,
        "Score_Liq_Volume": score_liq_volume,
        "Score_Liq_AUM": score_liq_aum,
        "Score_Div_Score": score_diversification,
        "Score_FinBERT": score_sentiment,
        "Portfolio_Volatility": portfolio_vol,
    }


def build_period_dimension_row(
    strategy: str,
    rebalance_date: pd.Timestamp,
    evaluation_date: pd.Timestamp,
    weights: pd.Series,
    period_returns: pd.Series,
    evaluation_feature_df: pd.DataFrame,
    evaluation_scaled: pd.DataFrame,
    evaluation_returns: pd.DataFrame,
    global_weights: dict[str, float],
    config: BacktestConfig,
) -> dict[str, float]:
    """整理單一策略在單一持有期間的偏好維度與未來評價分數。"""
    # 抗跌分數同樣用「評估截面共同尺度」，避免單一標的基準（VT）退化得滿分。
    _dim_maxdd_bounds = calculate_individual_maxdd_bounds(evaluation_returns)
    utility = calculate_portfolio_utility(
        weights, evaluation_scaled, evaluation_returns, global_weights, config,
        maxdd_bounds=_dim_maxdd_bounds,
    )
    raw_metrics = calculate_raw_dimension_metrics(weights, evaluation_feature_df, evaluation_returns)
    return {
        "Strategy": strategy,
        "Rebalance_Date": rebalance_date.strftime("%Y-%m-%d"),
        "Evaluation_Date": evaluation_date.strftime("%Y-%m-%d"),
        "Forward_Period_Return": (1.0 + period_returns).prod() - 1.0 if not period_returns.empty else np.nan,
        **utility,
        **raw_metrics,
    }


def build_aggregate_dimension_comparison(
    period_dimension_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """將逐期維度比較彙總成整段回測期間的策略/benchmark 比較表。"""
    if period_dimension_df.empty:
        return pd.DataFrame()

    metric_cols = [
        col
        for col in period_dimension_df.columns
        if col not in {"Strategy", "Rebalance_Date", "Evaluation_Date"}
    ]
    aggregate = period_dimension_df.groupby("Strategy")[metric_cols].mean(numeric_only=True).reset_index()
    aggregate = aggregate.rename(
        columns={
            "Forward_Period_Return": "Avg_Period_Return",
            "Preference_Score": "Avg_Preference_Score",
            "Score_Return_CAGR": "Avg_Score_Return_CAGR",
            "Score_Return_Div": "Avg_Score_Return_Div",
            "Score_Risk_Vol": "Avg_Score_Risk_Vol",
            "Score_Risk_MaxDD": "Avg_Score_Risk_MaxDD",
            "Score_Cost": "Avg_Score_Cost",
            "Score_Liq_Volume": "Avg_Score_Liq_Volume",
            "Score_Liq_AUM": "Avg_Score_Liq_AUM",
            "Score_Div_Score": "Avg_Score_Div_Score",
            "Score_FinBERT": "Avg_Score_FinBERT",
            "Portfolio_Volatility": "Avg_Utility_Portfolio_Volatility",
            "Raw_Return_CAGR_%": "Avg_Raw_Return_CAGR_%",
            "Raw_Dividend_Yield_%": "Avg_Raw_Dividend_Yield_%",
            "Raw_Expense_Ratio_%": "Avg_Raw_Expense_Ratio_%",
            "Raw_Liquidity_Volume_M": "Avg_Raw_Liquidity_Volume_M",
            "Raw_Liquidity_AUM_B": "Avg_Raw_Liquidity_AUM_B",
            "Raw_FinBERT_Score": "Avg_Raw_FinBERT_Score",
            "Raw_Portfolio_Volatility_%": "Avg_Raw_Portfolio_Volatility_%",
            "Raw_Portfolio_MaxDD_%": "Avg_Raw_Portfolio_MaxDD_%",
            "Raw_Sector_HHI": "Avg_Raw_Sector_HHI",
        }
    )

    if not summary_df.empty:
        aggregate = aggregate.merge(summary_df, on="Strategy", how="left")

    aggregate["Return_Uses_Adjusted_Close"] = not Path(config.close_price_cache_file).exists()
    aggregate["Dividend_Included_In_Total_Return_Note"] = (
        "Total performance separates capital gains and estimated cash dividends. "
        "If close-price cache is missing, capital gains may still fall back to adjusted-price data."
    )
    aggregate["Periodic_Contribution"] = config.periodic_contribution
    return aggregate.sort_values("Avg_Preference_Score", ascending=False).reset_index(drop=True)


def optimize_max_sharpe_portfolio(
    selected_df: pd.DataFrame,
    returns_matrix: pd.DataFrame,
    config: BacktestConfig,
) -> pd.Series:
    """建立同一候選池下的傳統 Max Sharpe 對照組。"""
    if selected_df.empty or "ETF" not in selected_df.columns:
        return pd.Series(dtype=float)

    tickers = [ticker for ticker in selected_df["ETF"] if ticker in returns_matrix.columns]
    if len(tickers) < int(np.ceil(1.0 / config.max_weight_limit)):
        return pd.Series(dtype=float)

    returns = returns_matrix[tickers].dropna(how="any")
    if returns.empty:
        return pd.Series(dtype=float)

    # Max Sharpe 期望報酬改用算術平均年化（Sharpe 比率定義所需），與主系統口徑一致。
    annual_returns = (returns.mean() * 252).values
    cov_matrix = compute_cov_annual(returns)
    n_assets = len(tickers)
    initial = np.array([1.0 / n_assets] * n_assets)
    bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

    def neg_sharpe(w: np.ndarray) -> float:
        p_ret = np.dot(w, annual_returns)
        p_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))
        return -((p_ret - config.risk_free_rate) / p_vol) if p_vol > 0 else 0

    result = minimize(
        neg_sharpe,
        initial,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-9},
    )
    if not result.success:
        return pd.Series(dtype=float)
    return pd.Series(np.round(result.x, 6), index=tickers)


def optimize_preference_portfolio(
    selected_df: pd.DataFrame,
    scaled_df: pd.DataFrame,
    returns_matrix: pd.DataFrame,
    global_weights: dict[str, float],
    config: BacktestConfig,
    benchmark_returns: pd.Series | None = None,
) -> pd.Series:
    if selected_df.empty or scaled_df.empty or "ETF" not in selected_df.columns or "ETF" not in scaled_df.columns:
        return pd.Series(dtype=float)

    tickers = [ticker for ticker in selected_df["ETF"] if ticker in returns_matrix.columns]
    if len(tickers) < int(np.ceil(1.0 / config.max_weight_limit)):
        return pd.Series(dtype=float)

    returns = returns_matrix[tickers].dropna(how="any")
    if returns.empty:
        return pd.Series(dtype=float)

    selected = selected_df.set_index("ETF").loc[tickers].reset_index()
    scaled = scaled_df.set_index("ETF").loc[tickers].reset_index()
    sector_matrix, _ = _get_sector_matrix_cached(tickers)
    cov_matrix = compute_cov_annual(returns)
    returns_values_for_true_mdd = np.nan_to_num(returns.values, nan=0.0)
    true_mdd_lower_bound, true_mdd_upper_bound = calculate_individual_maxdd_bounds(returns)

    if str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper() == "B":
        # Arm B（U-1 + U-2）：與主系統 functions.py 完全相同的邏輯——
        # 真實期望報酬（資本利得算術年化 + 殖利率）+ 風險預算約束。
        cap_gain_arith = returns.mean().values * 252.0
        cap_gain_arith = shrink_mean_returns(cap_gain_arith)  # 收縮資本利得樣本平均，降低均值估計雜訊
        div_yield_vec = pd.to_numeric(selected["Return_Div (%)"], errors="coerce").fillna(0.0).values / 100.0
        # 殖利率依使用者報酬子維度偏好比例加權（Return_Div / Return_CAGR），與主系統一致。
        div_pref_ratio = global_weights.get("Return_Div", 0.0) / max(global_weights.get("Return_CAGR", 0.0), 1e-6)
        mu_total = cap_gain_arith + div_pref_ratio * div_yield_vec
        lam = float(getattr(parameters, "RISK_AVERSION_LAMBDA", 2.0))
        vol_budget = float(getattr(parameters, "RISK_BUDGET_VOL", 0.30))
        n_assets = len(tickers)
        initial = np.array([1.0 / n_assets] * n_assets)
        bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))

        def neg_mean_variance(w: np.ndarray) -> float:
            port_ret = np.dot(w, mu_total)
            port_var = np.dot(w.T, np.dot(cov_matrix, w))
            return -(port_ret - 0.5 * lam * port_var)

        cons_sum = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        cons_budget = {"type": "ineq", "fun": lambda w: vol_budget - np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))}
        result = minimize(neg_mean_variance, initial, method="SLSQP", bounds=bounds, constraints=[cons_sum, cons_budget], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_mean_variance, initial, method="SLSQP", bounds=bounds, constraints=[cons_sum], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            return pd.Series(dtype=float)
        return pd.Series(np.round(result.x, 6), index=tickers)

    if str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper() == "C":
        # Arm C：與主系統 functions.py 完全相同——最小變異核心 + 排名式偏好傾斜 + 品質約束。
        tau = float(getattr(parameters, "TILT_STRENGTH", 0.1))
        s_full = pd.to_numeric(selected["User_Pref_Score"], errors="coerce").fillna(0.0).values
        if getattr(parameters, "TILT_INCLUDE_CAGR", True):
            s_tilt = s_full
        else:
            s_tilt = s_full - float(global_weights.get("Return_CAGR", 0.0)) * scaled["Norm_Return_CAGR"].values
        vol_budget = float(getattr(parameters, "RISK_BUDGET_VOL", 0.30))
        n_assets = len(tickers)
        initial = np.array([1.0 / n_assets] * n_assets)
        bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))

        def neg_tilt_minvar(w: np.ndarray) -> float:
            return 0.5 * np.dot(w.T, np.dot(cov_matrix, w)) - tau * np.dot(w, s_tilt)

        cons = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "ineq", "fun": lambda w: vol_budget - np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))},
        ]
        cons += build_quality_constraints(
            global_weights, config.max_weight_limit,
            cost_vec=pd.to_numeric(selected["Cost_ExpRatio (%)"], errors="coerce").fillna(0.0).values,
            sector_matrix=sector_matrix,
            norm_liq_vol=scaled["Norm_Liq_Volume"].values, norm_liq_aum=scaled["Norm_Liq_AUM"].values,
            sent_vec=scaled["Norm_FinBERT"].values)
        result = minimize(neg_tilt_minvar, initial, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_tilt_minvar, initial, method="SLSQP", bounds=bounds, constraints=cons[:2], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_tilt_minvar, initial, method="SLSQP", bounds=bounds, constraints=[cons[0]], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            return pd.Series(dtype=float)
        return pd.Series(np.round(result.x, 6), index=tickers)

    if str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper() == "C2":
        # Arm C2（U-C2）：profile-dependent 核心，與主系統 functions.py 完全相同邏輯。
        # g(w) 依偏好權重決定 核心類型/風險預算/τ；三核心只需每日報酬（Σ 與 c）。
        gp = derive_params_from_weights(global_weights)
        core_mode = gp["core_mode"]
        tau = float(gp["tau"])
        # 風險預算改用「相對候選池可行波動範圍」（與主系統 functions.py 完全相同）。
        vb_budget, _v_min, _v_max = compute_feasible_vol_budget(cov_matrix, config.max_weight_limit, gp["risk_fraction"])
        vol_budget = vb_budget if vb_budget is not None else float(gp["vol_budget"])
        s_full = pd.to_numeric(selected["User_Pref_Score"], errors="coerce").fillna(0.0).values
        if getattr(parameters, "TILT_INCLUDE_CAGR", True):
            s_tilt = s_full
        else:
            s_tilt = s_full - float(global_weights.get("Return_CAGR", 0.0)) * scaled["Norm_Return_CAGR"].values
        c_vec, var_bench = (None, None)
        if core_mode in ("market", "beta"):
            c_vec, var_bench = compute_benchmark_cov_vector(returns, benchmark_returns)
            if c_vec is None:
                core_mode = "minvar"  # 取不到基準共變異 → 退回 minvar（與主系統一致）

        n_assets = len(tickers)
        initial = np.array([1.0 / n_assets] * n_assets)
        bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))

        if core_mode == "beta":
            beta_vec = (c_vec / var_bench) if (var_bench and var_bench > 0) else c_vec

            def neg_c2(w: np.ndarray, b=beta_vec, st=s_tilt, t=tau) -> float:
                return -(np.dot(w, b) + t * np.dot(w, st))
        elif core_mode == "market":
            def neg_c2(w: np.ndarray, cc=c_vec, st=s_tilt, t=tau) -> float:
                return 0.5 * np.dot(w.T, np.dot(cov_matrix, w)) - np.dot(w, cc) - t * np.dot(w, st)
        else:  # minvar
            def neg_c2(w: np.ndarray, st=s_tilt, t=tau) -> float:
                return 0.5 * np.dot(w.T, np.dot(cov_matrix, w)) - t * np.dot(w, st)

        cons = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "ineq", "fun": lambda w: vol_budget - np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))},
        ]
        cons += build_quality_constraints(
            global_weights, config.max_weight_limit,
            cost_vec=pd.to_numeric(selected["Cost_ExpRatio (%)"], errors="coerce").fillna(0.0).values,
            sector_matrix=sector_matrix,
            norm_liq_vol=scaled["Norm_Liq_Volume"].values, norm_liq_aum=scaled["Norm_Liq_AUM"].values,
            sent_vec=scaled["Norm_FinBERT"].values)
        result = minimize(neg_c2, initial, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_c2, initial, method="SLSQP", bounds=bounds, constraints=cons[:2], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_c2, initial, method="SLSQP", bounds=bounds, constraints=[cons[0]], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            return pd.Series(dtype=float)
        return pd.Series(np.round(result.x, 6), index=tickers)

    if str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper() == "BL":
        # Black-Litterman 路(a) 統一目標（與主系統 functions.py 完全相同）：max wᵀΠ + τ·wᵀs s.t. vol≤budget。
        gp = derive_params_from_weights(global_weights)
        tau = float(gp["tau"])
        s_full = pd.to_numeric(selected["User_Pref_Score"], errors="coerce").fillna(0.0).values
        if getattr(parameters, "TILT_INCLUDE_CAGR", True):
            s_tilt = s_full
        else:
            s_tilt = s_full - float(global_weights.get("Return_CAGR", 0.0)) * scaled["Norm_Return_CAGR"].values
        c_vec, var_bench = compute_benchmark_cov_vector(returns, benchmark_returns)
        vb_budget, _vm, _vx = compute_feasible_vol_budget(cov_matrix, config.max_weight_limit, gp["risk_fraction"])
        vol_budget = vb_budget if vb_budget is not None else float(gp["vol_budget"])
        n_assets = len(tickers)
        initial = np.array([1.0 / n_assets] * n_assets)
        bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))
        if c_vec is not None and var_bench and var_bench > 0:
            pi_vec = c_vec / var_bench
            def neg_bl(w, b=pi_vec, st=s_tilt, t=tau):
                return -(np.dot(w, b) + t * np.dot(w, st))
        else:
            def neg_bl(w, st=s_tilt, t=tau):
                return 0.5 * np.dot(w.T, np.dot(cov_matrix, w)) - t * np.dot(w, st)
        cons = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "ineq", "fun": lambda w: vol_budget - np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))},
        ]
        cons += build_quality_constraints(
            global_weights, config.max_weight_limit,
            cost_vec=pd.to_numeric(selected["Cost_ExpRatio (%)"], errors="coerce").fillna(0.0).values,
            sector_matrix=sector_matrix,
            norm_liq_vol=scaled["Norm_Liq_Volume"].values, norm_liq_aum=scaled["Norm_Liq_AUM"].values,
            sent_vec=scaled["Norm_FinBERT"].values)
        result = minimize(neg_bl, initial, method="SLSQP", bounds=bounds, constraints=cons, options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_bl, initial, method="SLSQP", bounds=bounds, constraints=cons[:2], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            result = minimize(neg_bl, initial, method="SLSQP", bounds=bounds, constraints=[cons[0]], options={"maxiter": 1000, "ftol": 1e-9})
        if not result.success:
            return pd.Series(dtype=float)
        return pd.Series(np.round(result.x, 6), index=tickers)

    blended = {}
    for key in parameters.BASELINE_WEIGHTS:
        blended[key] = (
            parameters.ALPHA_BASELINE * parameters.BASELINE_WEIGHTS[key]
            + (1 - parameters.ALPHA_BASELINE) * global_weights.get(key, 0.0)
        )

    vecs = {
        "Return_CAGR": scaled["Norm_Return_CAGR"].values,
        "Return_Div": scaled["Norm_Return_Div"].values,
        "Risk_MaxDD": scaled["Norm_Risk_MaxDD"].values,
        "Cost_ExpRatio": scaled["Norm_Cost_ExpRatio"].values,
        "Liq_Volume": scaled["Norm_Liq_Volume"].values,
        "Liq_AUM": scaled["Norm_Liq_AUM"].values,
        "Div_Score": scaled["Norm_Div_Score"].values,
        "FinBERT_score": scaled["Norm_FinBERT"].values,
    }

    def calc_utility(weights: np.ndarray) -> float:
        port_div_score = np.dot(weights, vecs["Div_Score"])
        if parameters.USE_TRUE_HHI_OPTIMIZATION and sector_matrix is not None:
            port_sector_exposures = np.dot(weights, sector_matrix)
            port_div_score = 1.0 - np.sum(port_sector_exposures**2)

        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        vol_score = 1.0 - np.clip(
            (port_vol - VOL_SCORE_FLOOR) / (VOL_SCORE_CAP - VOL_SCORE_FLOOR),
            0.0,
            1.0,
        )
        proxy_maxdd = np.dot(weights, vecs["Risk_MaxDD"])
        true_maxdd_score = (
            calculate_true_maxdd_score(weights, returns_values_for_true_mdd, true_mdd_lower_bound, true_mdd_upper_bound)
            if USE_TRUE_MDD_OPTIMIZATION
            else None
        )
        # 舊版 MaxDD proxy 保留為 fallback；如果真實 MaxDD 計算失效或未來要測速，可直接切回。
        maxdd_score = proxy_maxdd if true_maxdd_score is None else true_maxdd_score

        return (
            blended["Return_CAGR"] * np.dot(weights, vecs["Return_CAGR"])
            + blended["Return_Div"] * np.dot(weights, vecs["Return_Div"])
            + blended["Risk_Vol"] * vol_score
            + blended["Risk_MaxDD"] * maxdd_score
            + blended["Cost_ExpRatio"] * np.dot(weights, vecs["Cost_ExpRatio"])
            + blended["Liq_Volume"] * np.dot(weights, vecs["Liq_Volume"])
            + blended["Liq_AUM"] * np.dot(weights, vecs["Liq_AUM"])
            + blended["Div_Score"] * port_div_score
            + blended["FinBERT_score"] * np.dot(weights, vecs["FinBERT_score"])
        )

    n_assets = len(tickers)
    initial = np.array([1.0 / n_assets] * n_assets)
    bounds = tuple((0.0, config.max_weight_limit) for _ in range(n_assets))
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    optimization_start_time = time.perf_counter()
    result = minimize(
        lambda w: -calc_utility(w),
        initial,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-9},
    )
    optimization_elapsed = time.perf_counter() - optimization_start_time
    if USE_TRUE_MDD_OPTIMIZATION and optimization_elapsed > TRUE_MDD_TIME_WARNING_SECONDS:
        warnings.warn(
            f"True MaxDD backtest optimization took {optimization_elapsed:.1f}s, "
            f"above {TRUE_MDD_TIME_WARNING_SECONDS:.0f}s. Consider switching back to the old MaxDD proxy.",
            RuntimeWarning,
        )
    if not result.success:
        return pd.Series(dtype=float)

    return pd.Series(np.round(result.x, 6), index=tickers)


def _performance_summary(nav: pd.Series, returns: pd.Series, cashflows: pd.Series | None = None) -> dict[str, float]:
    if nav.empty or returns.empty:
        return {}
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cumulative_return = (1.0 + returns).prod() - 1.0
    cagr = (1.0 + cumulative_return) ** (1.0 / years) - 1.0 if years > 0 else np.nan
    arithmetic_annual_return = returns.mean() * 252
    volatility = returns.std() * np.sqrt(252)
    # Sharpe 用算術平均年化報酬（定義所需）；報表同時保留幾何 CAGR 與算術年化報酬兩個口徑。
    sharpe = (arithmetic_annual_return - 0.04) / volatility if volatility > 0 else np.nan
    time_weighted_nav = (1.0 + returns).cumprod()
    drawdown = time_weighted_nav / time_weighted_nav.cummax() - 1.0
    summary = {
        "Cumulative_Return_%": cumulative_return * 100,
        "CAGR_%": cagr * 100,
        "Arithmetic_Annual_Return_%": arithmetic_annual_return * 100,
        "Annualized_Volatility_%": volatility * 100,
        "Sharpe": sharpe,
        "Max_Drawdown_%": drawdown.min() * 100,
    }
    if cashflows is not None and not cashflows.empty:
        total_contributed = cashflows.sum()
        ending_value = nav.iloc[-1]
        net_profit = ending_value - total_contributed
        summary.update(
            {
                "Total_Contributed": total_contributed,
                "Ending_Value": ending_value,
                "Net_Profit": net_profit,
                "Profit_on_Contributed_%": (net_profit / total_contributed * 100) if total_contributed > 0 else np.nan,
            }
        )
    return summary


def _income_split_summary(
    price_nav: pd.Series,
    dividend_cash: pd.Series,
    total_wealth: pd.Series,
    cashflows: pd.Series,
) -> dict[str, float]:
    """補充資本利得、股息現金與總財富拆分，讓績效來源保持可解釋。"""
    if price_nav.empty or total_wealth.empty or cashflows.empty:
        return {}

    total_contributed = cashflows.sum()
    if total_contributed <= 0:
        return {}

    ending_price_value = price_nav.iloc[-1]
    ending_dividend_cash = dividend_cash.iloc[-1] if not dividend_cash.empty else 0.0
    ending_total_wealth = total_wealth.iloc[-1]
    capital_gain_profit = ending_price_value - total_contributed
    dividend_income_profit = ending_dividend_cash
    return {
        "Capital_Gain_Ending_Value": ending_price_value,
        "Dividend_Cash": ending_dividend_cash,
        "Total_Wealth": ending_total_wealth,
        "Capital_Gain_Return_%": capital_gain_profit / total_contributed * 100,
        "Dividend_Income_Return_%": dividend_income_profit / total_contributed * 100,
        "Total_Wealth_Return_%": (ending_total_wealth - total_contributed) / total_contributed * 100,
    }


def _plot_backtest_outputs(nav: pd.DataFrame, output_prefix: str, output_dir: Path | str = "png", title_prefix: str = "") -> None:
    sns.set_theme(style="whitegrid")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(11, 6))
    for col in nav.columns:
        plt.plot(nav.index, nav[col], label=col, linewidth=2)
    plt.title(f"{title_prefix}Rolling Robo-Advisor Backtest NAV")
    plt.ylabel("Net Asset Value")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / f"{output_prefix}_nav.png", dpi=300)
    plt.close()

    drawdown = nav / nav.cummax() - 1.0
    plt.figure(figsize=(11, 5))
    for col in drawdown.columns:
        plt.plot(drawdown.index, drawdown[col] * 100, label=col, linewidth=2)
    plt.title(f"{title_prefix}Rolling Robo-Advisor Backtest Drawdown")
    plt.ylabel("Drawdown (%)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / f"{output_prefix}_drawdown.png", dpi=300)
    plt.close()


def _calc_turnover(weights_df: pd.DataFrame) -> pd.DataFrame:
    if weights_df.empty:
        return pd.DataFrame(columns=["Rebalance_Date", "Turnover"])

    pivot = weights_df.pivot_table(
        index="Rebalance_Date",
        columns="ETF",
        values="Weight",
        aggfunc="sum",
        fill_value=0.0,
    ).sort_index()
    turnover = pivot.diff().abs().sum(axis=1) / 2.0
    turnover.iloc[0] = np.nan
    return turnover.rename("Turnover").reset_index()


def _annual_return_table(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return pd.DataFrame()
    annual = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    annual.index.name = "Year"
    return annual.reset_index()


def _plot_backtest_performance_report(nav: pd.DataFrame, output_path: Path, title_prefix: str = "") -> None:
    if nav.empty:
        return

    sns.set_theme(style="whitegrid")
    drawdown = nav / nav.cummax() - 1.0
    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(12, 8),
        gridspec_kw={"height_ratios": [3, 1]},
        sharex=True,
    )

    for col in nav.columns:
        ax1.plot(nav.index, nav[col], label=col, linewidth=2)
        ax2.plot(drawdown.index, drawdown[col] * 100, label=col, linewidth=1.5)

    ax1.set_title(f"{title_prefix}Backtest Portfolio Performance")
    ax1.set_ylabel("Net Asset Value")
    ax1.legend()
    ax2.set_title("Drawdown")
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_annual_returns(annual_returns: pd.DataFrame, output_path: Path, title_prefix: str = "") -> None:
    if annual_returns.empty:
        return

    plot_df = annual_returns.set_index("Year") * 100
    ax = plot_df.plot(kind="bar", figsize=(11, 6), width=0.8)
    ax.set_title(f"{title_prefix}Backtest Annual Returns")
    ax.set_ylabel("Annual Return (%)")
    ax.axhline(0, color="black", linewidth=1)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_weight_evolution(weights_df: pd.DataFrame, output_path: Path, top_n: int = 10, title_prefix: str = "") -> None:
    if weights_df.empty:
        return

    pivot = weights_df.pivot_table(
        index="Rebalance_Date",
        columns="ETF",
        values="Weight",
        aggfunc="sum",
        fill_value=0.0,
    ).sort_index()
    top_cols = pivot.mean().sort_values(ascending=False).head(top_n).index.tolist()
    plot_df = pivot[top_cols].copy()
    other = pivot.drop(columns=top_cols, errors="ignore").sum(axis=1)
    if (other > 1e-8).any():
        plot_df["Other"] = other

    ax = plot_df.plot(kind="area", stacked=True, figsize=(12, 6), linewidth=0)
    ax.set_title(f"{title_prefix}Backtest Weight Evolution")
    ax.set_ylabel("Portfolio Weight")
    ax.set_ylim(0, 1)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_distribution_grid(
    df: pd.DataFrame,
    columns: list[str],
    output_path: Path,
    title: str,
    kind: Literal["hist", "box"],
) -> None:
    valid_cols = [col for col in columns if col in df.columns]
    if not valid_cols:
        return

    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Arial Unicode MS", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False
    n_cols = 3
    n_rows = int(np.ceil(len(valid_cols) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, max(4, n_rows * 3.5)))
    axes = np.array(axes).reshape(-1)

    for idx, col in enumerate(valid_cols):
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if kind == "hist":
            sns.histplot(series, kde=True, ax=axes[idx], color="steelblue", bins=30)
        else:
            sns.boxplot(x=series, ax=axes[idx], color="lightcoral")
        axes[idx].set_title(col)

    for idx in range(len(valid_cols), len(axes)):
        axes[idx].axis("off")

    fig.suptitle(title, fontsize=16, fontweight="bold")
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_dea_distribution_backtest(dea_results: pd.DataFrame, output_path: Path, title_prefix: str = "") -> None:
    if dea_results.empty or "DEA_Score" not in dea_results.columns:
        return

    plt.figure(figsize=(10, 6))
    sns.histplot(dea_results["DEA_Score"], bins=20, kde=True, color="steelblue", edgecolor="black")
    top_frac = getattr(parameters, "DEA_TOP_FRACTION", 0.25)
    cutoff = float(dea_results["DEA_Score"].quantile(1.0 - top_frac))
    plt.axvline(cutoff, color="red", linestyle="--", linewidth=2, label=f"Top {top_frac*100:.0f}% cutoff = {cutoff:.3f}")
    plt.title(f"{title_prefix}Backtest Final Rebalance DEA Score Distribution")
    plt.xlabel("DEA Score")
    plt.ylabel("ETF Count")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_backtest_metrics_comparison(summary_df: pd.DataFrame, dimension_df: "pd.DataFrame | None",
                                      output_path: Path, title_prefix: str = "") -> None:
    """把回測關鍵數據畫成「各策略 vs VT」對照圖（取代看 CSV）：
    累積總報酬(資本利得+股息堆疊，括號標年化 CAGR) / 平均費用率 / 平均殖利率 / 年化波動 / 夏普 / 最大回撤。
    偏好組合(紅)、VT(藍)highlight，其餘對照組(灰)；股息以金色堆疊，讓收入型偏好是否被滿足一眼可見。
    """
    if summary_df is None or summary_df.empty or "Strategy" not in summary_df.columns:
        return
    sns.set_theme(style="whitegrid")
    plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Arial Unicode MS", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    df = summary_df.copy().drop_duplicates(subset="Strategy").set_index("Strategy")
    order = [s for s in ["Preference_Driven", "VT", "VOO", "EqualWeight", "MaxSharpe"] if s in df.index]
    if not order:
        return
    label = {"Preference_Driven": "偏好組合", "VT": "VT", "VOO": "VOO",
             "EqualWeight": "等權", "MaxSharpe": "MaxSharpe"}
    color = {"Preference_Driven": "#DC2626", "VT": "#2563EB"}
    xs = list(range(len(order)))
    xt = [label.get(s, s) for s in order]

    # 維度層級指標（平均殖利率 / 平均費用率）取自 dimension comparison
    dim_src = None
    if dimension_df is not None and not getattr(dimension_df, "empty", True):
        dd = dimension_df.copy()
        if "Strategy" not in dd.columns and dd.index.name == "Strategy":
            dd = dd.reset_index()
        if "Strategy" in dd.columns:
            dim_src = dd.drop_duplicates(subset="Strategy").set_index("Strategy")

    def _num(src, s, col):
        try:
            return float(pd.to_numeric(src.loc[s, col], errors="coerce"))
        except Exception:
            return float("nan")

    def simple_bar(ax, col, title, src=None):
        src = df if src is None else src
        vals = [_num(src, s, col) for s in order]
        bars = ax.bar(xs, vals, color=[color.get(s, "#CBD5E1") for s in order],
                      edgecolor="black", linewidth=0.6)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xticks(xs); ax.set_xticklabels(xt, rotation=18, fontsize=9)
        ax.axhline(0, color="black", linewidth=0.8)
        for b, v in zip(bars, vals):
            if v == v:
                ax.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v),
                            ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5, fontweight="bold")
        ax.margins(y=0.20)

    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    axes = np.array(axes).reshape(-1)

    # (1) 累積總報酬 = 資本利得 + 股息（堆疊，金色為股息）
    ax = axes[0]
    if {"Capital_Gain_Return_%", "Dividend_Income_Return_%"}.issubset(df.columns):
        cg = [_num(df, s, "Capital_Gain_Return_%") for s in order]
        dv = [_num(df, s, "Dividend_Income_Return_%") for s in order]
        ax.bar(xs, cg, color="#94A3B8", edgecolor="black", linewidth=0.6, label="資本利得")
        ax.bar(xs, dv, bottom=cg, color="#F59E0B", edgecolor="black", linewidth=0.6, label="股息(現金)")
        for i in xs:
            tot = cg[i] + dv[i]
            cagr_i = _num(df, order[i], "CAGR_%")
            lbl = f"{tot:.0f}" + (f"\n(年化{cagr_i:.1f}%)" if cagr_i == cagr_i else "")
            ax.annotate(lbl, (i, tot), ha="center", va="bottom", fontsize=8.5, fontweight="bold")
            if dv[i] > 4:
                ax.annotate(f"息{dv[i]:.0f}", (i, cg[i] + dv[i] / 2), ha="center", va="center", fontsize=8)
        ax.set_title("累積總報酬 %（資本利得＋股息；括號為年化 CAGR）", fontsize=13, fontweight="bold")
        ax.set_xticks(xs); ax.set_xticklabels(xt, rotation=18, fontsize=9)
        ax.legend(fontsize=8, loc="upper right"); ax.margins(y=0.22)
    else:
        simple_bar(ax, "Cumulative_Return_%", "累積總報酬 %（含息）")

    # (2) 平均費用率（取代原 CAGR 欄；CAGR 已併入累積總報酬長條的括號標籤）
    if dim_src is not None and "Avg_Raw_Expense_Ratio_%" in dim_src.columns:
        simple_bar(axes[1], "Avg_Raw_Expense_Ratio_%", "平均費用率 %（每期加權，越低越好）", src=dim_src)
    else:
        axes[1].axis("off")
    # (3) 平均殖利率
    if dim_src is not None and "Avg_Raw_Dividend_Yield_%" in dim_src.columns:
        simple_bar(axes[2], "Avg_Raw_Dividend_Yield_%", "平均殖利率 %（每期加權）", src=dim_src)
    else:
        simple_bar(axes[2], "Dividend_Income_Return_%", "累積股息報酬 %")
    simple_bar(axes[3], "Annualized_Volatility_%", "年化波動率 %")
    simple_bar(axes[4], "Sharpe", "夏普值 (Sharpe)")
    simple_bar(axes[5], "Max_Drawdown_%", "最大回撤 %")

    fig.suptitle(f"{title_prefix}回測績效對照（各策略 vs VT）　紅=偏好組合 藍=VT 灰=對照",
                 fontsize=14, fontweight="bold")
    plt.tight_layout(rect=(0, 0, 1, 0.95))
    plt.savefig(output_path, dpi=300)
    plt.close()


def _cap_and_normalize(weights: np.ndarray, cap: float) -> np.ndarray:
    weights = np.maximum(weights.astype(float), 0.0)
    if weights.sum() <= 0:
        weights = np.ones_like(weights)
    weights = weights / weights.sum()

    for _ in range(20):
        over = weights > cap
        if not np.any(over):
            break
        weights[over] = cap
        remaining = 1.0 - weights[over].sum()
        under = ~over
        if remaining <= 0 or not np.any(under):
            break
        under_sum = weights[under].sum()
        weights[under] = remaining / under.sum() if under_sum <= 0 else weights[under] / under_sum * remaining

    return weights / weights.sum()


def _plot_final_period_frontiers(  # [DEAD CODE / 不符 C2] 未被呼叫；μ-σ + 8000 蒙地卡羅前緣,
    # 與 C2/BL(非 μ-σ 最佳化)框架不符。保留供參考,GitHub 清理時可移除。見 10 視覺化稽核。
    weights_df: pd.DataFrame,
    prices: pd.DataFrame,
    config: BacktestConfig,
    output_prefix: Path,
) -> None:
    if weights_df.empty:
        warnings.warn("Skip final-period frontier: empty weights.", RuntimeWarning)
        return

    last_date_label = weights_df["Rebalance_Date"].max()
    last_date = pd.Timestamp(last_date_label)
    final_weights = weights_df[weights_df["Rebalance_Date"] == last_date_label].copy()
    tickers = [ticker for ticker in final_weights["ETF"] if ticker in prices.columns]
    if len(tickers) < int(np.ceil(1.0 / config.max_weight_limit)):
        warnings.warn(
            f"Skip final-period frontier: only {len(tickers)} selected assets are available.",
            RuntimeWarning,
        )
        return

    returns = _lookback_prices(prices[tickers], last_date, config.lookback_years)
    returns = returns.pct_change(fill_method=None).dropna(how="any")
    if returns.empty:
        warnings.warn("Skip final-period frontier: empty final-period return matrix.", RuntimeWarning)
        return

    # Frontier 應該用最後一期「最佳化候選池」全部 ETF，而不是只用非零持倉。
    # 否則若最後權重剛好集中在 3 檔，efficient frontier 會退化成很窄的一條線。
    final_weights = final_weights.set_index("ETF").loc[tickers, "Weight"].astype(float).values
    if final_weights.sum() <= 0:
        warnings.warn("Skip final-period frontier: final portfolio weights sum to zero.", RuntimeWarning)
        return
    final_weights = final_weights / final_weights.sum()
    annual_returns = returns.mean().values * 252
    cov_matrix = returns.cov().values * 252
    n_assets = len(tickers)
    cap = config.max_weight_limit
    rf_rate = config.risk_free_rate

    def calc_vol(w: np.ndarray) -> float:
        return float(np.sqrt(np.dot(w.T, np.dot(cov_matrix, w))))

    def calc_ret(w: np.ndarray) -> float:
        return float(np.dot(w, annual_returns))

    initial = np.array([1.0 / n_assets] * n_assets)
    bounds = tuple((0.0, cap) for _ in range(n_assets))
    cons_sum = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

    max_sharpe = minimize(
        lambda w: -((calc_ret(w) - rf_rate) / calc_vol(w) if calc_vol(w) > 0 else -1e9),
        initial,
        method="SLSQP",
        bounds=bounds,
        constraints=[cons_sum],
    )
    max_sharpe_w = max_sharpe.x if max_sharpe.success else initial

    rng = np.random.default_rng(20260520)
    samples = []
    for _ in range(8000):
        w = _cap_and_normalize(rng.random(n_assets), cap)
        vol = calc_vol(w)
        ret = calc_ret(w)
        sharpe = (ret - rf_rate) / vol if vol > 0 else np.nan
        samples.append((vol, ret, sharpe))
    sample_df = pd.DataFrame(samples, columns=["Volatility", "Return", "Sharpe"])

    pref_vol = calc_vol(final_weights)
    pref_ret = calc_ret(final_weights)
    ms_vol = calc_vol(max_sharpe_w)
    ms_ret = calc_ret(max_sharpe_w)
    ms_sharpe = (ms_ret - rf_rate) / ms_vol if ms_vol > 0 else np.nan

    plt.figure(figsize=(10, 7))
    scatter = plt.scatter(
        sample_df["Volatility"] * 100,
        sample_df["Return"] * 100,
        c=sample_df["Sharpe"],
        cmap="viridis",
        s=10,
        alpha=0.35,
    )
    plt.colorbar(scatter, label="Sharpe Ratio")
    plt.scatter(pref_vol * 100, pref_ret * 100, color="red", marker="*", s=280, edgecolor="black", label="Backtest Final Portfolio")
    plt.scatter(ms_vol * 100, ms_ret * 100, color="blue", marker="X", s=160, edgecolor="black", label="Max Sharpe Portfolio")
    min_vol_plot = min(sample_df["Volatility"].min(), pref_vol, ms_vol) * 100 * 0.92
    max_vol_plot = max(sample_df["Volatility"].max(), pref_vol, ms_vol) * 100 * 1.05
    cml_x = np.array([0.0, ms_vol * 100, max_vol_plot])
    cml_y = rf_rate * 100 + ms_sharpe * cml_x
    plt.plot(cml_x, cml_y, color="darkorange", linestyle="--", linewidth=2, label="Capital Market Line")
    plt.title("Backtest Final-Period MPT Efficient Frontier")
    plt.xlabel("Annualized Volatility (%)")
    plt.ylabel("Expected Annual Return (%)")
    plt.xlim(left=max(0, min_vol_plot), right=max_vol_plot)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_prefix.with_name(f"{output_prefix.name}_mpt_efficient_frontier.png"), dpi=300)
    plt.close()

    gmv = minimize(calc_vol, initial, method="SLSQP", bounds=bounds, constraints=[cons_sum])
    max_ret = minimize(lambda w: -calc_ret(w), initial, method="SLSQP", bounds=bounds, constraints=[cons_sum])
    if not (gmv.success and max_ret.success):
        return

    target_returns = np.linspace(calc_ret(gmv.x), calc_ret(max_ret.x), 120)
    frontier_vols = []
    valid_returns = []
    for target in target_returns:
        cons = [
            cons_sum,
            {"type": "eq", "fun": lambda w, target=target: calc_ret(w) - target},
        ]
        res = minimize(calc_vol, initial, method="SLSQP", bounds=bounds, constraints=cons)
        if res.success:
            frontier_vols.append(calc_vol(res.x))
            valid_returns.append(target)

    if not frontier_vols:
        return

    plt.figure(figsize=(10, 7))
    plt.plot(np.array(frontier_vols) * 100, np.array(valid_returns) * 100, color="#2ECC71", linewidth=3, label="Efficient Frontier")
    plt.scatter(pref_vol * 100, pref_ret * 100, color="red", marker="*", s=280, edgecolor="black", label="Backtest Final Portfolio")
    plt.scatter(ms_vol * 100, ms_ret * 100, color="blue", marker="X", s=160, edgecolor="black", label="Max Sharpe Portfolio")
    plt.title("Backtest Final-Period Mathematical Efficient Frontier")
    plt.xlabel("Annualized Volatility (%)")
    plt.ylabel("Expected Annual Return (%)")
    min_frontier_vol = min(min(frontier_vols), pref_vol, ms_vol) * 100 * 0.92
    max_frontier_vol = max(max(frontier_vols), pref_vol, ms_vol) * 100 * 1.05
    plt.xlim(left=max(0, min_frontier_vol), right=max_frontier_vol)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_prefix.with_name(f"{output_prefix.name}_Mathematical Efficient Frontier.png"), dpi=300)
    plt.close()


def _plot_backtest_radar(summary_df: pd.DataFrame, output_path: Path) -> None:
    # [DORMANT] 目前未被 _write_unified_backtest_report 呼叫。保留供日後以偏好分數為核心重新設計後重用。
    if summary_df.empty or len(summary_df) < 2:
        return

    metrics = [
        ("Cumulative_Return_%", "Cumulative Return", False),
        ("CAGR_%", "CAGR", False),
        ("Annualized_Volatility_%", "Low Volatility", True),
        ("Max_Drawdown_%", "Low Drawdown", True),
        ("Sharpe", "Sharpe", False),
    ]
    labels = [label for _, label, _ in metrics]
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]

    def normalize_metric(series: pd.Series, reverse: bool) -> pd.Series:
        values = series.astype(float).copy()
        if reverse:
            values = -values.abs()
        if values.max() == values.min():
            return pd.Series([0.5] * len(values), index=values.index)
        return (values - values.min()) / (values.max() - values.min())

    score_table = pd.DataFrame(index=summary_df["Strategy"])
    for col, label, reverse in metrics:
        score_table[label] = normalize_metric(summary_df.set_index("Strategy")[col], reverse)

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw={"polar": True})
    for strategy, row in score_table.iterrows():
        values = row.tolist()
        values += values[:1]
        ax.plot(angles, values, linewidth=2, label=strategy)
        ax.fill(angles, values, alpha=0.12)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.set_title("Backtest Strategy Comparison Radar")
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _preference_score_column(df: pd.DataFrame, name: str) -> pd.Series:
    """安全取出偏好分數欄位，欄位不存在時回傳 NaN 序列。"""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype=float)


def _plot_preference_predictive_scatter(
    preference_scores_df: pd.DataFrame,
    output_path: Path,
    benchmark_label: str = "VOO",
    title_prefix: str = "",
) -> None:
    """V-1：偏好分數的樣本外預測力散佈圖。

    左圖（通用、profile-adaptive）：事前偏好分數 vs 事後實際偏好分數。
        因為偏好分數已內含使用者 AHP 權重，同一張圖自動適應保守型/報酬型，
        測的是「偏好滿足度的樣本外預測力」。
    右圖（報酬導向視角）：事前偏好分數 vs 未來實現報酬。
        只有對報酬導向使用者才是正確的成功指標，故另列一張並標註清楚。
    """
    if preference_scores_df is None or preference_scores_df.empty:
        return
    x = _preference_score_column(preference_scores_df, "Portfolio_ExAnte_Preference_Score")
    if x.notna().sum() < 3:
        return

    def _scatter(ax, x_series: pd.Series, y_series: pd.Series, ylabel: str, title: str) -> None:
        mask = x_series.notna() & y_series.notna()
        xv = x_series[mask].to_numpy(dtype=float)
        yv = y_series[mask].to_numpy(dtype=float)
        if len(xv) < 3:
            ax.text(0.5, 0.5, "Insufficient data", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            ax.set_xlabel("Ex-ante Preference Score (lookback)")
            ax.set_ylabel(ylabel)
            return
        ax.scatter(xv, yv, s=45, alpha=0.7, color="steelblue", edgecolor="black", linewidth=0.5)
        slope, intercept = np.polyfit(xv, yv, 1)
        xs = np.linspace(xv.min(), xv.max(), 50)
        ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=2)
        r = float(np.corrcoef(xv, yv)[0, 1]) if len(xv) > 1 else np.nan
        ax.set_title(f"{title}\nPearson r = {r:+.2f}  (n = {len(xv)})")
        ax.set_xlabel("Ex-ante Preference Score (lookback)")
        ax.set_ylabel(ylabel)

    sns.set_theme(style="whitegrid")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    _scatter(
        ax1,
        x,
        _preference_score_column(preference_scores_df, "Portfolio_Forward_Preference_Score"),
        "Forward (realized) Preference Score",
        "Preference-satisfaction predictive validity (profile-adaptive)",
    )
    _scatter(
        ax2,
        x,
        _preference_score_column(preference_scores_df, "Forward_Period_Return") * 100.0,
        "Forward Realized Return (%)",
        "Return-oriented view (valid only for return-seeking users)",
    )
    fig.suptitle(
        f"{title_prefix}V-1  Does a higher preference score predict better out-of-sample outcomes?",
        fontsize=14,
        fontweight="bold",
    )
    plt.tight_layout(rect=(0, 0, 1, 0.95))
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_preference_score_timeseries(
    preference_scores_df: pd.DataFrame,
    output_path: Path,
    benchmark_label: str = "VOO",
    title_prefix: str = "",
) -> None:
    """V-6：隨時間變化的偏好分數。

    上 (V-6a)：各策略事後（forward）偏好分數時間序列 + OOS 勝率（標題）。
    下 (V-6b)：本系統事前 vs 事後偏好分數，差距即偏好分數的樣本外衰減。
    """
    if preference_scores_df is None or preference_scores_df.empty:
        return
    if "Portfolio_Forward_Preference_Score" not in preference_scores_df.columns:
        return

    plot_df = pd.DataFrame(
        {
            "date": pd.to_datetime(preference_scores_df.get("Evaluation_Date"), errors="coerce"),
            "port_fwd": _preference_score_column(preference_scores_df, "Portfolio_Forward_Preference_Score"),
            "port_ex": _preference_score_column(preference_scores_df, "Portfolio_ExAnte_Preference_Score"),
            "voo": _preference_score_column(preference_scores_df, "Benchmark_Forward_Preference_Score"),
            "eq": _preference_score_column(preference_scores_df, "EqualWeight_Forward_Preference_Score"),
            "ms": _preference_score_column(preference_scores_df, "MaxSharpe_Forward_Preference_Score"),
        }
    ).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if plot_df.empty:
        return

    def _win_rate(other_col: str) -> float:
        pair = plot_df[["port_fwd", other_col]].dropna()
        if pair.empty:
            return np.nan
        return float((pair["port_fwd"] > pair[other_col]).mean() * 100.0)

    wr_voo, wr_eq, wr_ms = _win_rate("voo"), _win_rate("eq"), _win_rate("ms")

    sns.set_theme(style="whitegrid")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

    ax1.plot(plot_df["date"], plot_df["port_fwd"], label="System (Preference-Driven)", color="crimson", linewidth=2.5, marker="o", markersize=4)
    ax1.plot(plot_df["date"], plot_df["voo"], label=benchmark_label, color="steelblue", linewidth=1.8, alpha=0.85)
    ax1.plot(plot_df["date"], plot_df["eq"], label="Equal Weight", color="seagreen", linewidth=1.8, alpha=0.85)
    ax1.plot(plot_df["date"], plot_df["ms"], label="Max Sharpe", color="darkorange", linewidth=1.8, alpha=0.85)
    ax1.set_ylabel("Forward (realized) Preference Score")
    ax1.set_title(
        f"{title_prefix}V-6a  Out-of-sample preference score by strategy\n"
        f"System wins — {benchmark_label}: {wr_voo:.0f}%   EqualWeight: {wr_eq:.0f}%   MaxSharpe: {wr_ms:.0f}%  of periods"
    )
    ax1.legend(loc="best", fontsize=9)

    ax2.plot(plot_df["date"], plot_df["port_ex"], label="Ex-ante (lookback, expected)", color="gray", linestyle="--", linewidth=2)
    ax2.plot(plot_df["date"], plot_df["port_fwd"], label="Forward (realized)", color="crimson", linewidth=2.5, marker="o", markersize=4)
    ax2.fill_between(
        plot_df["date"],
        plot_df["port_ex"],
        plot_df["port_fwd"],
        where=(plot_df["port_ex"] >= plot_df["port_fwd"]),
        color="red",
        alpha=0.12,
        label="Out-of-sample decay",
    )
    ax2.set_ylabel("Preference Score")
    ax2.set_xlabel("Evaluation Date")
    ax2.set_title("V-6b  System portfolio: expected (ex-ante) vs realized (forward) preference score")
    ax2.legend(loc="best", fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def _plot_backtest_preference_radar(
    dimension_df: pd.DataFrame,
    output_path: Path,
    benchmark_label: str = "VT",
    title_prefix: str = "",
) -> None:
    """實現特徵雷達（回測）：系統(紅) vs 基準(藍)，9 維用投組**實際實現的特徵**。
    抗跌軸＝**全期最大回撤**（與摘要卡/績效圖一致，避免「每期子分數」與「全期 MaxDD」口徑矛盾）。
    各軸跨所有策略 min-max 正規化（越外圈＝相對越好）。純展示，不碰最佳化邏輯。"""
    if dimension_df is None or dimension_df.empty or "Strategy" not in dimension_df.columns:
        return
    # (顯示標籤, 欄位, 方向 +1=越大越好/-1=越小越好)
    specs_all = [
        ("報酬 CAGR", "CAGR_%", +1),
        ("殖利率", "Avg_Raw_Dividend_Yield_%", +1),
        ("低波動", "Annualized_Volatility_%", -1),
        ("抗跌(全期MaxDD)", "Max_Drawdown_%", +1),       # 負值，越接近 0（越大）越好
        ("低成本", "Avg_Raw_Expense_Ratio_%", -1),
        ("成交量", "Avg_Raw_Liquidity_Volume_M", +1),
        ("基金規模", "Avg_Raw_Liquidity_AUM_B", +1),
        ("分散(低HHI)", "Avg_Raw_Sector_HHI", -1),
        ("情緒", "Avg_Raw_FinBERT_Score", +1),
    ]
    specs = [(lab, col, d) for lab, col, d in specs_all if col in dimension_df.columns]
    if not specs:
        return
    df = dimension_df.drop_duplicates(subset="Strategy").set_index("Strategy")
    sys_name = "Preference_Driven"
    if sys_name not in df.index or benchmark_label not in df.index:
        return

    def _scaler(col, direction):
        s = pd.to_numeric(df[col], errors="coerce")
        vmin, vmax = float(s.min()), float(s.max())

        def sc(v):
            v = pd.to_numeric(v, errors="coerce")
            if pd.isna(v) or vmax <= vmin:
                return 0.5
            t = (float(v) - vmin) / (vmax - vmin)   # 值越大 → 1
            return t if direction > 0 else (1.0 - t)
        return sc

    sys_vals, vt_vals = [], []
    for lab, col, d in specs:
        f = _scaler(col, d)
        sys_vals.append(max(f(df.loc[sys_name, col]), 0.04))   # 下限 0.04，最差者仍可見
        vt_vals.append(max(f(df.loc[benchmark_label, col]), 0.04))

    labels = [lab for lab, _c, _d in specs]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]
    sys_p = sys_vals + sys_vals[:1]
    vt_p = vt_vals + vt_vals[:1]

    try:
        plt.rcParams["font.sans-serif"] = ["Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

    fig = plt.figure(figsize=(8, 8))
    ax = plt.subplot(111, polar=True)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"], fontsize=8, color="#94a3b8")
    ax.plot(angles, vt_p, color="steelblue", linewidth=2.0, label=benchmark_label)
    ax.fill(angles, vt_p, color="steelblue", alpha=0.12)
    ax.plot(angles, sys_p, color="crimson", linewidth=2.4, label="System (Preference-Driven)")
    ax.fill(angles, sys_p, color="crimson", alpha=0.18)
    ax.set_title(
        f"{title_prefix}實現特徵雷達：系統 vs {benchmark_label}\n"
        f"（投組實際實現特徵；跨策略相對位置，越外圈越好；抗跌＝全期最大回撤）",
        fontsize=12, pad=24,
    )
    ax.legend(loc="upper right", bbox_to_anchor=(1.18, 1.12), fontsize=10)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()


def _mirror_run_figures_to_upgrade(
    png_dir: Path, prefix: str, run_id: str, parent_dir: str | Path | None = None
) -> Path:
    """把本次回測的「全部圖片 + 報表」集中到使用者結果資料夾，並**分四個子夾**：
        01_text_reports/        文字結果（*.txt / *.md，含 summary 與 output_inventory）
        02_eda_dea_figures/     EDA 與 DEA 圖片（檔名含 eda/dea 的 *.png）
        03_performance_figures/ 表現圖片（nav / drawdown / 績效 / 雷達 / 年報酬 / 權重演化）
        04_data_csv/            過程中的 .csv 檔

    parent_dir 有給（主系統 prompt 回測會帶入 user_results/main_*/ 路徑）
      → 本次回測夾「巢狀」在該次使用者資料夾內；
    parent_dir=None（獨立執行回測）→ 自成一夾於 user_results/ 下。
    """
    stamp = time.strftime("%Y%m%d_%H%M%S")
    arm = str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper()
    # 用較短的資料夾名（prefix 已含頻率，如 backtest_q），避免巢狀後超過 Windows 260 字元路徑上限。
    short_name = f"{prefix}_arm{arm}_{stamp}"
    if parent_dir is not None:
        dest = Path(parent_dir) / short_name
    else:
        user_root = Path(getattr(parameters, "USER_RESULTS_DIR", "user_results"))
        dest = user_root / short_name

    def _bucket(name: str) -> str:
        low = name.lower()
        if low.endswith((".txt", ".md")):
            return "01_text_reports"
        if low.endswith(".png"):
            if "eda" in low or "dea" in low:
                return "02_eda_dea_figures"
            return "03_performance_figures"
        if low.endswith(".csv"):
            return "04_data_csv"
        return "04_data_csv"

    png_dir = Path(png_dir)
    # png_dir = backtest_report/png/<run_id>;report/csv 為其同層 sibling。
    report_dir = png_dir.parent.parent / "report" / run_id
    csv_dir = png_dir.parent.parent / "csv" / run_id
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src_dir in (png_dir, report_dir, csv_dir):
        if src_dir.exists():
            for f in src_dir.iterdir():
                if f.is_file():
                    sub = dest / _bucket(f.name)
                    sub.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, sub / f.name)
                    copied += 1
    return dest


def _write_output_inventory(config: BacktestConfig, prefix: str, run_id: str) -> None:
    inventory_path = Path(config.report_output_dir) / "report" / run_id / f"{prefix}_output_inventory.md"
    original_outputs = [
        "csv/stage0_yq_features.csv",
        "csv/stage0_final_matrix.csv",
        "csv/stage0_dea_ready_matrix.csv",
        "csv/stage1_dea_results.csv",
        "csv/stage1_super_efficiency_results.csv",
        "csv/stage1_final_candidates.csv",
        "csv/stage2_final_user_universe.csv",
        "csv/stage2_normalized_features.csv",
        "json/stage2_ahp_global_weights.json",
        "report/{CASE_NAME}_summary.txt",
        "report/{CASE_NAME}_weights.csv",
        "report/{CASE_NAME}_analytics.csv",
        "png/eda_histograms_beforeDEA.png",
        "png/eda_boxplots_beforeDEA.png",
        "png/eda_normalized_histograms.png",
        "png/eda_normalized_boxplots.png",
        "png/dea_score_distribution.png",
        "png/{CASE_NAME}_portfolio_performance.png",
        "png/{CASE_NAME}_mpt_efficient_frontier.png",
        "png/{CASE_NAME}_Mathematical Efficient Frontier.png",
        "png/{CASE_NAME}_radar_chart.png",
    ]
    backtest_outputs = [
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_weights.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_diagnostics.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_nav.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_price_nav.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_dividend_cash.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_price_returns.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_returns.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_cashflows.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_summary.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_preference_scores.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_period_dimension_comparison.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_dimension_comparison.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_annual_returns.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_turnover.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_final_feature_matrix.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_final_dea_ready_matrix.csv",
        f"{config.report_output_dir}/csv/{run_id}/{prefix}_final_dea_results.csv",
        f"{config.report_output_dir}/report/{run_id}/{prefix}_summary.txt",
        f"{config.report_output_dir}/report/{run_id}/{prefix}_analytics.csv",
        f"{config.report_output_dir}/report/{run_id}/{prefix}_dimension_comparison.csv",
        f"{config.report_output_dir}/report/{run_id}/{prefix}_final_weights.csv",
        f"{config.report_output_dir}/report/{run_id}/{prefix}_output_inventory.md",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_nav.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_drawdown.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_final_eda_histograms_beforeDEA.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_final_eda_boxplots_beforeDEA.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_final_eda_normalized_histograms.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_final_eda_normalized_boxplots.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_dea_score_distribution.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_portfolio_performance.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_radar_chart.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_annual_returns.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_weight_evolution.png",
        f"{config.report_output_dir}/png/{run_id}/{prefix}_metrics_comparison.png",
    ]

    with open(inventory_path, "w", encoding="utf-8") as f:
        f.write("# Output Inventory\n\n")
        f.write("## Original Main System Outputs\n")
        for item in original_outputs:
            f.write(f"- {item}\n")
        f.write("\n## Backtest System Unified Outputs\n")
        for item in backtest_outputs:
            f.write(f"- {item}\n")


def _write_unified_backtest_report(
    config: BacktestConfig,
    prefix: str,
    weights_df: pd.DataFrame,
    diagnostics_df: pd.DataFrame,
    nav: pd.DataFrame,
    price_nav: pd.DataFrame,
    dividend_cash: pd.DataFrame,
    price_returns: pd.DataFrame,
    returns: pd.DataFrame,
    cashflows: pd.DataFrame,
    summary_df: pd.DataFrame,
    preference_scores_df: pd.DataFrame | None,
    period_dimension_df: pd.DataFrame | None,
    dimension_comparison_df: pd.DataFrame | None,
    prices: pd.DataFrame,
    final_feature_df: pd.DataFrame | None = None,
    final_dea_ready_df: pd.DataFrame | None = None,
    final_dea_results_df: pd.DataFrame | None = None,
) -> None:
    run_id, _, csv_dir, png_dir, report_dir = _backtest_output_dirs(config)

    annual_returns = _annual_return_table(returns)
    turnover = _calc_turnover(weights_df)
    final_date = weights_df["Rebalance_Date"].max() if not weights_df.empty else ""
    final_weights = weights_df[weights_df["Rebalance_Date"] == final_date].copy() if final_date else pd.DataFrame()
    if not final_weights.empty:
        final_weights = final_weights[final_weights["Weight"] > 1e-8].sort_values("Weight", ascending=False)

    weights_df.to_csv(csv_dir / f"{prefix}_weights.csv", index=False)
    diagnostics_df.to_csv(csv_dir / f"{prefix}_diagnostics.csv", index=False)
    nav.to_csv(csv_dir / f"{prefix}_nav.csv", index_label="Date")
    price_nav.to_csv(csv_dir / f"{prefix}_price_nav.csv", index_label="Date")
    dividend_cash.to_csv(csv_dir / f"{prefix}_dividend_cash.csv", index_label="Date")
    price_returns.to_csv(csv_dir / f"{prefix}_price_returns.csv", index_label="Date")
    returns.to_csv(csv_dir / f"{prefix}_returns.csv", index_label="Date")
    cashflows.to_csv(csv_dir / f"{prefix}_cashflows.csv", index_label="Date")
    summary_df.to_csv(csv_dir / f"{prefix}_summary.csv", index=False)
    if preference_scores_df is not None and not preference_scores_df.empty:
        preference_scores_df.to_csv(csv_dir / f"{prefix}_preference_scores.csv", index=False)
    if period_dimension_df is not None and not period_dimension_df.empty:
        period_dimension_df.to_csv(csv_dir / f"{prefix}_period_dimension_comparison.csv", index=False)
    if dimension_comparison_df is not None and not dimension_comparison_df.empty:
        dimension_comparison_df.to_csv(csv_dir / f"{prefix}_dimension_comparison.csv", index=False)
    annual_returns.to_csv(csv_dir / f"{prefix}_annual_returns.csv", index=False)
    turnover.to_csv(csv_dir / f"{prefix}_turnover.csv", index=False)
    if final_feature_df is not None and not final_feature_df.empty:
        final_feature_df.to_csv(csv_dir / f"{prefix}_final_feature_matrix.csv", index=False)
    if final_dea_ready_df is not None and not final_dea_ready_df.empty:
        final_dea_ready_df.to_csv(csv_dir / f"{prefix}_final_dea_ready_matrix.csv", index=False)
    if final_dea_results_df is not None and not final_dea_results_df.empty:
        final_dea_results_df.to_csv(csv_dir / f"{prefix}_final_dea_results.csv", index=False)

    summary_df.to_csv(report_dir / f"{prefix}_analytics.csv", index=False, encoding="utf-8-sig")
    if dimension_comparison_df is not None and not dimension_comparison_df.empty:
        dimension_comparison_df.to_csv(
            report_dir / f"{prefix}_dimension_comparison.csv",
            index=False,
            encoding="utf-8-sig",
        )
    final_weights.to_csv(report_dir / f"{prefix}_final_weights.csv", index=False, encoding="utf-8-sig")

    with open(report_dir / f"{prefix}_summary.txt", "w", encoding="utf-8") as f:
        f.write("=" * 72 + "\n")
        f.write("Backtest Portfolio Report\n")
        f.write("=" * 72 + "\n")
        f.write(f"Start Date: {config.start_date}\n")
        f.write(f"End Date: {config.end_date or nav.index.max().strftime('%Y-%m-%d')}\n")
        f.write(f"Rebalance Frequency: {config.rebalance_freq}\n")
        f.write(f"Lookback Years: {config.lookback_years}\n")
        f.write(f"Minimum History Years: {config.min_history_years}\n")
        f.write(f"Initial Capital: {config.initial_capital:,.2f}\n")
        f.write(f"Periodic Contribution: {config.periodic_contribution:,.2f}\n")
        f.write(f"Benchmark: {config.benchmark_ticker}\n\n")
        f.write(f"Comparison Benchmarks: {', '.join(config.comparison_benchmarks)}\n\n")
        f.write("Performance Summary\n")
        f.write(summary_df.to_string(index=False) + "\n\n")
        if preference_scores_df is not None and not preference_scores_df.empty:
            score_cols = [
                "Portfolio_Forward_Preference_Score",
                "Benchmark_Forward_Preference_Score",
                "EqualWeight_Forward_Preference_Score",
                "MaxSharpe_Forward_Preference_Score",
                "Forward_Score_vs_Benchmark",
                "Forward_Score_vs_EqualWeight",
                "Forward_Score_vs_MaxSharpe",
            ]
            score_summary = preference_scores_df[[col for col in score_cols if col in preference_scores_df.columns]].describe()
            f.write("Forward Preference Score Summary\n")
            f.write(score_summary.to_string() + "\n\n")
        if dimension_comparison_df is not None and not dimension_comparison_df.empty:
            f.write("Aggregate Dimension Comparison\n")
            f.write(dimension_comparison_df.to_string(index=False) + "\n\n")
            f.write(
                "Return Basis Note: total wealth equals capital-gain price NAV plus estimated dividend cash. "
                "If close-price cache is missing, capital gains may still fall back to adjusted-price data.\n\n"
            )
        f.write("Diagnostics Summary\n")
        f.write(diagnostics_df.describe(include="all").to_string() + "\n\n")
        if not final_weights.empty:
            f.write(f"Final Rebalance Weights ({final_date})\n")
            f.write(final_weights[["ETF", "Weight"]].to_string(index=False) + "\n")

    _plot_backtest_performance_report(nav, png_dir / f"{prefix}_portfolio_performance.png")
    _plot_annual_returns(annual_returns, png_dir / f"{prefix}_annual_returns.png")
    _plot_weight_evolution(weights_df, png_dir / f"{prefix}_weight_evolution.png")
    _plot_backtest_metrics_comparison(summary_df, dimension_comparison_df, png_dir / f"{prefix}_metrics_comparison.png")
    # 雷達圖已停用，待日後以「偏好分數」為核心重新設計後再接回（見 03_planned_upgrade_items.md V-1/V-6）。
    # _plot_backtest_radar 函式保留在檔案中供未來重用，目前不輸出 radar_chart.png。
    _plot_backtest_outputs(nav, prefix, png_dir)
    # V-1 / V-6：以偏好分數為核心的樣本外驗證圖（資料來自 preference_scores_df，不碰最佳化邏輯）。
    if preference_scores_df is not None and not preference_scores_df.empty:
        _plot_preference_predictive_scatter(
            preference_scores_df,
            png_dir / f"{prefix}_preference_predictive_scatter.png",
            benchmark_label=config.benchmark_ticker,
        )
        _plot_preference_score_timeseries(
            preference_scores_df,
            png_dir / f"{prefix}_preference_score_timeseries.png",
            benchmark_label=config.benchmark_ticker,
        )
        _plot_backtest_preference_radar(
            dimension_comparison_df,
            png_dir / f"{prefix}_preference_radar_vs_benchmark.png",
            benchmark_label=config.benchmark_ticker,
        )
    if final_feature_df is not None and not final_feature_df.empty:
        raw_cols = [
            "Return_CAGR (%)",
            "Return_Div (%)",
            "Risk_Vol (%)",
            "Risk_MaxDD (%)",
            "Cost_ExpRatio (%)",
            "Liq_Volume (M)",
            "Liq_AUM (B)",
            _div_score_col(final_feature_df),
            "FinBERT_score",
        ]
        _plot_distribution_grid(
            final_feature_df,
            raw_cols,
            png_dir / f"{prefix}_final_eda_histograms_beforeDEA.png",
            "Backtest Final Rebalance Feature Histograms",
            "hist",
        )
        _plot_distribution_grid(
            final_feature_df,
            raw_cols,
            png_dir / f"{prefix}_final_eda_boxplots_beforeDEA.png",
            "Backtest Final Rebalance Feature Boxplots",
            "box",
        )
    if final_dea_ready_df is not None and not final_dea_ready_df.empty:
        dea_cols = [col for col in final_dea_ready_df.columns if col != "ETF"]
        _plot_distribution_grid(
            final_dea_ready_df,
            dea_cols,
            png_dir / f"{prefix}_final_eda_normalized_histograms.png",
            "Backtest Final Rebalance Normalized Feature Histograms",
            "hist",
        )
        _plot_distribution_grid(
            final_dea_ready_df,
            dea_cols,
            png_dir / f"{prefix}_final_eda_normalized_boxplots.png",
            "Backtest Final Rebalance Normalized Feature Boxplots",
            "box",
        )
    if final_dea_results_df is not None and not final_dea_results_df.empty:
        _plot_dea_distribution_backtest(final_dea_results_df, png_dir / f"{prefix}_dea_score_distribution.png")
    _write_output_inventory(config, prefix, run_id)
    # 把本次所有圖片（含 V-1/V-6 與 portfolio_performance 等）集中複製到 upgrade_figures/ 的本次專屬資料夾。
    mirrored_dir = _mirror_run_figures_to_upgrade(
        png_dir, prefix, run_id, parent_dir=config.user_results_parent
    )
    print(f"[user_results] 本次回測全部圖表+報表已分四夾集中到 {mirrored_dir} "
          f"（01_text_reports / 02_eda_dea_figures / 03_performance_figures / 04_data_csv）")


def run_rolling_backtest(config: BacktestConfig | None = None) -> dict[str, pd.DataFrame]:
    cfg = config or BacktestConfig()
    _ensure_output_dirs(cfg)

    static_features = _load_static_features(cfg)
    global_weights = _load_global_weights(cfg)
    # 回測全程共用同一份每日情緒 cache，避免每個再平衡日重複讀檔。
    sentiment_daily_df = load_daily_sentiment(cfg.sentiment_cache_file)
    dividend_yields = static_features.set_index("ETF")["Return_Div (%)"].fillna(0.0).astype(float)
    tickers = static_features["ETF"].dropna().astype(str).tolist()
    _anchor = getattr(parameters, "BETA_ANCHOR_TICKER", None)
    comparison_benchmarks = tuple(
        dict.fromkeys(
            [
                str(cfg.benchmark_ticker).strip(),
                *[str(ticker).strip() for ticker in cfg.comparison_benchmarks],
                *([str(_anchor).strip()] if _anchor else []),  # 確保 beta 錨的價格也被載入
            ]
        )
    )
    for benchmark in comparison_benchmarks:
        if benchmark and benchmark not in tickers:
            tickers.append(benchmark)

    prices, volumes = load_or_fetch_backtest_data(tickers, cfg)
    investable_tickers = filter_min_history(prices, cfg)

    if not investable_tickers:
        raise ValueError(
            "No ETF passes the minimum history filter. "
            "Fetch a longer backtest price cache first, e.g. run with --fetch-missing-data --fetch-period 10y."
        )

    # benchmark 只作為比較組，不參與系統選股；但要保留價格與特徵，才能做維度比較。
    price_cols = investable_tickers.copy()
    for benchmark in comparison_benchmarks:
        if benchmark in prices.columns and benchmark not in price_cols:
            price_cols.append(benchmark)
    prices = prices[price_cols]
    volumes = volumes[[ticker for ticker in price_cols if ticker in volumes.columns]]
    rebalance_dates = generate_rebalance_dates(prices[investable_tickers], cfg)
    terminal_date = prices[investable_tickers].dropna(how="all").index.max()
    if pd.notna(terminal_date) and rebalance_dates and terminal_date > rebalance_dates[-1]:
        # 最後一期投組應持有到資料最新交易日，否則 NAV 會停在最後一個季末再平衡日。
        rebalance_dates.append(terminal_date)
    if len(rebalance_dates) < 2:
        raise ValueError("Need at least two rebalance dates for a rolling backtest.")

    weight_rows = []
    price_returns_parts = []
    income_rate_parts = []
    total_returns_parts = []
    equal_returns_parts = []
    equal_income_rate_parts = []
    equal_total_returns_parts = []
    max_sharpe_returns_parts = []
    max_sharpe_income_rate_parts = []
    max_sharpe_total_returns_parts = []
    funding_dates = []
    preference_score_rows = []
    dimension_rows = []
    diagnostics = []
    final_feature_df = pd.DataFrame()
    final_dea_ready_df = pd.DataFrame()
    final_dea_results_df = pd.DataFrame()
    benchmark_price_return_parts = {benchmark: [] for benchmark in comparison_benchmarks}
    benchmark_income_rate_parts = {benchmark: [] for benchmark in comparison_benchmarks}
    benchmark_total_return_parts = {benchmark: [] for benchmark in comparison_benchmarks}

    for i, as_of_date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i + 1]
        feature_df = build_asof_feature_matrix(
            static_features,
            prices[investable_tickers],
            volumes,
            as_of_date,
            cfg,
            sentiment_daily_df=sentiment_daily_df,
        )
        if feature_df.empty or "ETF" not in feature_df.columns:
            # 早期再平衡日可能因 lookback 視窗不足而沒有可用特徵，直接跳過避免用不完整資料硬算。
            diagnostics.append(
                {
                    "Rebalance_Date": as_of_date.strftime("%Y-%m-%d"),
                    "Next_Rebalance_Date": next_date.strftime("%Y-%m-%d"),
                    "Feature_Universe": 0,
                    "DEA_Universe": 0,
                    "Candidate_Universe": 0,
                    "Selected_Universe": 0,
                    "Optimized_Holdings": 0,
                    "Skip_Reason": "empty_feature_matrix",
                }
            )
            continue

        feature_df = feature_df[feature_df["ETF"].isin(investable_tickers)].reset_index(drop=True)
        dea_ready = build_dea_ready_matrix(feature_df)
        dea_results = solve_dea_scores(dea_ready)
        # 保留最後一個再平衡日的截面資料，用來產生與原系統 Stage 0/1 對應的 EDA 與 DEA 圖表。
        final_feature_df = feature_df.copy()
        final_dea_ready_df = dea_ready.copy()
        final_dea_results_df = dea_results.copy()
        candidates = solve_cross_efficiency(dea_results, cfg.dea_threshold)
        scored_df, scaled_df = build_preference_scores(candidates, feature_df, global_weights)
        lookback_returns = (
            _lookback_prices(prices[investable_tickers], as_of_date, cfg.lookback_years)
            .pct_change(fill_method=None)
            .dropna()
        )
        selected = select_cluster_representatives(scored_df, lookback_returns, cfg.corr_threshold)
        # Arm C2 的 market/beta 核心需要「市場錨」的 lookback 報酬流（只用報酬，不需成分權重）。
        # 錨可與報告基準解耦（BETA_ANCHOR_TICKER）；None 時沿用報告基準。
        benchmark_lookback_returns = None
        if str(getattr(parameters, "OPTIMIZATION_ARM", "A")).upper() in ("C2", "BL"):
            anchor_ticker = str(getattr(parameters, "BETA_ANCHOR_TICKER", None) or cfg.benchmark_ticker)
            if anchor_ticker in prices.columns:
                _bench_lb = (
                    _lookback_prices(prices[[anchor_ticker]], as_of_date, cfg.lookback_years)
                    .pct_change(fill_method=None)
                    .dropna()
                )
                if anchor_ticker in _bench_lb.columns and not _bench_lb.empty:
                    benchmark_lookback_returns = _bench_lb[anchor_ticker]
        weights = optimize_preference_portfolio(
            selected, scaled_df, lookback_returns, global_weights, cfg,
            benchmark_returns=benchmark_lookback_returns,
        )
        max_sharpe_weights = optimize_max_sharpe_portfolio(selected, lookback_returns, cfg)

        diagnostics.append(
            {
                "Rebalance_Date": as_of_date.strftime("%Y-%m-%d"),
                "Next_Rebalance_Date": next_date.strftime("%Y-%m-%d"),
                "Feature_Universe": len(feature_df),
                "DEA_Universe": len(dea_results),
                "Candidate_Universe": len(candidates),
                "Selected_Universe": len(selected),
                "Optimized_Holdings": len(weights),
            }
        )

        if weights.empty:
            continue

        for ticker, weight in weights.items():
            weight_rows.append(
                {
                    "Rebalance_Date": as_of_date.strftime("%Y-%m-%d"),
                    "ETF": ticker,
                    "Weight": weight,
                }
            )

        # 嚴格 buy-and-hold：再平衡日依照目標權重買入，期間不每日調回目標權重。
        period_returns, drifted_weights = _buy_and_hold_period_returns(prices, as_of_date, next_date, weights)
        # 嚴格 buy-and-hold：價格報酬與股息收入分開計算，股息累積成現金且不再投入。
        period_price_returns, period_income_rates, period_total_returns, drifted_weights = _buy_and_hold_period_components(
            prices,
            as_of_date,
            next_date,
            weights,
            dividend_yields,
        )
        if period_price_returns.empty:
            continue
        funding_dates.append(as_of_date)
        price_returns_parts.append(period_price_returns.rename("Preference_Driven"))
        income_rate_parts.append(period_income_rates.rename("Preference_Driven"))
        total_returns_parts.append(period_total_returns.rename("Preference_Driven"))

        equal_weights = pd.Series(
            1.0 / len(weights),
            index=weights.index,
            dtype=float,
        )
        equal_price_returns, equal_income_rates, equal_total_returns, equal_drifted_weights = _buy_and_hold_period_components(
            prices,
            as_of_date,
            next_date,
            equal_weights,
            dividend_yields,
        )
        max_sharpe_price_returns, max_sharpe_income_rates, max_sharpe_total_returns, max_sharpe_drifted_weights = _buy_and_hold_period_components(
            prices,
            as_of_date,
            next_date,
            max_sharpe_weights,
            dividend_yields,
        )
        if not equal_price_returns.empty:
            equal_returns_parts.append(equal_price_returns.rename("EqualWeight"))
            equal_income_rate_parts.append(equal_income_rates.rename("EqualWeight"))
            equal_total_returns_parts.append(equal_total_returns.rename("EqualWeight"))
        if not max_sharpe_price_returns.empty:
            max_sharpe_returns_parts.append(max_sharpe_price_returns.rename("MaxSharpe"))
            max_sharpe_income_rate_parts.append(max_sharpe_income_rates.rename("MaxSharpe"))
            max_sharpe_total_returns_parts.append(max_sharpe_total_returns.rename("MaxSharpe"))
        benchmark_periods = {}
        for benchmark in comparison_benchmarks:
            benchmark_weights = pd.Series({benchmark: 1.0}, dtype=float)
            (
                benchmark_price_returns_i,
                benchmark_income_rates_i,
                benchmark_total_returns_i,
                benchmark_drifted_weights_i,
            ) = _buy_and_hold_period_components(
                prices,
                as_of_date,
                next_date,
                benchmark_weights,
                dividend_yields,
            )
            benchmark_periods[benchmark] = {
                "price_returns": benchmark_price_returns_i,
                "income_rates": benchmark_income_rates_i,
                "total_returns": benchmark_total_returns_i,
                "weights": benchmark_drifted_weights_i,
            }
            if not benchmark_price_returns_i.empty:
                benchmark_price_return_parts[benchmark].append(benchmark_price_returns_i.rename(benchmark))
                benchmark_income_rate_parts[benchmark].append(benchmark_income_rates_i.rename(benchmark))
                benchmark_total_return_parts[benchmark].append(benchmark_total_returns_i.rename(benchmark))

        # 抗跌分數的「共同尺度」：用候選池（lookback 截面）全體個股 MaxDD 分布建尺，ex-ante 各策略共用。
        ex_ante_maxdd_bounds = calculate_individual_maxdd_bounds(lookback_returns)
        ex_ante_score = calculate_portfolio_utility(weights, scaled_df, lookback_returns, global_weights, cfg, benchmark_returns=benchmark_lookback_returns, maxdd_bounds=ex_ante_maxdd_bounds)

        # 評估下一期偏好分數時，把 benchmark 也放進同一個截面，尺度才可直接比較。
        evaluation_tickers = [
            ticker
            for ticker in dict.fromkeys([*investable_tickers, *comparison_benchmarks])
            if ticker in prices.columns
        ]
        evaluation_feature_df = build_asof_feature_matrix(
            static_features,
            prices[evaluation_tickers],
            volumes,
            next_date,
            cfg,
            sentiment_daily_df=sentiment_daily_df,
        )
        evaluation_returns = (
            _lookback_prices(prices[evaluation_tickers], next_date, cfg.lookback_years)
            .pct_change(fill_method=None)
            .dropna()
        )
        evaluation_scaled = scale_preference_features(evaluation_feature_df) if not evaluation_feature_df.empty else pd.DataFrame()
        primary_benchmark = cfg.benchmark_ticker
        primary_benchmark_returns = benchmark_periods.get(primary_benchmark, {}).get(
            "total_returns",
            pd.Series(dtype=float),
        )
        primary_benchmark_drifted_weights = benchmark_periods.get(primary_benchmark, {}).get(
            "weights",
            pd.Series(dtype=float),
        )
        # beta 評分基礎用：評估截面裡的基準(VT)報酬流（evaluation_returns 已含 benchmark 欄）。
        eval_bench_ret = (
            evaluation_returns[primary_benchmark]
            if primary_benchmark in evaluation_returns.columns
            else None
        )

        # ★抗跌分數「共同尺度」★：用評估截面（含 VT 等基準）全體個股 MaxDD 分布建一把尺，
        # 讓 System / VT / EqualWeight / MaxSharpe 都站在同一尺度比較。
        # （修正：單一標的基準若各自建尺會退化成滿分 1.0，使抗跌權重高的使用者誤判 VT 必勝。）
        eval_maxdd_bounds = calculate_individual_maxdd_bounds(evaluation_returns)
        forward_score = calculate_portfolio_utility(
            drifted_weights,
            evaluation_scaled,
            evaluation_returns,
            global_weights,
            cfg,
            benchmark_returns=eval_bench_ret,
            maxdd_bounds=eval_maxdd_bounds,
        )
        benchmark_score = calculate_portfolio_utility(
            primary_benchmark_drifted_weights,
            evaluation_scaled,
            evaluation_returns,
            global_weights,
            cfg,
            benchmark_returns=eval_bench_ret,
            maxdd_bounds=eval_maxdd_bounds,
        )
        equal_score = calculate_portfolio_utility(
            equal_drifted_weights,
            evaluation_scaled,
            evaluation_returns,
            global_weights,
            cfg,
            benchmark_returns=eval_bench_ret,
            maxdd_bounds=eval_maxdd_bounds,
        )
        max_sharpe_score = calculate_portfolio_utility(
            max_sharpe_drifted_weights,
            evaluation_scaled,
            evaluation_returns,
            global_weights,
            cfg,
            benchmark_returns=eval_bench_ret,
            maxdd_bounds=eval_maxdd_bounds,
        )

        def flatten_score(prefix: str, score: dict[str, float]) -> dict[str, float]:
            return {f"{prefix}_{key}": value for key, value in score.items()}

        # 每一段 buy-and-hold 結束後，用漂移後權重衡量「實際持有到下一期」的資產特徵。
        dimension_specs = [
            ("Preference_Driven", drifted_weights, period_total_returns),
            ("EqualWeight", equal_drifted_weights, equal_total_returns),
            ("MaxSharpe", max_sharpe_drifted_weights, max_sharpe_total_returns),
        ]
        for benchmark, payload in benchmark_periods.items():
            dimension_specs.append((benchmark, payload["weights"], payload["total_returns"]))
        for strategy, strategy_weights, strategy_returns in dimension_specs:
            if strategy_weights.empty:
                continue
            dimension_rows.append(
                build_period_dimension_row(
                    strategy,
                    as_of_date,
                    next_date,
                    strategy_weights,
                    strategy_returns,
                    evaluation_feature_df,
                    evaluation_scaled,
                    evaluation_returns,
                    global_weights,
                    cfg,
                )
            )

        preference_score_rows.append(
            {
                "Rebalance_Date": as_of_date.strftime("%Y-%m-%d"),
                "Evaluation_Date": next_date.strftime("%Y-%m-%d"),
                "Forward_Period_Return": (1 + period_total_returns).prod() - 1,
                "Capital_Gain_Forward_Return": (1 + period_price_returns).prod() - 1,
                "Dividend_Income_Forward_Return": (1 + period_total_returns).prod()
                - (1 + period_price_returns).prod(),
                "Benchmark_Forward_Return": (1 + primary_benchmark_returns).prod() - 1
                if not primary_benchmark_returns.empty
                else np.nan,
                "EqualWeight_Forward_Return": (1 + equal_total_returns).prod() - 1
                if not equal_total_returns.empty
                else np.nan,
                "MaxSharpe_Forward_Return": (1 + max_sharpe_total_returns).prod() - 1
                if not max_sharpe_total_returns.empty
                else np.nan,
                **flatten_score("Portfolio_ExAnte", ex_ante_score),
                **flatten_score("Portfolio_Forward", forward_score),
                **flatten_score("Benchmark_Forward", benchmark_score),
                **flatten_score("EqualWeight_Forward", equal_score),
                **flatten_score("MaxSharpe_Forward", max_sharpe_score),
                "Forward_Score_vs_Benchmark": forward_score.get("Preference_Score", np.nan)
                - benchmark_score.get("Preference_Score", np.nan),
                "Forward_Score_vs_EqualWeight": forward_score.get("Preference_Score", np.nan)
                - equal_score.get("Preference_Score", np.nan),
                "Forward_Score_vs_MaxSharpe": forward_score.get("Preference_Score", np.nan)
                - max_sharpe_score.get("Preference_Score", np.nan),
            }
        )

    if not total_returns_parts:
        raise ValueError("Backtest produced no return series. Check history coverage and rebalance dates.")

    def assemble_strategy_wealth(
        strategy_name: str,
        price_parts: list[pd.Series],
        income_parts: list[pd.Series],
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        price_returns = pd.concat(price_parts).sort_index()
        price_returns = price_returns[~price_returns.index.duplicated(keep="first")]
        income_rates = pd.concat(income_parts).sort_index().reindex(price_returns.index).fillna(0.0)
        income_rates = income_rates[~income_rates.index.duplicated(keep="first")]
        price_nav, dividend_cash, total_wealth, strategy_cashflows = _build_wealth_with_cashflows(
            price_returns,
            income_rates,
            funding_dates,
            cfg,
        )
        total_returns = _returns_from_wealth(total_wealth, strategy_cashflows).rename(strategy_name)
        price_returns_actual = _returns_from_wealth(price_nav, strategy_cashflows).rename(strategy_name)
        return (
            price_nav.rename(strategy_name),
            dividend_cash.rename(strategy_name),
            total_wealth.rename(strategy_name),
            price_returns_actual,
            total_returns,
            strategy_cashflows.rename(strategy_name),
        )

    strategy_inputs = [
        ("Preference_Driven", price_returns_parts, income_rate_parts),
        ("EqualWeight", equal_returns_parts, equal_income_rate_parts),
        ("MaxSharpe", max_sharpe_returns_parts, max_sharpe_income_rate_parts),
    ]
    for benchmark in comparison_benchmarks:
        strategy_inputs.append(
            (
                benchmark,
                benchmark_price_return_parts.get(benchmark, []),
                benchmark_income_rate_parts.get(benchmark, []),
            )
        )

    price_nav_parts = []
    dividend_cash_parts = []
    total_wealth_parts = []
    price_return_parts_out = []
    total_return_parts_out = []
    cashflow_parts = []
    for strategy_name, strategy_price_parts, strategy_income_parts in strategy_inputs:
        if not strategy_price_parts or not strategy_income_parts:
            continue
        (
            strategy_price_nav,
            strategy_dividend_cash,
            strategy_total_wealth,
            strategy_price_returns,
            strategy_total_returns,
            strategy_cashflows,
        ) = assemble_strategy_wealth(strategy_name, strategy_price_parts, strategy_income_parts)
        price_nav_parts.append(strategy_price_nav)
        dividend_cash_parts.append(strategy_dividend_cash)
        total_wealth_parts.append(strategy_total_wealth)
        price_return_parts_out.append(strategy_price_returns)
        total_return_parts_out.append(strategy_total_returns)
        cashflow_parts.append(strategy_cashflows)

    price_nav = pd.concat(price_nav_parts, axis=1).dropna(how="all")
    dividend_cash = pd.concat(dividend_cash_parts, axis=1).dropna(how="all")
    nav = pd.concat(total_wealth_parts, axis=1).dropna(how="all")
    price_returns = pd.concat(price_return_parts_out, axis=1).dropna(how="all")
    returns = pd.concat(total_return_parts_out, axis=1).dropna(how="all")
    cashflows = pd.concat(cashflow_parts, axis=1).reindex(returns.index).fillna(0.0)

    weights_df = pd.DataFrame(weight_rows)
    diagnostics_df = pd.DataFrame(diagnostics)
    preference_scores_df = pd.DataFrame(preference_score_rows)
    period_dimension_df = pd.DataFrame(dimension_rows)
    summary_df = pd.DataFrame(
        [
            {
                "Strategy": col,
                **_performance_summary(nav[col].dropna(), returns[col].dropna(), cashflows[col].dropna()),
                **_income_split_summary(
                    price_nav[col].dropna(),
                    dividend_cash[col].dropna(),
                    nav[col].dropna(),
                    cashflows[col].dropna(),
                ),
            }
            for col in nav.columns
        ]
    )
    dimension_comparison_df = build_aggregate_dimension_comparison(period_dimension_df, summary_df, cfg)

    prefix = f"backtest_{cfg.rebalance_freq.lower()}"
    _, raw_dir, _, _, _ = _backtest_output_dirs(cfg)
    weights_df.to_csv(raw_dir / f"{prefix}_weights.csv", index=False)
    diagnostics_df.to_csv(raw_dir / f"{prefix}_diagnostics.csv", index=False)
    nav.to_csv(raw_dir / f"{prefix}_nav.csv", index_label="Date")
    price_nav.to_csv(raw_dir / f"{prefix}_price_nav.csv", index_label="Date")
    dividend_cash.to_csv(raw_dir / f"{prefix}_dividend_cash.csv", index_label="Date")
    price_returns.to_csv(raw_dir / f"{prefix}_price_returns.csv", index_label="Date")
    returns.to_csv(raw_dir / f"{prefix}_returns.csv", index_label="Date")
    cashflows.to_csv(raw_dir / f"{prefix}_cashflows.csv", index_label="Date")
    summary_df.to_csv(raw_dir / f"{prefix}_summary.csv", index=False)
    preference_scores_df.to_csv(raw_dir / f"{prefix}_preference_scores.csv", index=False)
    period_dimension_df.to_csv(raw_dir / f"{prefix}_period_dimension_comparison.csv", index=False)
    dimension_comparison_df.to_csv(raw_dir / f"{prefix}_dimension_comparison.csv", index=False)
    try:
        _write_unified_backtest_report(
            cfg,
            prefix,
            weights_df,
            diagnostics_df,
            nav,
            price_nav,
            dividend_cash,
            price_returns,
            returns,
            cashflows,
            summary_df,
            preference_scores_df,
            period_dimension_df,
            dimension_comparison_df,
            prices,
            final_feature_df,
            final_dea_ready_df,
            final_dea_results_df,
        )
    except Exception as exc:
        warnings.warn(f"Unified backtest report generation failed: {exc}", RuntimeWarning)

    return {
        "weights": weights_df,
        "diagnostics": diagnostics_df,
        "nav": nav,
        "price_nav": price_nav,
        "dividend_cash": dividend_cash,
        "price_returns": price_returns,
        "returns": returns,
        "cashflows": cashflows,
        "summary": summary_df,
        "preference_scores": preference_scores_df,
        "period_dimension_comparison": period_dimension_df,
        "dimension_comparison": dimension_comparison_df,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rolling backtest for the ETF robo-advisor system.")
    parser.add_argument("--start-date", default=DEFAULT_BACKTEST_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_BACKTEST_END_DATE)
    parser.add_argument("--freq", default=DEFAULT_REBALANCE_FREQ, choices=["M", "Q", "6M", "Y"])
    parser.add_argument("--lookback-years", type=int, default=DEFAULT_LOOKBACK_YEARS)
    parser.add_argument("--min-history-years", type=int, default=DEFAULT_MIN_HISTORY_YEARS)
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--periodic-contribution", type=float, default=DEFAULT_PERIODIC_CONTRIBUTION)
    parser.add_argument("--fetch-missing-data", default=DEFAULT_FETCH_MISSING_DATA, action=argparse.BooleanOptionalAction)
    parser.add_argument("--fetch-period", default=DEFAULT_FETCH_PERIOD)
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK_TICKER)
    parser.add_argument(
        "--comparison-benchmarks",
        default=",".join(DEFAULT_COMPARISON_BENCHMARKS),
        help="Comma-separated benchmark tickers for dimension comparison, e.g. VOO,VT.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = BacktestConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        lookback_years=args.lookback_years,
        min_history_years=args.min_history_years,
        rebalance_freq=args.freq,
        initial_capital=args.initial_capital,
        periodic_contribution=args.periodic_contribution,
        fetch_missing_data=args.fetch_missing_data,
        fetch_period=args.fetch_period,
        benchmark_ticker=args.benchmark,
        comparison_benchmarks=tuple(
            ticker.strip()
            for ticker in str(args.comparison_benchmarks).split(",")
            if ticker.strip()
        ),
    )
    results = run_rolling_backtest(config)
    print(results["summary"].to_string(index=False))
