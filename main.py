import concurrent.futures
import html
import json
import os
import re
from datetime import date, datetime

import feedparser
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


def get_config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default))


ECOS_API_KEY = get_config_value("ECOS_API_KEY")
FRED_API_KEY = get_config_value("FRED_API_KEY")

ECOS_BASE = f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr"
ECOS_ITEM_BASE = f"https://ecos.bok.or.kr/api/StatisticItemList/{ECOS_API_KEY}/json/kr"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FRED_FETCH_ERRORS: dict[str, str] = {}
ECOS_FETCH_ERRORS: dict[str, str] = {}
MARKET_PROXY_ERRORS: dict[str, str] = {}

START_MONTH = "201501"
START_DAY = "20150101"
FRED_START = "2015-01-01"
TODAY = date.today()
END_MONTH = TODAY.strftime("%Y%m")
END_DAY = TODAY.strftime("%Y%m%d")

DOMESTIC_SERIES = {
    "기준금리": {
        "stat": "722Y001",
        "cycle": "M",
        "items": ["0101000"],
        "unit": "%",
        "description": "한국은행 정책금리입니다. 시장금리의 기준점이며 일간 차트에서는 다음 발표 전까지 같은 값으로 이어서 표시합니다.",
    },
    "국고채 3년": {
        "stat": "817Y002",
        "cycle": "D",
        "items": ["010200000"],
        "unit": "%",
        "description": "국내 중단기 무위험 금리입니다. 회사채 발행금리와 은행 차입 조건의 기준점으로 씁니다.",
    },
    "국고채 10년": {
        "stat": "817Y002",
        "cycle": "D",
        "items": ["010210000"],
        "unit": "%",
        "description": "국내 장기금리입니다. 장기 성장률, 물가, 글로벌 금리 흐름을 함께 반영합니다.",
    },
    "회사채 AA- 3년": {
        "stat": "817Y002",
        "cycle": "D",
        "items": ["010300000"],
        "unit": "%",
        "description": "우량 회사채 조달금리입니다. 기업 자금조달 부담을 보는 핵심 지표입니다.",
    },
    "회사채 BBB- 3년": {
        "stat": "817Y002",
        "cycle": "D",
        "items": ["010320000"],
        "unit": "%",
        "description": "비우량 회사채 조달금리입니다. 자금시장 경색과 부도 위험의 선행 신호로 볼 수 있습니다.",
    },
    "KORIBOR 3개월": {
        "stat": "817Y002",
        "cycle": "D",
        "items": ["010150000"],
        "unit": "%",
        "description": "은행 간 단기자금 금리입니다. 은행 차입과 단기 유동성 여건을 보는 데 씁니다.",
    },
    "CD 91일": {
        "stat": "817Y002",
        "cycle": "D",
        "keywords": ["CD", "91"],
        "unit": "%",
        "description": "은행 양도성예금증서 금리입니다. 은행권 단기 조달비용과 변동금리 대출 기준금리의 압력을 봅니다.",
    },
    "CP 91일": {
        "stat": "817Y002",
        "cycle": "D",
        "keywords": ["CP", "91"],
        "unit": "%",
        "description": "기업어음 금리입니다. 기업 단기자금 조달 비용과 단기 신용경색 여부를 빠르게 보여줍니다.",
    },
    "KORIBOR 1개월": {
        "stat": "817Y002",
        "cycle": "D",
        "keywords": ["KORIBOR", "1개월"],
        "unit": "%",
        "description": "1개월 은행 간 단기자금 금리입니다. 초단기 원화 유동성 부담을 봅니다.",
    },
    "KORIBOR 6개월": {
        "stat": "817Y002",
        "cycle": "D",
        "keywords": ["KORIBOR", "6개월"],
        "unit": "%",
        "description": "6개월 은행 간 단기자금 금리입니다. 중단기 조달비용과 금리 기대를 함께 반영합니다.",
    },
    "원/달러": {
        "stat": "731Y001",
        "cycle": "D",
        "items": ["0000001"],
        "unit": "원",
        "description": "원화 기준 달러 환율입니다. 외화 결제, 차입, 환헤지 비용 판단의 가장 기본 축입니다.",
    },
    "원/엔": {
        "stat": "731Y001",
        "cycle": "D",
        "keywords": ["엔"],
        "unit": "원",
        "description": "엔화 대비 원화 환율입니다. 에너지, 설비, 일본 경쟁업종과 아시아 자금흐름을 볼 때 참고합니다.",
    },
    "원/위안": {
        "stat": "731Y001",
        "cycle": "D",
        "keywords": ["위안"],
        "unit": "원",
        "description": "위안화 대비 원화 환율입니다. 한국 수출 경기와 중국 경기 민감도를 함께 확인할 때 유용합니다.",
    },
}

