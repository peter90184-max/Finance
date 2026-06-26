import concurrent.futures
import html
import json
import os
import re
from datetime import date, datetime

import feedparser
import altair as alt
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
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_FETCH_ERRORS: dict[str, str] = {}

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
        "description": "우량 회사채 조달금리입니다. 대기업 자금조달 부담을 보는 핵심 지표입니다.",
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
    "Core PCE": {
        "code": "PCEPILFE",
        "unit": "YoY %",
        "group": "경기/물가",
        "transform": "yoy",
        "description": "연준이 중시하는 근원 개인소비지출 물가입니다. 통화정책의 긴축 또는 완화 여지를 판단할 때 봅니다.",
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
    "글로벌 구리 가격 지수": {
        "code": "PCOPPUSDM",
        "unit": "지수",
        "group": "환율/원자재",
        "transform": "level",
        "description": "글로벌 구리 가격입니다. 산업 경기와 제조업 모멘텀을 반영하는 대표 원자재 지표입니다.",
    },
    "금 가격": {
        "code": ["GOLDAMGBD228NLBM", "GOLDPMGBD228NLBM"],
        "unit": "달러",
        "group": "환율/원자재",
        "transform": "level",
        "description": "런던 금 가격입니다. 안전자산 선호와 실질금리 흐름을 함께 반영합니다.",
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
        "구리/금 비율은 글로벌 경기 모멘텀 나침반입니다. 우상향은 경기 회복, 하락 전환은 방어적 포지션 선호로 해석합니다.",
        "히트맵은 지수 상승이 특정 섹터 쏠림인지, 넓은 상승인지 빠르게 확인하는 보조 화면입니다.",
    ],
}


def _period_bounds(cycle: str) -> tuple[str, str]:
    if cycle == "D":
        return START_DAY, END_DAY
    return START_MONTH, END_MONTH


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
    return series


@st.cache_data(ttl=3600)
def fetch_domestic_rates() -> pd.DataFrame:
    daily_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []

    for label, spec in DOMESTIC_SERIES.items():
        try:
            rows = fetch_ecos_rows(spec["stat"], spec["cycle"], spec["items"])
            series = rows_to_series(rows, spec["cycle"]).rename(label)
        except Exception:
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

    if {"글로벌 구리 가격 지수", "금 가격"}.issubset(merged.columns):
        ratio_base = merged[["글로벌 구리 가격 지수", "금 가격"]].sort_index().ffill()
        merged["구리/금 비율"] = ratio_base["글로벌 구리 가격 지수"] / ratio_base["금 가격"]

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


def render_ratio_dual_axis_chart(df: pd.DataFrame) -> None:
    required = ["글로벌 구리 가격 지수", "금 가격", "구리/금 비율"]
    available = [col for col in required if col in df.columns and not df[col].dropna().empty]
    if len(available) < 3:
        missing = [col for col in required if col not in available]
        st.info(f"구리/금 비율 계산에 필요한 데이터가 부족합니다: {', '.join(missing)}")
        return

    chart_df = df[required].dropna().tail(180).reset_index(names="date")
    price_df = chart_df.melt(
        id_vars="date",
        value_vars=["글로벌 구리 가격 지수", "금 가격"],
        var_name="가격 지표",
        value_name="가격",
    )

    price_chart = (
        alt.Chart(price_df)
        .mark_line()
        .encode(
            x=alt.X("date:T", title="date"),
            y=alt.Y("가격:Q", title="구리/금 가격"),
            color=alt.Color("가격 지표:N", title="가격 지표"),
            tooltip=["date:T", "가격 지표:N", alt.Tooltip("가격:Q", format=",.2f")],
        )
    )
    ratio_chart = (
        alt.Chart(chart_df)
        .mark_line(color="#111827", strokeWidth=3)
        .encode(
            x=alt.X("date:T", title="date"),
            y=alt.Y("구리/금 비율:Q", title="구리/금 비율"),
            tooltip=["date:T", alt.Tooltip("구리/금 비율:Q", format=".5f")],
        )
    )
    st.altair_chart(alt.layer(price_chart, ratio_chart).resolve_scale(y="independent"), use_container_width=True)


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
    if "실업률" in df.columns:
        unemployment = df["실업률"].dropna()
        if len(unemployment) >= 12:
            latest = unemployment.iloc[-1]
            trailing_low = unemployment.tail(12).min()
            gap = latest - trailing_low
            if gap >= 0.5:
                st.error(
                    "샴의 법칙 경기침체 경고: "
                    f"현재 실업률이 최근 12개월 최저치보다 {gap:.2f}%p 높습니다."
                )

    if "미국채 10년-2년" in df.columns:
        curve = df["미국채 10년-2년"].dropna()
        if not curve.empty and curve.iloc[-1] < 0:
            st.warning("⚠️ 미국채 10Y-2Y 장단기 금리차 역전 상태 지속 중 (경기 침체 선행 신호 위험)")


