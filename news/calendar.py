"""
High-Impact Economic News Filter using ForexFactory / FairEconomy JSON calendar.
Strictly alerts and filters before/after major events (e.g. CPI, NFP, FOMC, PPI, Powell speeches).
"""
import requests
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class NewsFilter:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("news_filter", {})
        self.enabled = self.config.get("enabled", True)
        self.feed_url = self.config.get("feed_url", FEED_URL)
        self.buffer_before_min = self.config.get("buffer_minutes_before", 30)
        self.buffer_after_min = self.config.get("buffer_minutes_after", 30)
        self.impact_filter = self.config.get("impact_filter", ["High"])
        self._events_cache: List[Dict[str, Any]] = []
        self._last_fetch: Optional[datetime] = None

    def fetch_calendar(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        if self._last_fetch and (now - self._last_fetch) < timedelta(hours=2):
            return self._events_cache

        try:
            resp = requests.get(self.feed_url, timeout=10)
            if resp.status_code == 200:
                self._events_cache = resp.json()
                self._last_fetch = now
                logger.info(f"Loaded {len(self._events_cache)} economic calendar events.")
                return self._events_cache
        except Exception as e:
            logger.warning(f"Could not load economic calendar: {e}")
        return self._events_cache

    def check_news_status(self, symbol: str, check_time: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Evaluates whether a symbol is blocked or warned due to high-impact economic news.
        Gold (XAUUSD) is sensitive to USD news.
        """
        if not self.enabled:
            return {"is_safe": True, "active_warning": False, "upcoming_event": None, "feed_ok": True}

        if check_time is None:
            check_time = datetime.now(timezone.utc)

        events = self.fetch_calendar()
        if not events:
            # Hardened Fail-Closed requirement:
            # If the economic calendar cannot be verified, suppress trading signals
            # to prevent executing ahead of unmonitored high-impact news releases (CPI/NFP/FOMC).
            fail_closed = self.config.get("fail_closed_on_error", True)
            return {
                "is_safe": not fail_closed,
                "active_warning": True,
                "upcoming_event": "CALENDAR_UNAVAILABLE_FAIL_CLOSED: News feed unreachable. Signals suppressed for safety.",
                "feed_ok": False,
                "reason": "CALENDAR_UNAVAILABLE_FAIL_CLOSED"
            }

        relevant_currency = "USD"
        if "EUR" in symbol:
            relevant_currency = "EUR"
        elif "GBP" in symbol:
            relevant_currency = "GBP"
        elif "JPY" in symbol:
            relevant_currency = "JPY"

        for ev in events:
            impact = ev.get("impact", "")
            country = ev.get("country", "")
            if impact not in self.impact_filter:
                continue

            # XAUUSD is heavily USD-driven
            if country != relevant_currency and not ("XAU" in symbol and country == "USD"):
                continue

            date_str = ev.get("date")
            if not date_str:
                continue

            try:
                # Format: 2026-10-14T08:30:00-04:00
                ev_time = datetime.fromisoformat(date_str)
                time_diff = (ev_time - check_time).total_seconds() / 60.0

                # If within buffer window
                if -self.buffer_after_min <= time_diff <= self.buffer_before_min:
                    return {
                        "is_safe": False,
                        "active_warning": True,
                        "upcoming_event": f"HIGH IMPACT: {country} {ev.get('title')} at {ev_time.strftime('%H:%M UTC')}",
                        "feed_ok": True
                    }
                # If approaching within 2 hours
                elif 0 < time_diff <= 120:
                    return {
                        "is_safe": True,
                        "active_warning": True,
                        "upcoming_event": f"Upcoming: {country} {ev.get('title')} in {int(time_diff)} mins",
                        "feed_ok": True
                    }
            except Exception as e:
                continue

        return {"is_safe": True, "active_warning": False, "upcoming_event": None, "feed_ok": True}