FRED_SERIES = {
    "미국 기준금리": {
        "code": "FEDFUNDS",
        "unit": "%",
        "group": "정책금리",
        "transform": "level",
        "description": "미국 연방기금 실효금리입니다. 한국 기준금리와 비교해 한미 기준금리차 및 환헤지 비용 압력을 봅니다.",
    },
    "역레포 잔고": {
        "code": "RRPONTSYD",
        "unit": "십억 달러",
        "group": "유동성",
        "transform": "level",
        "description": "연준 역레포 잔고입니다. 단기자금이 연준에 머무는 규모로, 줄어들면 단기 유동성 완충력이 약해질 수 있습니다.",
    },
    "재무부 일반계정": {
        "code": "WTREGEN",
        "unit": "십억 달러",
        "group": "유동성",
        "transform": "level",
        "description": "미 재무부 일반계정(TGA)입니다. 잔고가 늘면 시중 유동성을 흡수하고, 줄면 유동성을 공급하는 효과가 있습니다.",
    },
    "연준 총자산 YoY": {
        "code": "WALCL",
        "unit": "YoY %",
        "group": "유동성",
        "transform": "yoy",
        "description": "연준 총자산의 전년 대비 변화율입니다. 양적긴축 또는 완화 속도를 직관적으로 보여줍니다.",
    },
    "연준 지급준비금": {
        "code": "WRESBAL",
        "unit": "십억 달러",
        "group": "유동성",
        "transform": "level",
        "description": "연준 지급준비금입니다. 은행 시스템 내부의 실제 유동성 체력을 보는 핵심 지표입니다.",
    },
    "SOFR": {
        "code": "SOFR",
        "unit": "%",
        "group": "유동성",
        "transform": "level",
        "description": "달러 하루짜리 담보 조달금리입니다. 글로벌 단기자금 조달 비용을 보는 데 씁니다.",
    },
    "대출태도지수": {
        "code": "DRTSCILM",
        "unit": "%",
        "group": "유동성",
        "transform": "level",
        "description": "은행 대출 문턱을 보여줍니다. 높아질수록 은행이 대출을 더 보수적으로 취급한다는 뜻입니다.",
    },
    "금융여건지수": {
        "code": "NFCI",
        "unit": "",
        "group": "유동성",
        "transform": "level",
        "description": "금융시장 스트레스와 긴축 정도를 종합한 지표입니다. 상승하면 금융여건이 타이트해졌다고 봅니다.",
    },
    "미국채 10년-2년": {
        "code": "T10Y2Y",
        "unit": "%p",
        "group": "채권/신용",
        "transform": "level",
        "description": "장단기 금리차입니다. 0%p 미만 역전은 경기 침체 선행 신호로 자주 해석됩니다.",
    },
    "미국채 10년-3개월": {
        "code": "T10Y3M",
        "unit": "%p",
        "group": "채권/신용",
        "transform": "level",
        "description": "10년물과 3개월물 금리차입니다. 경기 침체 선행 신호로 자주 참고됩니다.",
    },
    "미국 10년 실질금리": {
        "code": "DFII10",
        "unit": "%",
        "group": "채권/신용",
        "transform": "level",
        "description": "물가를 뺀 10년 실질금리입니다. 높을수록 금융환경이 제약적이고 성장주에는 부담입니다.",
    },
    "하이일드 스프레드": {
        "code": "BAMLH0A0HYM2",
        "unit": "%p",
        "group": "채권/신용",
        "transform": "level",
        "description": "위험 회사채와 국채의 금리차입니다. 급등하면 신용위험과 경기침체 우려가 커진 것입니다.",
    },
    "실업률": {
        "code": "UNRATE",
        "unit": "%",
        "group": "경기/물가",
        "transform": "level",
        "description": "미국 소비와 경기 사이클의 핵심 지표입니다. 최근 1년 저점 대비 0.5%p 이상 오르면 샴의 법칙 경고로 봅니다.",
    },
    "비농업 고용 증감": {
        "code": "PAYEMS",
        "unit": "천 명",
        "group": "경기/물가",
        "transform": "diff",
        "description": "미국 비농업 부문 취업자 수의 전월 대비 증감입니다. 고용이 유지되는지 보는 실업률의 짝 지표입니다.",
    },
    "CPI": {
        "code": "CPIAUCSL",
        "unit": "YoY %",
        "group": "경기/물가",
        "transform": "yoy",
        "description": "미국 소비자물가 상승률입니다. 연준의 금리 경로를 좌우하는 핵심 물가 지표입니다.",
    },
    "Core CPI": {
        "code": "CPILFESL",
        "unit": "YoY %",
        "group": "경기/물가",
        "transform": "yoy",
        "description": "식료품과 에너지를 제외한 근원 소비자물가입니다. 추세적인 물가 압력을 볼 때 중요합니다.",
    },
    "Core PCE": {
        "code": "PCEPILFE",
        "unit": "YoY %",
        "group": "경기/물가",
        "transform": "yoy",
        "description": "연준이 중시하는 근원 개인소비지출 물가입니다. 통화정책의 긴축 또는 완화 여지를 판단할 때 봅니다.",
    },
    "소매판매": {
        "code": "RSAFS",
        "unit": "MoM %",
        "group": "경기/물가",
        "transform": "mom",
        "description": "미국 소매판매의 전월 대비 변화율입니다. 미국 소비 모멘텀이 살아 있는지 확인하는 실물 지표입니다.",
    },
    "ISM 제조업": {
        "code": "NAPM",
        "unit": "",
        "group": "경기/물가",
        "transform": "level",
        "description": "ISM 제조업 구매관리자지수입니다. 50 이상은 확장, 50 미만은 위축으로 해석합니다.",
    },
    "무역가중 달러지수": {
        "code": "DTWEXBGS",
        "unit": "",
        "group": "환율/원자재",
        "transform": "level",
        "description": "미 달러의 광범위한 강약을 보여줍니다. 상승하면 글로벌 달러 유동성 압박이 커질 수 있습니다.",
    },
    "WTI": {
        "code": "DCOILWTICO",
        "unit": "달러",
        "group": "환율/원자재",
        "transform": "level",
        "description": "미국 서부텍사스산 원유 가격입니다. 에너지 비용과 물가 압력 판단에 씁니다.",
    },
    "천연가스": {
        "code": "DHHNGSP",
        "unit": "달러",
        "group": "환율/원자재",
        "transform": "level",
        "description": "Henry Hub 천연가스 가격입니다. 지역난방회사 관점에서 에너지 원가 부담을 볼 때 유용합니다.",
    },
}

MARKET_PROXY_SERIES = {
    "비트코인": {
        "symbol": "BTC-USD",
        "unit": "달러",
        "description": "글로벌 위험선호와 달러 유동성 심리를 빠르게 반영하는 보조 지표입니다.",
    },
    "금": {
        "symbol": "GC=F",
        "unit": "달러",
        "description": "안전자산 선호, 실질금리, 달러 흐름을 함께 보는 방어자산 지표입니다.",
    },
    "VIX": {
        "symbol": "^VIX",
        "unit": "",
        "description": "미국 주식시장 변동성 지수입니다. 급등하면 위험회피 심리가 커졌다고 봅니다.",
    },
    "S&P500": {
        "symbol": "^GSPC",
        "unit": "pt",
        "description": "미국 대형주 위험자산 흐름을 보는 대표 지수입니다.",
    },
    "나스닥": {
        "symbol": "^IXIC",
        "unit": "pt",
        "description": "성장주와 기술주 위험선호를 보는 대표 지수입니다.",
    },
}

RSS_FEEDS = {
    "부동산": "https://news.einfomax.co.kr/rss/S1N17.xml",
    "해외주식": "https://news.einfomax.co.kr/rss/S1N21.xml",
    "증권/기업": "https://news.einfomax.co.kr/rss/S1N7.xml",
    "정책/금융": "https://news.einfomax.co.kr/rss/S1N15.xml",
}

