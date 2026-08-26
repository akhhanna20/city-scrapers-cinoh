import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable

import scrapy
from city_scrapers_core.constants import CITY_COUNCIL, COMMITTEE
from city_scrapers_core.items import Meeting
from city_scrapers_core.spiders import LegistarSpider
from dateutil.parser import parse
from scrapy import Selector


class CinohCityCouncilSpider(LegistarSpider):
    name = "cinoh_city_council"
    agency = "Cincinnati City Council"
    timezone = "America/New_York"
    start_urls = ["https://cincinnatioh.legistar.com/Calendar.aspx"]
    video_page_url = "https://www.cincinnati-oh.gov/council/council-meeting-videos/"

    DEFAULT_ADDRESS = "801 Plum St. Cincinnati, OH 45202"

    def start_requests(self):
        """
        Fetch the video page first so self.video_links is populated
        before Legistar meeting parsing (and _parse_links) runs.
        """
        yield scrapy.Request(self.video_page_url, callback=self._parse_video_page)

    def _parse_video_page(self, response):
        self.video_links = []  # list of (date, normalized_title, url)

        for li in response.css("div.mura-region-local ul li"):
            link = li.css("a")
            if not link:
                continue

            href = link.attrib.get("href")
            date_text = link.css("::text").get("").replace("\xa0", " ").strip()

            full_text = " ".join(li.css("*::text").extract()).replace("\xa0", " ")
            title_text = full_text.replace(date_text, "", 1)
            title_text = title_text.strip(" \n\t-")

            try:
                video_date = parse(date_text, fuzzy=True).date()
            except (ValueError, OverflowError):
                continue

            self.video_links.append(
                (video_date, self._normalize_title(title_text), href)
            )

        # Start the normal Legistar crawl
        for request in super().start_requests():
            yield request

    def parse_legistar(self, response):
        """
        Parse upcoming and past meetings from the
        Cincinnati City Council meetings table.

        Oftentimes, the columns: meeting details, agenda,
        minutes, and video are left blank on the calander
        but when they are, they are in the form of links.
        """
        seen_meetings = getattr(self, "_seen_meetings", None)
        if seen_meetings is None:
            seen_meetings = self._seen_meetings = set()

        for obj in response:
            title = obj["Name"]["label"]
            em_note = self._parse_location_em_note(
                obj.get("_MeetingLocationHtml") or ""
            )
            if em_note:
                title = f"{title} - {em_note}"

            meeting = Meeting(
                title=title,
                description="",
                classification=self._parse_classification(obj),
                start=self.legistar_start(obj),
                end=None,
                all_day=False,
                time_notes="",
                status=self._parse_status(obj),
                location=self._parse_location(obj),
                links=self._parse_links(obj),
                source=self.legistar_source(obj),
            )

            # Dedupe by title + start datetime (date and time combined).
            dedupe_key = (meeting["title"].strip().lower(), meeting["start"])
            if dedupe_key in seen_meetings:
                continue
            seen_meetings.add(dedupe_key)

            meeting["id"] = self._get_id(meeting)

            yield meeting

    def _parse_location_em_note(self, html):
        """Extract the text inside <em>...</em> in the location cell, if any,
        excluding cancellation notices (handled separately by _parse_status)."""
        if not html:
            return ""

        match = re.search(r"<em[^>]*>(.*?)</em>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""

        note_text = "".join(Selector(text=match.group(1)).css("*::text").getall())
        note_text = re.sub(r"\s+", " ", note_text).strip()

        if note_text.strip().lower() in (
            "notice of cancellation",
            "notice of time & location change",
        ):
            return ""

        return note_text

    def _parse_legistar_events(
        self, response: scrapy.http.Response
    ) -> Iterable[Dict]:  # noqa
        events_table = response.css("table.rgMasterTable")[0]

        headers = []
        for header in events_table.css("th[class^='rgHeader']"):
            header_text = (
                " ".join(header.css("*::text").extract())
                .replace("&nbsp;", " ")
                .strip()  # noqa
            )
            header_inputs = header.css("input")
            if header_text:
                headers.append(header_text)
            elif len(header_inputs) > 0:
                headers.append(header_inputs[0].attrib["value"])
            else:
                headers.append(header.css("img")[0].attrib["alt"])

        events = []
        for row in events_table.css("tr.rgRow, tr.rgAltRow"):
            try:
                data = defaultdict(lambda: None)
                for header, field in zip(headers, row.css("td")):
                    field_text = (
                        " ".join(field.css("*::text").extract())
                        .replace("&nbsp;", " ")
                        .strip()
                    )
                    # Keep the raw HTML for the location cell so we can
                    # separate venue name / address / <em> notes later.
                    if header == "Meeting Location":
                        data["_MeetingLocationHtml"] = field.get()

                    url = None
                    if len(field.css("a")) > 0:
                        link_el = field.css("a")[0]
                        if "onclick" in link_el.attrib and link_el.attrib[
                            "onclick"
                        ].startswith(("radopen('", "window.open", "OpenTelerikWindow")):
                            url = response.urljoin(
                                link_el.attrib["onclick"].split("'")[1]
                            )
                        elif "href" in link_el.attrib:
                            url = response.urljoin(link_el.attrib["href"])
                    if url:
                        if header in ["", "ics"] or "View.ashx?M=IC" in url:
                            header = "iCalendar"
                            value = {"url": url}
                        else:
                            value = {"label": field_text, "url": url}
                    else:
                        value = field_text

                    data[header] = value

                ical_url = data.get("iCalendar", {}).get("url")
                if ical_url is None or ical_url in self._scraped_urls:
                    continue
                else:
                    self._scraped_urls.add(ical_url)
                events.append(dict(data))
            except Exception:
                pass

        return events

    def _parse_classification(self, obj):
        if obj["Name"]["label"] == "Cincinnati City Council":
            return CITY_COUNCIL
        else:
            return COMMITTEE

    def _parse_status(self, obj):

        date = obj["Meeting Date"]
        parsed_date = parse(date, fuzzy=True)
        location = obj.get("Meeting Location") or ""

        if "notice of cancellation" in location.lower():
            return "cancelled"
        elif parsed_date < datetime.today():
            return "passed"
        else:
            return "tentative"

    def _parse_location(self, obj):

        html = obj.get("_MeetingLocationHtml") or ""

        if not html:
            room = (obj.get("Meeting Location") or "").strip()
            return {"address": self.DEFAULT_ADDRESS, "name": room}

        # Drop <em>...</em> notes (e.g. "PUBLIC HEARING") entirely
        html = re.sub(r"<em[^>]*>.*?</em>", "", html, flags=re.IGNORECASE | re.DOTALL)

        # Keep what's before the first <br> -- anything after is extra wording
        html = re.split(r"<br\s*/?>", html, maxsplit=1, flags=re.IGNORECASE)[0]

        # Extract text via Selector so ANY wrapping tag (<font>, <span>, etc.)
        # is stripped. Preserve internal "\n" so multi-line
        # venue-name / street / city-state-zip cells still split correctly.
        raw_text = "".join(Selector(text=html).css("*::text").getall())
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.split("\n")]
        lines = [line for line in lines if line]

        if not lines:
            room = (obj.get("Meeting Location") or "").strip()
            return {"address": self.DEFAULT_ADDRESS, "name": room}

        if len(lines) == 1:
            line = lines[0]
            if re.search(r"\b\d{5}\b", line):
                # Single line with an embedded address, e.g.
                # "Cincinnati Music Hall Ballroom, 1241 Elm St, Cincinnati, OH 45202"
                parts = [p.strip() for p in line.split(",")]
                addr_start = next(
                    (i for i, p in enumerate(parts) if re.match(r"^\d+\s", p)), None
                )
                if addr_start:
                    name = ", ".join(parts[:addr_start])
                    address = ", ".join(parts[addr_start:])
                else:
                    name = ""
                    address = line
            else:
                # Room name only, e.g. "Council Chambers, Room 300"
                name = line
                address = self.DEFAULT_ADDRESS
        else:
            # Multi-line: first line is the venue name, rest is the address
            name = lines[0]
            address = ", ".join(lines[1:])

        return {"address": address, "name": name}

    def _parse_links(self, obj):

        links = []

        if not obj.get("Meeting Details") == "Meeting\u00a0details":
            links.append(
                {"title": "Meeting Details", "href": obj["Meeting Details"]["url"]}
            )

        if not obj.get("Agenda") == "Not\u00a0available":
            links.append({"title": "Agenda", "href": obj["Agenda"]["url"]})

        if not obj.get("Agenda Packet") == "Not\u00a0available":
            links.append(
                {"title": "Agenda Packet", "href": obj["Agenda Packet"]["url"]}
            )

        if not obj.get("Minutes") == "Not\u00a0available":
            links.append({"title": "Minutes", "href": obj["Minutes"]["url"]})

        video_url = self._match_video_link(obj)
        if video_url:
            links.append({"title": "Video", "href": video_url})
        elif isinstance(obj.get("Video"), dict) and obj["Video"].get("url"):
            links.append({"title": "Video", "href": obj["Video"]["url"]})

        return links

    def _normalize_title(self, text):
        """Clean text by converting to lowercase and stripping non-alphanumeric characters."""  # noqa
        if not text:
            return ""
        text = re.sub(r"&\s*", "and ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text.lower())
        return text.strip()

    def _titles_match(self, legistar_title, video_title):
        """
        Matches Legistar and video titles based on committee name and
        differentiates public hearings on the same date.
        """
        if not legistar_title or not video_title:
            return False

        # 1. Handle Public Hearing specificity
        is_legistar_ph = "public hearing" in legistar_title
        is_video_ph = "public hearing" in video_title

        # If one is a public hearing and the other isn't, they are different meetings
        if is_legistar_ph != is_video_ph:
            return False

        # Stop words to strip before comparing core tokens
        stop_words = {
            "and",
            "or",
            "the",
            "of",
            "to",
            "a",
            "in",
            "for",
            "on",
            "meeting",
            "committee",
        }

        legistar_words = set(
            w for w in legistar_title.split() if len(w) > 2 and w not in stop_words
        )
        video_words = set(
            w for w in video_title.split() if len(w) > 2 and w not in stop_words
        )

        if not legistar_words or not video_words:
            return False

        # Check keyword overlap (at least 2 matching core words, or all if fewer)
        overlap = legistar_words.intersection(video_words)
        min_required = min(2, len(legistar_words))

        return len(overlap) >= min_required

    def _match_video_link(self, obj):
        name_obj = obj.get("Name")
        title = (
            name_obj.get("label", "")
            if isinstance(name_obj, dict)
            else str(name_obj or "")
        )
        date_str = obj.get("Meeting Date")
        if not title or not date_str:
            return None

        # Append em_note (e.g. "Public Hearing") so the title matches the video title
        em_note = self._parse_location_em_note(obj.get("_MeetingLocationHtml") or "")
        if em_note:
            title = f"{title} - {em_note}"

        try:
            meeting_date = parse(date_str, fuzzy=True).date()
        except (ValueError, OverflowError):
            self.logger.warning(f"Unable to parse date: {date_str}")
            return None

        norm_legistar_title = self._normalize_title(title)

        for video_date, video_title, url in getattr(self, "video_links", []):
            if video_date == meeting_date and self._titles_match(
                norm_legistar_title, video_title
            ):
                return url

        return None