def render_market_summary(domestic: pd.DataFrame, macro: pd.DataFrame, cross: pd.DataFrame) -> None:
    st.markdown("### 오늘의 자금시장 신호")
    render_sahm_rule_warning(macro)

    cols = st.columns(6)
    aa_rate = latest_value(domestic, "회사채 AA- 3년")
    bbb_aa_spread = latest_value(domestic, "BBB- vs AA- 스프레드")
    hy_spread = latest_value(macro, "하이일드 스프레드")
    curve_10y2y = latest_value(macro, "미국채 10년-2년")
    han_us_gap = latest_value(cross, "한-미 기준금리차")
    copper_gold = latest_value(macro, "구리/금 비율")

    aa_signal, aa_color = signal_from_value(aa_rate, 4.5, 5.0)
    bbb_signal, bbb_color = signal_from_value(bbb_aa_spread, 4.5, 6.0)
    hy_signal, hy_color = signal_from_value(hy_spread, 4.5, 6.0)
    curve_signal, curve_color = signal_from_value(curve_10y2y, 0.0, -0.5, higher_is_risk=False)
    gap_signal, gap_color = signal_from_value(han_us_gap, -1.0, -2.0, higher_is_risk=False)
    copper_signal, copper_color = signal_from_value(copper_gold, 0.004, 0.0035, higher_is_risk=False)

    with cols[0]:
        render_signal_card("국내 AA- 조달금리", format_value(aa_rate, "%"), aa_signal, "대기업 회사채 발행 부담", aa_color)
    with cols[1]:
        render_signal_card("BBB- vs AA-", format_value(bbb_aa_spread, "%p"), bbb_signal, "비우량 자금시장 경색 신호", bbb_color)
    with cols[2]:
        render_signal_card("미국 신용위험", format_value(hy_spread, "%p"), hy_signal, "하이일드 스프레드 기준", hy_color)
    with cols[3]:
        render_signal_card("10Y-2Y 금리차", format_value(curve_10y2y, "%p"), curve_signal, "역전 시 경기침체 선행 신호", curve_color)
    with cols[4]:
        render_signal_card("한-미 기준금리차", format_value(han_us_gap, "%p"), gap_signal, "환헤지 비용과 달러 조달 압력", gap_color)
    with cols[5]:
        render_signal_card("구리/금 비율", format_value(copper_gold, "", 4), copper_signal, "경기 모멘텀 나침반", copper_color)


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


def render_tradingview_widgets() -> None:
    st.markdown("### 글로벌 시장 히트맵")
    st.caption("무료 공식 TradingView 위젯입니다. 데이터는 외부 위젯에서 직접 제공되며 앱 내부 계산에는 쓰지 않습니다.")

    if not st.checkbox("TradingView 외부 위젯 불러오기", value=False):
        st.info("외부 위젯은 브라우저 렌더링 부담이 커서 기본으로 꺼두었습니다. 필요할 때만 체크해서 불러오세요.")
        link_cols = st.columns(3)
        link_cols[0].link_button("TradingView 히트맵 새 창", "https://www.tradingview.com/heatmap/stock/")
        link_cols[1].link_button("Finviz S&P500 맵", "https://finviz.com/map.ashx")
        link_cols[2].link_button("TradingView 시장", "https://www.tradingview.com/markets/")
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

    forex_col, overview_col = st.columns(2)
    with forex_col:
        st.markdown("#### 환율 히트맵")
        tradingview_widget(
            "embed-widget-forex-heat-map.js",
            {
                "currencies": ["USD", "EUR", "JPY", "CNY", "KRW", "GBP", "AUD", "CAD", "CHF"],
                "isTransparent": False,
                "colorTheme": "light",
                "locale": "kr",
            },
            430,
        )
    with overview_col:
        st.markdown("#### 시장 개요")
        tradingview_widget(
            "embed-widget-market-overview.js",
            {
                "colorTheme": "light",
                "dateRange": "12M",
                "showChart": True,
                "locale": "kr",
                "largeChartUrl": "",
                "isTransparent": False,
                "showSymbolLogo": True,
                "showFloatingTooltip": False,
                "tabs": [
                    {
                        "title": "지수",
                        "symbols": [
                            {"s": "FOREXCOM:SPXUSD", "d": "S&P 500"},
                            {"s": "NASDAQ:NDX", "d": "Nasdaq 100"},
                            {"s": "TVC:US10Y", "d": "미국 10년"},
                            {"s": "TVC:DXY", "d": "달러지수"},
                        ],
                    },
                    {
                        "title": "원자재",
                        "symbols": [
                            {"s": "NYMEX:CL1!", "d": "WTI"},
                            {"s": "NYMEX:NG1!", "d": "천연가스"},
                            {"s": "TVC:GOLD", "d": "금"},
                        ],
                    },
                    {
                        "title": "환율",
                        "symbols": [
                            {"s": "FX_IDC:USDKRW", "d": "달러/원"},
                            {"s": "FX_IDC:USDJPY", "d": "달러/엔"},
                            {"s": "FX_IDC:USDCNH", "d": "달러/위안"},
                        ],
                    },
                ],
            },
            430,
        )