MARKET_GUIDE = {
    "자금담당자 관점": [
        "AA-와 BBB- 스프레드는 우량/비우량 조달 여건의 온도차를 보여줍니다.",
        "한미 기준금리차는 달러 조달, 환헤지 프리미엄, 스왑포인트 압력의 큰 방향을 보는 데 유용합니다.",
        "지급준비금, 역레포, TGA는 연준 총자산보다 더 가까운 단기 유동성 체감 지표입니다.",
    ],
    "프로 투자자 관점": [
        "10Y-2Y 역전, 샴의 법칙, 하이일드 스프레드는 위험자산 비중을 줄일 때 보는 핵심 경보입니다.",
        "비트코인, 금, VIX는 위험선호와 안전자산 선호가 동시에 어떻게 움직이는지 보는 보조 지표입니다.",
        "히트맵은 지수 상승이 특정 섹터 쏠림인지, 넓은 상승인지 빠르게 확인하는 보조 화면입니다.",
    ],
}


def _period_bounds(cycle: str) -> tuple[str, str]:
    if cycle == "D":
        return START_DAY, END_DAY
    return START_MONTH, END_MONTH


@st.cache_data(ttl=86400)
def fetch_ecos_item_rows(stat_code: str) -> list[dict]:
    if not ECOS_API_KEY:
        raise ValueError("ECOS_API_KEY가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 추가하세요.")

    rows: list[dict] = []
    page_size = 1000
    offset = 1

    while True:
        url = f"{ECOS_ITEM_BASE}/{offset}/{offset + page_size - 1}/{stat_code}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()

        if "StatisticItemList" not in payload:
            message = payload.get("RESULT", {}).get("MESSAGE", payload)
            raise ValueError(f"ECOS 항목 조회 오류 ({stat_code}): {message}")

        block = payload["StatisticItemList"]
        batch = block.get("row", [])
        if isinstance(batch, dict):
            batch = [batch]
        rows.extend(batch)

        total = int(block.get("list_total_count", len(rows)))
        if offset + page_size - 1 >= total:
            break
        offset += page_size

    return rows


def resolve_ecos_item_codes(stat_code: str, keywords: list[str], fallback_items: list[str] | None = None) -> list[str]:
    normalized_keywords = [keyword.lower().replace(" ", "") for keyword in keywords if keyword]
    if not normalized_keywords:
        if fallback_items:
            return fallback_items
        raise ValueError(f"{stat_code} 항목 키워드가 없습니다.")

    rows = fetch_ecos_item_rows(stat_code)
    for row in rows:
        haystack = " ".join(str(value) for value in row.values() if value is not None)
        normalized_haystack = haystack.lower().replace(" ", "")
        if all(keyword in normalized_haystack for keyword in normalized_keywords):
            for key in ("ITEM_CODE", "ITEM_CODE1", "ITEM_CODE2", "ITEM_CODE3", "ITEM_CODE4"):
                value = str(row.get(key, "")).strip()
                if value:
                    return [value]

    if fallback_items:
        return fallback_items
    raise ValueError(f"ECOS {stat_code}에서 항목을 찾지 못했습니다: {', '.join(keywords)}")


def fetch_ecos_rows(
    stat_code: str,
    cycle: str,
    item_codes: list[str],
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    if not ECOS_API_KEY:
        raise ValueError("ECOS_API_KEY가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 추가하세요.")

    start = start or _period_bounds(cycle)[0]
    end = end or _period_bounds(cycle)[1]
    item_path = "/".join(item_codes)
    rows: list[dict] = []
    page_size = 1000
    offset = 1

    while True:
        url = (
            f"{ECOS_BASE}/{offset}/{offset + page_size - 1}/"
            f"{stat_code}/{cycle}/{start}/{end}/{item_path}"
        )
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        payload = response.json()

        if "StatisticSearch" not in payload:
            message = payload.get("RESULT", {}).get("MESSAGE", payload)
            raise ValueError(f"ECOS API 오류 ({stat_code}): {message}")

        block = payload["StatisticSearch"]
        batch = block.get("row", [])
        if isinstance(batch, dict):
            batch = [batch]
        rows.extend(batch)

        total = int(block.get("list_total_count", len(rows)))
        if offset + page_size - 1 >= total:
            break
        offset += page_size

    return rows


def rows_to_series(rows: list[dict], cycle: str) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows)
    df["value"] = pd.to_numeric(df["DATA_VALUE"], errors="coerce")
    if cycle == "M":
        df["date"] = pd.to_datetime(df["TIME"].astype(str), format="%Y%m", errors="coerce")
    else:
        df["date"] = pd.to_datetime(df["TIME"].astype(str), format="%Y%m%d", errors="coerce")

    series = df.dropna(subset=["date"]).set_index("date")["value"].sort_index()
    return series[~series.index.duplicated(keep="last")].dropna()


def fred_to_monthly_series(series_id: str | list[str]) -> pd.Series:
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY가 설정되어 있지 않습니다. Streamlit secrets 또는 환경변수에 추가하세요.")

    if isinstance(series_id, list):
        last_error: Exception | None = None
        for candidate in series_id:
            try:
                return fred_to_monthly_series(candidate)
            except Exception as error:
                last_error = error
        if last_error is not None:
            raise last_error
        return pd.Series(dtype=float)

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": FRED_START,
    }
    response = requests.get(FRED_OBSERVATIONS_URL, params=params, timeout=30)
    response.raise_for_status()
    observations = response.json().get("observations", [])

    if not observations:
        return pd.Series(dtype=float)

    df = pd.DataFrame(observations)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    series = df.dropna(subset=["date"]).set_index("date")["value"].sort_index()
    return series.resample("ME").last().dropna()


def transform_fred_series(series: pd.Series, transform: str) -> pd.Series:
    if transform == "yoy":
        return series.pct_change(12) * 100
    if transform == "mom":
        return series.pct_change() * 100
    if transform == "diff":
        return series.diff()
    return series


