from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import requests
import re

from moex_carry.domain.models import KeyRate


class CbrKeyRateClient:
    def __init__(self, base_url: str, key_rate_path: str, timeout_sec: int = 20) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.key_rate_path = key_rate_path.lstrip("/")
        self.timeout_sec = timeout_sec
        self.session = requests.Session()

    def _request(self) -> bytes:
        url = urljoin(self.base_url, self.key_rate_path)
        response = self.session.get(url, timeout=self.timeout_sec)
        response.raise_for_status()
        return response.content

    def _request_html(self, from_date: date, to_date: date) -> str:
        url = urljoin(self.base_url, "hd_base/KeyRate/")
        params = {
            "UniDbQuery.Posted": "True",
            "UniDbQuery.From": from_date.strftime("%d.%m.%Y"),
            "UniDbQuery.To": to_date.strftime("%d.%m.%Y"),
        }
        response = self.session.get(url, params=params, timeout=self.timeout_sec)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "windows-1251"
        return response.text

    @staticmethod
    def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame.columns = [str(col).strip().lower() for col in frame.columns]
        date_col = None
        rate_col = None
        for col in frame.columns:
            if "date" in col or "дата" in col:
                date_col = col
            if "rate" in col or "ставка" in col or "ключ" in col:
                rate_col = col
        if date_col is None or rate_col is None:
            raise ValueError("Unsupported CBR key rate format")
        frame = frame[[date_col, rate_col]].rename(
            columns={date_col: "date", rate_col: "rate"}
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["rate"] = pd.to_numeric(frame["rate"], errors="coerce")
        frame["rate"] = _normalize_rate_series(frame["rate"])
        return frame.dropna()

    def get_key_rate_history(self) -> list[KeyRate]:
        try:
            content = self._request()
            frame = pd.read_excel(BytesIO(content))
            frame = self._normalize_frame(frame)
            return [KeyRate(date=row["date"], rate=float(row["rate"])) for _, row in frame.iterrows()]
        except requests.exceptions.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise
        return self._get_key_rate_history_html()

    def _get_key_rate_history_html(self) -> list[KeyRate]:
        from_date = date(2010, 1, 1)
        to_date = date.today()
        text = self._request_html(from_date, to_date)
        rows = re.findall(r"<tr>(.*?)</tr>", text, flags=re.S)
        rates: list[KeyRate] = []
        for row in rows:
            cols = [
                re.sub(r"<.*?>", "", col).strip()
                for col in re.findall(r"<td.*?>(.*?)</td>", row, flags=re.S)
            ]
            if len(cols) < 2:
                continue
            raw_date, raw_rate = cols[0], cols[1]
            try:
                parsed_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
            except (ValueError, TypeError):
                try:
                    parsed_date = date.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    continue
            try:
                rate_value = float(str(raw_rate).replace(",", "."))
            except (ValueError, TypeError):
                continue
            rates.append(KeyRate(date=parsed_date, rate=rate_value))
        rates = _normalize_rate_list(rates)
        rates.sort(key=lambda item: item.date)
        return rates


def _normalize_rate_series(series: pd.Series) -> pd.Series:
    clean = series.dropna()
    if clean.empty:
        return series
    max_rate = float(clean.max())
    if max_rate > 1.5:
        return series / 100.0
    return series


def _normalize_rate_list(rates: list[KeyRate]) -> list[KeyRate]:
    if not rates:
        return rates
    max_rate = max(rate.rate for rate in rates)
    if max_rate > 1.5:
        return [KeyRate(date=rate.date, rate=rate.rate / 100.0) for rate in rates]
    return rates


def latest_rate(rates: list[KeyRate], as_of: Optional[date] = None) -> Optional[KeyRate]:
    if not rates:
        return None
    if as_of is None:
        return max(rates, key=lambda r: r.date)
    eligible = [r for r in rates if r.date <= as_of]
    return max(eligible, key=lambda r: r.date) if eligible else None