def render_domestic_section(df: pd.DataFrame) -> None:
    st.markdown("### 국내 자금시장")
    st.caption(f"한국은행 ECOS | {START_DAY[:4]}년 이후 | 시장금리는 일간 기준")

    if df.empty:
        st.warning("국내 금리 데이터를 불러오지 못했습니다. 네트워크 권한 또는 ECOS 응답을 확인하세요.")
        return

    metric_cols = ["기준금리", "국고채 3년", "국고채 10년", "회사채 AA- 3년", "회사채 BBB- 3년", "KORIBOR 3개월"]
    render_metric_row(df, DOMESTIC_SERIES, metric_cols)

    chart_col, spread_col = st.columns([2, 1])
    with chart_col:
        st.markdown("#### 일간 금리 추이")
        rate_cols = [col for col in metric_cols if col in df.columns]
        min_date = df.index.min().date()
        max_date = df.index.max().date()
        default_start = max(min_date, (pd.Timestamp(max_date) - pd.DateOffset(years=3)).date())
        start_date, end_date = st.date_input(
            "국내 금리 조회 기간",
            value=(default_start, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        filtered = df.loc[pd.to_datetime(start_date) : pd.to_datetime(end_date)]
        st.line_chart(filtered[rate_cols], use_container_width=True)

    with spread_col:
        st.markdown("#### 조달 스프레드")
        spread_cols = [col for col in ["AA- vs 국고채 스프레드", "BBB- vs AA- 스프레드"] if col in df.columns]
        if spread_cols:
            spread_start, spread_end = st.date_input(
                "스프레드 조회 기간",
                value=(df.index.min().date(), df.index.max().date()),
                min_value=df.index.min().date(),
                max_value=df.index.max().date(),
                key="spread_date_range",
            )
            spread_df = df.loc[pd.to_datetime(spread_start) : pd.to_datetime(spread_end), spread_cols]
            st.line_chart(spread_df, use_container_width=True)
        st.markdown(
            "AA- 스프레드는 대기업 조달 여건, BBB- vs AA- 스프레드는 비우량 기업의 자금 가뭄과 부도위험 선행 신호로 봅니다."
        )

    with st.expander("최근 일별 국내 금리 데이터", expanded=False):
        display_cols = [col for col in metric_cols + ["AA- vs 국고채 스프레드", "BBB- vs AA- 스프레드"] if col in df.columns]
        recent_df = format_dataframe(df[display_cols].tail(120).sort_index(ascending=False))
        st.dataframe(recent_df, use_container_width=True, hide_index=True)

    render_indicator_notes(DOMESTIC_SERIES, "국내 지표 설명")


def render_cross_market_section(cross: pd.DataFrame) -> None:
    st.markdown("### 달러 유동성 및 환헤지 비용")
    st.caption("한국 기준금리와 미국 기준금리를 맞춰 계산한 한-미 기준금리차입니다.")

    if cross.empty or "한-미 기준금리차" not in cross.columns:
        st.info("한-미 기준금리차를 계산할 데이터가 부족합니다.")
        return

    cols = [col for col in ["한국 기준금리", "미국 기준금리", "한-미 기준금리차"] if col in cross.columns]
    st.line_chart(cross[cols], use_container_width=True)
    latest_gap = cross["한-미 기준금리차"].dropna().iloc[-1]
    st.markdown(
        f"현재 한-미 기준금리차는 **{latest_gap:.2f}%p**입니다. "
        "한국 금리가 미국보다 낮아질수록 외화 조달과 환헤지 비용 부담이 커질 수 있습니다."
    )


def render_macro_section(df: pd.DataFrame) -> None:
    st.markdown("### 미국/글로벌 매크로")
    st.caption("FRED | 병렬 호출 | 유동성, 채권/신용, 경기/물가, 환율/원자재")

    if df.empty:
        st.warning("미국/글로벌 매크로 데이터를 불러오지 못했습니다. 네트워크 권한 또는 FRED 응답을 확인하세요.")
        return

    important = ["SOFR", "연준 지급준비금", "하이일드 스프레드", "미국채 10년-2년", "실업률", "구리/금 비율"]
    render_metric_row(df, FRED_SERIES | {"구리/금 비율": {"unit": ""}}, [name for name in important if name in df.columns])

    groups = {
        "유동성": [name for name, spec in FRED_SERIES.items() if spec["group"] == "유동성"],
        "채권/신용": [name for name, spec in FRED_SERIES.items() if spec["group"] == "채권/신용"],
        "경기/물가": [name for name, spec in FRED_SERIES.items() if spec["group"] == "경기/물가"],
        "환율/원자재": [
            name
            for name, spec in FRED_SERIES.items()
            if spec["group"] == "환율/원자재" and name not in {"글로벌 구리 가격 지수", "금 가격"}
        ],
    }

    for row_start in range(0, len(groups), 2):
        cols = st.columns(2)
        for col, (title, names) in zip(cols, list(groups.items())[row_start : row_start + 2]):
            with col:
                st.markdown(f"#### {title}")
                visible_cols = [name for name in names if name in df.columns]
                if visible_cols:
                    st.line_chart(df[visible_cols], use_container_width=True)

    if "구리/금 비율" in df.columns:
        st.markdown("#### 구리/금 비율")
        render_ratio_dual_axis_chart(df)
        st.info("구리/금 비율이 우상향하면 경기 회복과 위험자산 선호, 꺾이면 경기 둔화와 채권 선호 신호로 해석할 수 있습니다.")
    else:
        raw_cols = [col for col in ["글로벌 구리 가격 지수", "금 가격"] if col in df.columns]
        if raw_cols:
            st.markdown("#### 구리/금 비율")
            st.info(f"구리/금 비율 계산 전 단계 데이터만 있습니다: {', '.join(raw_cols)}. 금 또는 구리 FRED 시리즈 응답이 비어 있으면 비율을 만들 수 없습니다.")
        if FRED_FETCH_ERRORS:
            with st.expander("FRED 수집 실패 진단", expanded=False):
                for label, error in FRED_FETCH_ERRORS.items():
                    st.write(f"{label}: {error}")

    with st.expander("월별 미국/글로벌 매크로 데이터", expanded=False):
        display_df = format_dataframe(df, "%Y-%m")
        st.dataframe(display_df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

    render_indicator_notes(FRED_SERIES, "미국/글로벌 지표 설명")


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
    domestic = fetch_domestic_rates()
    macro = fetch_fred_macro_data()
    cross = build_cross_market_indicators(domestic, macro)

    render_market_guide()
    render_market_summary(domestic, macro, cross)
    st.divider()
    render_domestic_section(domestic)
    st.divider()
    render_cross_market_section(cross)
    st.divider()
    render_macro_section(macro)
    st.divider()
    render_tradingview_widgets()


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
    link_cols = st.columns(3)
    link_cols[0].link_button("TradingView 히트맵", "https://www.tradingview.com/heatmap/stock/")
    link_cols[1].link_button("Finviz S&P500 맵", "https://finviz.com/map.ashx")
    link_cols[2].link_button("FRED 데이터", "https://fred.stlouisfed.org/")


def main() -> None:
    st.set_page_config(
        page_title="글로벌 자금 대시보드",
        page_icon="📈",
        layout="wide",
    )

    st.title("글로벌 자금 대시보드")
    st.caption("대기업 자금담당자와 글로벌 매크로 투자자를 위한 무료 데이터 기반 시장 상황판")

    tab_dashboard, tab_news = st.tabs(["시장 대시보드", "뉴스/캘린더"])

    with tab_dashboard:
        render_dashboard_tab()

    with tab_news:
        render_news_calendar_tab()


if __name__ == "__main__":
    main()