@st.cache_data(ttl=3600)
def fetch_domestic_rates() -> pd.DataFrame:
    ECOS_FETCH_ERRORS.clear()
    daily_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []

    for label, spec in DOMESTIC_SERIES.items():
        try:
            item_codes = spec.get("items") or resolve_ecos_item_codes(
                spec["stat"],
                spec.get("keywords", []),
                spec.get("fallback_items"),
            )
            rows = fetch_ecos_rows(spec["stat"], spec["cycle"], item_codes)
            series = rows_to_series(rows, spec["cycle"]).rename(label)
        except Exception as error:
            ECOS_FETCH_ERRORS[label] = str(error)
            continue

        if spec["cycle"] == "D":
            daily_frames.append(series.to_frame())
        else:
            monthly_frames.append(series.to_frame())

    daily = pd.concat(daily_frames, axis=1).sort_index() if daily_frames else pd.DataFrame()
    if daily.empty:
        return daily

    market_index = daily.index
    merged = daily.copy()

    for frame in monthly_frames:
        monthly_series = frame.iloc[:, 0]
        aligned = monthly_series.reindex(market_index.union(monthly_series.index)).sort_index().ffill()
        merged[monthly_series.name] = aligned.reindex(market_index)

    ordered_cols = [name for name in DOMESTIC_SERIES if name in merged.columns]
    merged = merged[ordered_cols].ffill()

    if {"회사채 AA- 3년", "국고채 3년"}.issubset(merged.columns):
        merged["AA- vs 국고채 스프레드"] = merged["회사채 AA- 3년"] - merged["국고채 3년"]
    if {"회사채 BBB- 3년", "회사채 AA- 3년"}.issubset(merged.columns):
        merged["BBB- vs AA- 스프레드"] = merged["회사채 BBB- 3년"] - merged["회사채 AA- 3년"]
    if {"CP 91일", "CD 91일"}.issubset(merged.columns):
        merged["CP-CD 스프레드"] = merged["CP 91일"] - merged["CD 91일"]
    if {"KORIBOR 3개월", "기준금리"}.issubset(merged.columns):
        merged["KORIBOR-기준금리 스프레드"] = merged["KORIBOR 3개월"] - merged["기준금리"]
    if "원/달러" in merged.columns:
        merged["원/달러 1개월 변화율"] = merged["원/달러"].pct_change(20) * 100
        merged["원/달러 20일 변동성"] = merged["원/달러"].pct_change().rolling(20).std() * (252 ** 0.5) * 100

    return merged.dropna(how="all")


def yahoo_chart_to_series(symbol: str) -> pd.Series:
    params = {
        "range": "10y",
        "interval": "1d",
        "includePrePost": "false",
        "events": "history",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(YAHOO_CHART_URL.format(symbol=symbol), params=params, headers=headers, timeout=20)
    response.raise_for_status()
    result = response.json().get("chart", {}).get("result", [])
    if not result:
        return pd.Series(dtype=float)

    block = result[0]
    timestamps = block.get("timestamp", [])
    close = block.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    if not timestamps or not close:
        return pd.Series(dtype=float)

    series = pd.Series(close, index=pd.to_datetime(timestamps, unit="s"), dtype="float64")
    series = series.dropna().sort_index()
    series.index = series.index.normalize()
    return series[~series.index.duplicated(keep="last")]


def _fetch_one_market_proxy(label_and_spec: tuple[str, dict]) -> tuple[str, pd.Series | None]:
    label, spec = label_and_spec
    try:
        series = yahoo_chart_to_series(spec["symbol"])
        return label, series.rename(label)
    except Exception as error:
        MARKET_PROXY_ERRORS[label] = str(error)
        return label, None


@st.cache_data(ttl=900)
def fetch_market_proxy_data() -> pd.DataFrame:
    MARKET_PROXY_ERRORS.clear()
    frames: list[pd.DataFrame] = []
    items = list(MARKET_PROXY_SERIES.items())
    max_workers = min(6, len(items))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_one_market_proxy, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            label, series = future.result()
            if series is not None and not series.empty:
                frames.append(series.to_frame())

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, axis=1).sort_index().ffill()
    for name in [col for col in merged.columns if col != "VIX"]:
        merged[f"{name} 1개월 변화율"] = merged[name].pct_change(20) * 100
    return merged.dropna(how="all")


def _fetch_one_fred(label_and_spec: tuple[str, dict]) -> tuple[str, pd.Series | None]:
    label, spec = label_and_spec
    try:
        series = fred_to_monthly_series(spec["code"])
        series = transform_fred_series(series, spec.get("transform", "level"))
        return label, series.rename(label)
    except Exception as error:
        FRED_FETCH_ERRORS[label] = str(error)
        return label, None


@st.cache_data(ttl=3600)
def fetch_fred_macro_data() -> pd.DataFrame:
    FRED_FETCH_ERRORS.clear()
    frames: list[pd.DataFrame] = []
    items = list(FRED_SERIES.items())
    max_workers = min(12, len(items))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_one_fred, item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            label, series = future.result()
            if series is not None and not series.dropna().empty:
                frames.append(series.to_frame())

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, axis=1).sort_index()
    if "실업률" in merged.columns:
        unemployment = merged["실업률"].dropna()
        unemployment_3m = unemployment.rolling(3).mean()
        trailing_low = unemployment_3m.rolling(12, min_periods=3).min()
        merged["샴룰 갭"] = unemployment_3m - trailing_low

    return merged.dropna(how="all")


@st.cache_data(ttl=900)
def fetch_rss_news(feed_url: str) -> list[dict]:
    feed = feedparser.parse(feed_url)
    articles: list[dict] = []

    if getattr(feed, "bozo", False) and getattr(feed, "bozo_exception", None):
        raise ValueError(feed.bozo_exception)

    for entry in feed.entries:
        published = entry.get("published", "")
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")

        summary = html.unescape(re.sub(r"<[^>]+>", "", entry.get("summary", ""))).strip()
        title = html.unescape(entry.get("title", "제목 없음")).strip()
        articles.append(
            {
                "title": title,
                "link": entry.get("link", ""),
                "published": published,
                "summary": summary,
            }
        )

    return articles


def build_cross_market_indicators(domestic: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    if "기준금리" in domestic.columns:
        frames.append(domestic[["기준금리"]].rename(columns={"기준금리": "한국 기준금리"}))

    if "미국 기준금리" in macro.columns:
        us_policy = macro[["미국 기준금리"]]
        if not domestic.empty:
            target_index = domestic.index.union(us_policy.index)
            us_policy = us_policy.reindex(target_index).sort_index().ffill().reindex(domestic.index)
        frames.append(us_policy)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, axis=1).sort_index().ffill()
    if {"한국 기준금리", "미국 기준금리"}.issubset(merged.columns):
        merged["한-미 기준금리차"] = merged["한국 기준금리"] - merged["미국 기준금리"]
    return merged.dropna(how="all")


def latest_delta(series: pd.Series, periods: int = 1) -> tuple[float, float | None]:
    clean = series.dropna()
    latest = clean.iloc[-1]
    previous = clean.iloc[-1 - periods] if len(clean) > periods else None
    return latest, None if previous is None else latest - previous


