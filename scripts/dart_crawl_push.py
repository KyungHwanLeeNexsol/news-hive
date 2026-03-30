"""Standalone DART crawler for GitHub Actions.

Scrapes DART disclosures and pushes them to the NewsHive server API.
Runs outside Oracle Cloud where DART is accessible.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

import httpx

DART_SEARCH_URL = "https://dart.fss.or.kr/dsab007/detailSearch.ax"
DART_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://dart.fss.or.kr/dsab007/main.do",
    "X-Requested-With": "XMLHttpRequest",
}

MARKET_MAP = {"kospi": "KOSPI", "kosdaq": "KOSDAQ"}


def parse_dart_html(html: str) -> list[dict]:
    """Parse DART search result HTML into disclosure dicts."""
    items = []
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)

    for row in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 5:
            continue

        market_match = re.search(r'class="tagCom_(\w+)"', tds[1])
        market_cls = market_match.group(1) if market_match else ""
        if market_cls not in MARKET_MAP:
            continue

        corp_code_match = re.search(r"openCorpInfoNew\('(\d+)'", tds[1])
        corp_code = corp_code_match.group(1) if corp_code_match else ""

        corp_name_match = re.search(
            r"openCorpInfoNew.*?>\s*([^<]+?)\s*</a>", tds[1], re.DOTALL
        )
        corp_name = corp_name_match.group(1).strip() if corp_name_match else ""

        report_match = re.search(
            r'rcpNo=(\d+).*?>\s*(.+?)\s*</a>', tds[2], re.DOTALL
        )
        if not report_match:
            continue
        rcept_no = report_match.group(1)
        report_name = re.sub(r"\s+", " ", report_match.group(2)).strip()

        date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", tds[4])
        rcept_dt = (
            f"{date_match.group(1)}{date_match.group(2)}{date_match.group(3)}"
            if date_match
            else ""
        )

        items.append({
            "corp_code": corp_code,
            "corp_name": corp_name,
            "report_name": report_name,
            "rcept_no": rcept_no,
            "rcept_dt": rcept_dt,
            "market": MARKET_MAP.get(market_cls, ""),
        })

    return items


def parse_total_pages(html: str) -> int:
    m = re.search(r"\[\d+/(\d+)\]", html)
    return int(m.group(1)) if m else 1


def crawl_dart(days: int = 3, max_pages: int = 20) -> list[dict]:
    """Crawl DART disclosures."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    bgn_de = start_date.strftime("%Y%m%d")
    end_de = end_date.strftime("%Y%m%d")

    print(f"Crawling DART: {bgn_de} ~ {end_de}")

    all_items = []
    seen_rcepts = set()

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        # Session init
        try:
            client.get(
                "https://dart.fss.or.kr/dsab007/main.do",
                headers={"User-Agent": DART_HEADERS["User-Agent"]},
            )
        except Exception:
            pass

        for page_no in range(1, max_pages + 1):
            form_data = {
                "currentPage": str(page_no),
                "maxResults": "100",
                "maxLinks": "5",
                "sort": "date",
                "series": "desc",
                "startDate": bgn_de,
                "endDate": end_de,
                "textCrpNm": "",
                "textCrpCik": "",
            }

            try:
                resp = client.post(DART_SEARCH_URL, data=form_data, headers=DART_HEADERS)
                resp.raise_for_status()
            except Exception as e:
                print(f"  Page {page_no} failed: {e}")
                break

            items = parse_dart_html(resp.text)
            if not items:
                if page_no == 1:
                    print("  No disclosures found")
                break

            total_pages = parse_total_pages(resp.text)
            new_items = [i for i in items if i["rcept_no"] not in seen_rcepts]
            for i in new_items:
                seen_rcepts.add(i["rcept_no"])
            all_items.extend(new_items)

            print(f"  Page {page_no}/{total_pages}: {len(new_items)} new items")

            if page_no >= total_pages:
                break

    return all_items


def push_to_server(items: list[dict], api_url: str, push_secret: str) -> dict:
    """Push disclosures to the server API."""
    resp = httpx.post(
        f"{api_url}/api/disclosures/push",
        json={"items": items},
        headers={"X-Push-Secret": push_secret},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    api_url = os.environ.get("API_URL", "http://140.245.76.242:8000")
    push_secret = os.environ.get("DART_PUSH_SECRET", "")

    if not push_secret:
        print("ERROR: DART_PUSH_SECRET not set")
        sys.exit(1)

    items = crawl_dart(days=3, max_pages=20)
    print(f"\nTotal crawled: {len(items)} disclosures")

    if not items:
        print("Nothing to push")
        return

    result = push_to_server(items, api_url, push_secret)
    print(f"Push result: {json.dumps(result)}")


if __name__ == "__main__":
    main()