def latest_value(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns or frame[column].dropna().empty:
        return None
    return float(frame[column].dropna().iloc[-1])


def format_value(value: float | None, unit: str = "", digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    suffix = f" {unit}" if unit and unit not in {"%", "%p"} else unit
    return f"{value:,.{digits}f}{suffix}"


def format_dataframe(frame: pd.DataFrame, date_format: str = "%Y-%m-%d") -> pd.DataFrame:
    display_df = frame.copy()
    display_df.index = display_df.index.strftime(date_format)
    display_df.index.name = "date"
    return display_df.round(4).reset_index()


def normalize_to_100(frame: pd.DataFrame) -> pd.DataFrame:
    clean = frame.dropna(how="all").ffill()
    if clean.empty:
        return clean
    base = clean.apply(lambda series: series.dropna().iloc[0] if not series.dropna().empty else float("nan"))
    normalized = clean.divide(base).multiply(100)
    return normalized.dropna(how="all")


def signal_from_value(value: float | None, warning: float, danger: float, higher_is_risk: bool = True) -> tuple[str, str]:
    if value is None or pd.isna(value):
        return "확인 필요", "gray"
    if higher_is_risk:
        if value >= danger:
            return "위험", "red"
        if value >= warning:
            return "주의", "orange"
    else:
        if value <= danger:
            return "위험", "red"
        if value <= warning:
            return "주의", "orange"
    return "안정", "green"


def render_signal_card(title: str, value: str, signal: str, note: str, color: str) -> None:
    st.markdown(
        f"""
        <div style="border:1px solid #e6e8eb;border-radius:8px;padding:14px 16px;background:#ffffff;height:154px">
            <div style="font-size:0.86rem;color:#606975;margin-bottom:6px">{title}</div>
            <div style="font-size:1.45rem;font-weight:700;color:#111827">{value}</div>
            <div style="display:inline-block;margin:8px 0;padding:3px 9px;border-radius:999px;background:{color};color:white;font-size:0.78rem">{signal}</div>
            <div style="font-size:0.82rem;color:#4b5563;line-height:1.35">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sahm_rule_warning(df: pd.DataFrame) -> None:
    if "샴룰 갭" in df.columns:
        sahm_gap = df["샴룰 갭"].dropna()
        if not sahm_gap.empty and sahm_gap.iloc[-1] >= 0.5:
            st.error(f"샴의 법칙 경기침체 경고: 샴룰 갭이 {sahm_gap.iloc[-1]:.2f}%p로 0.5%p 기준을 넘었습니다.")

    if "미국채 10년-2년" in df.columns:
        curve = df["미국채 10년-2년"].dropna()
        if not curve.empty and curve.iloc[-1] < 0:
            st.warning("⚠️ 미국채 10Y-2Y 장단기 금리차 역전 상태 지속 중 (경기 침체 선행 신호 위험)")


def render_market_summary(domestic: pd.DataFrame, macro: pd.DataFrame, cross: pd.DataFrame) -> None:
    st.markdown("### 오늘의 자금시장 신호")
    render_sahm_rule_warning(macro)

    cols = st.columns(6)
    cp_cd_spread = latest_value(domestic, "CP-CD 스프레드")
    bbb_aa_spread = latest_value(domestic, "BBB- vs AA- 스프레드")
    hy_spread = latest_value(macro, "하이일드 스프레드")
    curve_10y2y = latest_value(macro, "미국채 10년-2년")
    han_us_gap = latest_value(cross, "한-미 기준금리차")
    usdkrw_mom = latest_value(domestic, "원/달러 1개월 변화율")

    cp_cd_signal, cp_cd_color = signal_from_value(cp_cd_spread, 0.4, 0.8)
    bbb_signal, bbb_color = signal_from_value(bbb_aa_spread, 4.5, 6.0)
    hy_signal, hy_color = signal_from_value(hy_spread, 4.5, 6.0)
    curve_signal, curve_color = signal_from_value(curve_10y2y, 0.0, -0.5, higher_is_risk=False)
    gap_signal, gap_color = signal_from_value(han_us_gap, -1.0, -2.0, higher_is_risk=False)
    usdkrw_signal, usdkrw_color = signal_from_value(abs(usdkrw_mom) if pd.notna(usdkrw_mom) else float("nan"), 3.0, 6.0)

    with cols[0]:
        render_signal_card("CP-CD 스프레드", format_value(cp_cd_spread, "%p"), cp_cd_signal, "기업 단기자금 경색 신호", cp_cd_color)
    with cols[1]:
        render_signal_card("BBB- vs AA-", format_value(bbb_aa_spread, "%p"), bbb_signal, "비우량 자금시장 경색 신호", bbb_color)
    with cols[2]:
        render_signal_card("미국 신용위험", format_value(hy_spread, "%p"), hy_signal, "하이일드 스프레드 기준", hy_color)
    with cols[3]:
        render_signal_card("10Y-2Y 금리차", format_value(curve_10y2y, "%p"), curve_signal, "역전 시 경기침체 선행 신호", curve_color)
    with cols[4]:
        render_signal_card("한-미 기준금리차", format_value(han_us_gap, "%p"), gap_signal, "환헤지 비용과 달러 조달 압력", gap_color)
    with cols[5]:
        render_signal_card("원/달러 1개월", format_value(usdkrw_mom, "%"), usdkrw_signal, "외화 결제와 환헤지 변동성", usdkrw_color)


def render_indicator_notes(specs: dict[str, dict], title: str) -> None:
    with st.expander(title, expanded=False):
        for name, spec in specs.items():
            st.markdown(f"**{name}**: {spec.get('description', '')}")


def render_market_guide() -> None:
    with st.expander("대시보드 읽는 법", expanded=False):
        cols = st.columns(2)
        for col, (title, notes) in zip(cols, MARKET_GUIDE.items()):
            with col:
                st.markdown(f"**{title}**")
                for note in notes:
                    st.markdown(f"- {note}")


def render_data_source_diagnostics() -> None:
    with st.expander("데이터 연결 진단", expanded=False):
        st.write(
            {
                "ECOS_API_KEY loaded": bool(ECOS_API_KEY),
                "FRED_API_KEY loaded": bool(FRED_API_KEY),
                "ECOS key length": len(ECOS_API_KEY or ""),
                "FRED key length": len(FRED_API_KEY or ""),
            }
        )
        if ECOS_FETCH_ERRORS:
            st.markdown("**ECOS 수집 실패**")
            for label, error in ECOS_FETCH_ERRORS.items():
                st.write(f"{label}: {error}")
        if FRED_FETCH_ERRORS:
            st.markdown("**FRED 수집 실패**")
            for label, error in FRED_FETCH_ERRORS.items():
                st.write(f"{label}: {error}")
        if MARKET_PROXY_ERRORS:
            st.markdown("**시장 보조지표 수집 실패**")
            for label, error in MARKET_PROXY_ERRORS.items():
                st.write(f"{label}: {error}")
        if not ECOS_FETCH_ERRORS and not FRED_FETCH_ERRORS and not MARKET_PROXY_ERRORS:
            st.caption("현재 세션에서 기록된 API 오류가 없습니다.")


def render_metric_row(frame: pd.DataFrame, specs: dict[str, dict], columns: list[str]) -> None:
    visible = [name for name in columns if name in frame.columns]
    if not visible:
        return

    cols = st.columns(len(visible))
    for col, name in zip(cols, visible):
        spec = specs.get(name, {"unit": ""})
        if frame[name].dropna().empty:
            col.metric(name, "-")
            continue

        latest, delta = latest_delta(frame[name])
        unit = spec.get("unit", "")
        delta_unit = "p" if unit in {"%", "%p"} else f" {unit}" if unit else ""
        col.metric(
            name,
            format_value(latest, unit),
            delta=None if delta is None else f"{delta:+,.2f}{delta_unit}",
        )


def tradingview_widget(script_name: str, config: dict, height: int) -> None:
    widget_config = dict(config)
    widget_config["width"] = "100%"
    widget_config["height"] = height
    config_json = json.dumps(widget_config, ensure_ascii=False)
    html_block = f"""
    <div class="tradingview-widget-container" style="height:{height + 34}px;width:100%;overflow:hidden">
      <div class="tradingview-widget-container__widget" style="height:{height}px;width:100%"></div>
      <div class="tradingview-widget-copyright" style="height:24px;text-align:center">
        <a href="https://www.tradingview.com/" rel="noopener nofollow" target="_blank">
          <span class="blue-text">Track all markets on TradingView</span>
        </a>
      </div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/{script_name}" async>
      {config_json}
      </script>
    </div>
    """
    components.html(html_block, height=height + 40, scrolling=False)


def render_tradingview_widgets(lightweight: bool = True) -> None:
    st.markdown("### 글로벌 시장 히트맵")
    st.caption("무료 공식 TradingView 위젯입니다. 데이터는 외부 위젯에서 직접 제공되며 앱 내부 계산에는 쓰지 않습니다.")

    if lightweight:
        st.info("모바일/공유용 경량 모드에서는 외부 위젯을 앱 안에 직접 띄우지 않습니다. 아래 버튼으로 새 창에서 여는 편이 안정적입니다.")
        st.link_button("TradingView 히트맵 새 창", "https://www.tradingview.com/heatmap/stock/")
        return

    if not st.checkbox("TradingView 외부 위젯 불러오기", value=False):
        st.info("외부 위젯은 브라우저 렌더링 부담이 커서 기본으로 꺼두었습니다. 필요할 때만 체크해서 불러오세요.")
        st.link_button("TradingView 히트맵 새 창", "https://www.tradingview.com/heatmap/stock/")
        return

    st.markdown("#### 미국 주식 히트맵")
    tradingview_widget(
        "embed-widget-stock-heatmap.js",
        {
            "exchanges": [],
            "dataSource": "SPX500",
            "grouping": "sector",
            "blockSize": "market_cap_basic",
            "blockColor": "change",
            "locale": "kr",
            "symbolUrl": "",
            "colorTheme": "light",
            "hasTopBar": True,
            "isDataSetEnabled": True,
            "isZoomEnabled": True,
            "hasSymbolTooltip": True,
        },
        760,
    )


def render_domestic_section(df: pd.DataFrame, lightweight: bool = True) -> None:
    st.markdown("### 국내 자금시장")
    st.caption(f"한국은행 ECOS | {START_DAY[:4]}년 이후 | 시장금리는 일간 기준")

    if df.empty:
        st.warning("국내 금리 데이터를 불러오지 못했습니다. 네트워크 권한 또는 ECOS 응답을 확인하세요.")
        return

    metric_cols = ["기준금리", "국고채 3년", "회사채 AA- 3년", "CD 91일", "CP 91일", "원/달러"]
    render_metric_row(df, DOMESTIC_SERIES, metric_cols)

    min_date = df.index.min().date()
    max_date = df.index.max().date()
    default_years = 2 if lightweight else 3
    default_start = max(min_date, (pd.Timestamp(max_date) - pd.DateOffset(years=default_years)).date())
    if lightweight:
        start_date, end_date = default_start, max_date
        st.caption("경량 모드: 국내 차트는 최근 2년 기준")
    else:
        start_date, end_date = st.date_input(
            "국내 자금시장 조회 기간",
            value=(default_start, max_date),
            min_value=min_date,
            max_value=max_date,
        )
    filtered = df.loc[pd.to_datetime(start_date) : pd.to_datetime(end_date)]

    chart_col, spread_col = st.columns([2, 1])
    with chart_col:
        st.markdown("#### 국채/회사채 금리")
        rate_cols = [col for col in ["기준금리", "국고채 3년", "국고채 10년", "회사채 AA- 3년", "회사채 BBB- 3년"] if col in filtered.columns]
        if rate_cols:
            st.line_chart(filtered[rate_cols], width="stretch")
        else:
            st.info("표시할 국내 금리 데이터가 없습니다.")

    with spread_col:
        st.markdown("#### 조달 스프레드")
        spread_cols = [col for col in ["AA- vs 국고채 스프레드", "BBB- vs AA- 스프레드"] if col in filtered.columns]
        if spread_cols:
            st.line_chart(filtered[spread_cols], width="stretch")
        st.markdown(
            "AA- 스프레드는 우량기업 조달 여건, BBB- vs AA- 스프레드는 비우량 기업의 자금 가뭄과 부도위험 선행 신호로 봅니다."
        )

    money_col, fx_col = st.columns(2)
    with money_col:
        st.markdown("#### 단기자금시장")
        money_cols = [
            col
            for col in ["CD 91일", "CP 91일", "KORIBOR 1개월", "KORIBOR 3개월", "KORIBOR 6개월"]
            if col in filtered.columns
        ]
        if money_cols:
            st.line_chart(filtered[money_cols], width="stretch")
        else:
            st.info("CD, CP, KORIBOR 등 단기자금시장 데이터가 아직 연결되지 않았습니다.")

        short_spread_cols = [col for col in ["CP-CD 스프레드", "KORIBOR-기준금리 스프레드"] if col in filtered.columns]
        if short_spread_cols and not lightweight:
            st.line_chart(filtered[short_spread_cols], width="stretch")
        st.caption("CP-CD 스프레드가 벌어지면 기업 단기 차입 부담이 CD보다 빠르게 높아진다는 뜻입니다.")

    with fx_col:
        st.markdown("#### 외환/환헤지")
        fx_cols = [col for col in ["원/달러", "원/엔", "원/위안"] if col in filtered.columns]
        if fx_cols:
            st.line_chart(filtered[fx_cols], width="stretch")
        else:
            st.info("환율 데이터가 아직 연결되지 않았습니다.")

        fx_risk_cols = [col for col in ["원/달러 1개월 변화율", "원/달러 20일 변동성"] if col in filtered.columns]
        if fx_risk_cols and not lightweight:
            st.line_chart(filtered[fx_risk_cols], width="stretch")
        st.caption("원/달러 상승은 외화 결제 부담과 환헤지 비용 점검 필요성을 키웁니다.")

    if not lightweight:
        with st.expander("최근 일별 국내 금리 데이터", expanded=False):
            display_cols = [
                col
                for col in metric_cols
                + [
                    "KORIBOR 1개월",
                    "KORIBOR 3개월",
                    "KORIBOR 6개월",
                    "원/엔",
                    "원/위안",
                    "AA- vs 국고채 스프레드",
                    "BBB- vs AA- 스프레드",
                    "CP-CD 스프레드",
                    "KORIBOR-기준금리 스프레드",
                    "원/달러 1개월 변화율",
                    "원/달러 20일 변동성",
                ]
                if col in df.columns
            ]
            recent_df = format_dataframe(df[display_cols].tail(120).sort_index(ascending=False))
            st.dataframe(recent_df, width="stretch", hide_index=True)

    render_indicator_notes(DOMESTIC_SERIES, "국내 지표 설명")


def render_cross_market_section(cross: pd.DataFrame) -> None:
    st.markdown("### 달러 유동성 및 환헤지 비용")
    st.caption("한국 기준금리와 미국 기준금리를 맞춰 계산한 한-미 기준금리차입니다.")

    if cross.empty or "한-미 기준금리차" not in cross.columns:
        st.info("한-미 기준금리차를 계산할 데이터가 부족합니다.")
        return

    cols = [col for col in ["한국 기준금리", "미국 기준금리", "한-미 기준금리차"] if col in cross.columns]
    st.line_chart(cross[cols], width="stretch")
    latest_gap = cross["한-미 기준금리차"].dropna().iloc[-1]
    st.markdown(
        f"현재 한-미 기준금리차는 **{latest_gap:.2f}%p**입니다. "
        "한국 금리가 미국보다 낮아질수록 외화 조달과 환헤지 비용 부담이 커질 수 있습니다."
    )


def render_macro_signal_cards(df: pd.DataFrame) -> None:
    st.markdown("#### 미국 매크로 핵심 신호")

    sahm_gap = latest_value(df, "샴룰 갭")
    core_cpi = latest_value(df, "Core CPI")
    ism = latest_value(df, "ISM 제조업")

    sahm_signal, sahm_color = signal_from_value(sahm_gap, 0.3, 0.5)
    cpi_signal, cpi_color = signal_from_value(core_cpi, 3.0, 4.0)
    ism_signal, ism_color = signal_from_value(ism, 50.0, 47.0, higher_is_risk=False)

    cols = st.columns(3)
    with cols[0]:
        render_signal_card("샴의 법칙", format_value(sahm_gap, "%p"), sahm_signal, "0.5%p 이상이면 침체 경고", sahm_color)
    with cols[1]:
        render_signal_card("Core CPI", format_value(core_cpi, "%"), cpi_signal, "물가가 높을수록 금리 인하 여지 축소", cpi_color)
    with cols[2]:
        render_signal_card("ISM 제조업", format_value(ism, ""), ism_signal, "50 이상 확장, 50 미만 위축", ism_color)


def render_macro_section(df: pd.DataFrame, lightweight: bool = True) -> None:
    st.markdown("### 미국/글로벌 매크로")
    st.caption("FRED | 병렬 호출 | 유동성, 채권/신용, 경기/물가, 환율/원자재")

    if df.empty:
        st.warning("미국/글로벌 매크로 데이터를 불러오지 못했습니다. 네트워크 권한 또는 FRED 응답을 확인하세요.")
        return

    render_macro_signal_cards(df)
    important = ["실업률", "비농업 고용 증감", "CPI", "Core CPI", "소매판매", "ISM 제조업"]
    extra_specs = FRED_SERIES | {"샴룰 갭": {"unit": "%p"}}
    render_metric_row(df, extra_specs, [name for name in important if name in df.columns])

    groups = {
        "유동성": [name for name, spec in FRED_SERIES.items() if spec["group"] == "유동성"],
        "채권/신용": [name for name, spec in FRED_SERIES.items() if spec["group"] == "채권/신용"],
        "경기/물가": [name for name, spec in FRED_SERIES.items() if spec["group"] == "경기/물가"],
        "환율/원자재": [name for name, spec in FRED_SERIES.items() if spec["group"] == "환율/원자재"],
    }
    if lightweight:
        groups = {
            "고용/물가": [name for name in ["실업률", "샴룰 갭", "Core CPI", "소매판매"] if name in df.columns],
            "채권/신용": [name for name in ["미국채 10년-2년", "하이일드 스프레드"] if name in df.columns],
        }

    for row_start in range(0, len(groups), 2):
        cols = st.columns(2)
        for col, (title, names) in zip(cols, list(groups.items())[row_start : row_start + 2]):
            with col:
                st.markdown(f"#### {title}")
                visible_cols = [name for name in names if name in df.columns]
                if visible_cols:
                    st.line_chart(df[visible_cols], width="stretch")

    if FRED_FETCH_ERRORS:
        with st.expander("FRED 수집 실패 진단", expanded=False):
            for label, error in FRED_FETCH_ERRORS.items():
                st.write(f"{label}: {error}")

    if not lightweight:
        with st.expander("월별 미국/글로벌 매크로 데이터", expanded=False):
            display_df = format_dataframe(df, "%Y-%m")
            st.dataframe(display_df.sort_values("date", ascending=False), width="stretch", hide_index=True)

    derived_specs = {
        "샴룰 갭": {
            "description": "최근 3개월 평균 실업률이 최근 1년 저점보다 얼마나 높아졌는지 보는 경기침체 경고 지표입니다. 0.5%p 이상이면 침체 경고로 봅니다."
        }
    }
    render_indicator_notes(FRED_SERIES | derived_specs, "미국/글로벌 지표 설명")


def render_market_proxy_section(df: pd.DataFrame, lightweight: bool = True) -> None:
    st.markdown("### 시장 보조지표")
    st.caption("무료 Yahoo Finance 가격 데이터 | 코인, 금, 변동성, 미국 주가지수")

    if df.empty:
        st.info("시장 보조지표를 불러오지 못했습니다. 이 섹션은 보조 데이터라 메인 판단에는 영향을 주지 않습니다.")
        if MARKET_PROXY_ERRORS:
            with st.expander("시장 보조지표 수집 실패 진단", expanded=False):
                for label, error in MARKET_PROXY_ERRORS.items():
                    st.write(f"{label}: {error}")
        return

    metric_cols = [name for name in ["비트코인", "금", "VIX", "S&P500", "나스닥"] if name in df.columns]
    render_metric_row(df, MARKET_PROXY_SERIES, metric_cols)

    if lightweight:
        visible = df.tail(756)
        st.caption("경량 모드: 보조지표는 최근 약 3년만 표시합니다.")
    else:
        lookback_label = st.radio(
            "시장 보조지표 표시 기간",
            ["1년", "3년", "5년", "전체"],
            index=2,
            horizontal=True,
        )
        lookback_days = {"1년": 252, "3년": 756, "5년": 1260}
        visible = df if lookback_label == "전체" else df.tail(lookback_days[lookback_label])
    price_cols = [col for col in ["비트코인", "금", "VIX"] if col in visible.columns]
    equity_cols = [col for col in ["S&P500", "나스닥"] if col in visible.columns]
    change_cols = [col for col in ["비트코인 1개월 변화율", "금 1개월 변화율", "S&P500 1개월 변화율", "나스닥 1개월 변화율"] if col in visible.columns]

    price_col, change_col = st.columns(2)
    with price_col:
        st.markdown("#### 위험선호/안전자산")
        if price_cols:
            normalized_prices = normalize_to_100(visible[price_cols])
            st.line_chart(normalized_prices, width="stretch")
            st.caption("가격 단위 차이가 커서 최근 구간 첫날을 100으로 맞춰 비교합니다.")
        if equity_cols and not lightweight:
            st.markdown("#### 미국 주가지수")
            st.line_chart(normalize_to_100(visible[equity_cols]), width="stretch")
    with change_col:
        st.markdown("#### 1개월 변화율")
        if change_cols:
            st.line_chart(visible[change_cols], width="stretch")
        st.caption("비트코인과 주식이 같이 강하고 VIX가 낮으면 위험선호, 금과 VIX가 같이 강하면 방어 심리로 봅니다.")

    render_indicator_notes(MARKET_PROXY_SERIES, "시장 보조지표 설명")


def render_news_card(article: dict) -> None:
    with st.container(border=True):
        title = article["title"]
        link = article["link"]
        if link:
            st.markdown(f"**[{title}]({link})**")
        else:
            st.markdown(f"**{title}**")

        if article["published"]:
            st.caption(article["published"])
        if article["summary"]:
            preview = article["summary"][:180]
            st.write(preview + ("..." if len(article["summary"]) > 180 else ""))


def render_dashboard_tab() -> None:
    lightweight = st.sidebar.toggle("모바일/공유용 경량 모드", value=True)
    load_market_proxy = st.sidebar.checkbox("코인/금 보조지표 불러오기", value=not lightweight)
    if lightweight:
        st.caption("경량 모드가 켜져 있어 외부 위젯, 보조 시세, 큰 표, 일부 장기 차트 렌더링을 줄입니다.")

    domestic = fetch_domestic_rates()
    macro = fetch_fred_macro_data()
    market_proxy = fetch_market_proxy_data() if load_market_proxy else pd.DataFrame()
    cross = build_cross_market_indicators(domestic, macro)

    render_market_guide()
    render_data_source_diagnostics()
    render_market_summary(domestic, macro, cross)
    st.divider()
    render_domestic_section(domestic, lightweight=lightweight)
    st.divider()
    render_cross_market_section(cross)
    st.divider()
    render_macro_section(macro, lightweight=lightweight)
    if load_market_proxy:
        st.divider()
        render_market_proxy_section(market_proxy, lightweight=lightweight)
    st.divider()
    render_tradingview_widgets(lightweight=lightweight)


def render_news_calendar_tab() -> None:
    st.subheader("뉴스/캘린더")
    st.caption("연합인포맥스 RSS와 TradingView 경제 캘린더")

    st.markdown("### 연합인포맥스 실시간 뉴스")
    feed_items = list(RSS_FEEDS.items())
    for row_start in range(0, len(feed_items), 2):
        cols = st.columns(2)
        for col, (category, feed_url) in zip(cols, feed_items[row_start : row_start + 2]):
            with col:
                st.markdown(f"#### {category}")
                with st.container(height=500):
                    try:
                        articles = fetch_rss_news(feed_url)
                        if not articles:
                            st.info("표시할 기사가 없습니다.")
                            continue
                        for article in articles:
                            render_news_card(article)
                    except Exception as error:
                        st.error(f"{category} 뉴스를 불러오지 못했습니다: {error}")

    st.markdown("### 경제 캘린더")
    if st.checkbox("TradingView 경제 캘린더 불러오기", value=False):
        tradingview_widget(
            "embed-widget-events.js",
            {
                "colorTheme": "light",
                "isTransparent": False,
                "locale": "kr",
                "importanceFilter": "-1,0,1",
                "countryFilter": "us,kr,cn,jp,eu",
            },
            520,
        )
    else:
        st.info("경제 캘린더는 외부 위젯이라 필요할 때만 불러오도록 꺼두었습니다.")

    st.markdown("### 외부 자료 바로가기")
    link_cols = st.columns(2)
    link_cols[0].link_button("TradingView 히트맵", "https://www.tradingview.com/heatmap/stock/")
    link_cols[1].link_button("FRED 데이터", "https://fred.stlouisfed.org/")


def main() -> None:
    st.set_page_config(
        page_title="글로벌 자금 대시보드",
        page_icon="📈",
        layout="wide",
    )

    st.title("글로벌 자금 대시보드")
    st.caption("자금담당자와 글로벌 매크로 투자자를 위한 무료 데이터 기반 시장 상황판")

    tab_dashboard, tab_news = st.tabs(["시장 대시보드", "뉴스/캘린더"])

    with tab_dashboard:
        render_dashboard_tab()

    with tab_news:
        render_news_calendar_tab()


if __name__ == "__main__":
    main()
