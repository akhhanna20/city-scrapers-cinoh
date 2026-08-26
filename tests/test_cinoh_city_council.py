import json
from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import CITY_COUNCIL, COMMITTEE
from freezegun import freeze_time
from scrapy.http import TextResponse

from city_scrapers.spiders.cinoh_city_council import CinohCityCouncilSpider

freezer = freeze_time("2026-08-15")
freezer.start()

with open(
    join(dirname(__file__), "files", "cinoh_city_council.json"), "r", encoding="utf-8"
) as f:
    test_response = json.load(f)

with open(
    join(dirname(__file__), "files", "cinoh_city_council_videos.html"), "rb"
) as f:
    video_page_body = f.read()

spider = CinohCityCouncilSpider()

# Run the real _parse_video_page against the saved videos page fixture to
# populate spider.video_links, same as start_requests would before crawling
# Legistar. Advancing the generator once executes the extraction loop and
# then yields the (discarded) Legistar start_requests call.
video_page_response = TextResponse(
    url=spider.video_page_url, body=video_page_body, encoding="utf-8"
)
next(spider._parse_video_page(video_page_response), None)

parsed_items = [item for item in spider.parse_legistar(test_response)]

freezer.stop()


def test_title():
    assert parsed_items[0]["title"] == "Cincinnati City Council"


def test_title_with_em_note():
    # <em>PUBLIC HEARING</em> in the location cell gets appended to the title
    assert (
        parsed_items[7]["title"]
        == "Budget, Finance and Governance Committee - PUBLIC HEARING"
    )


def test_title_excludes_cancellation_note():
    # <em>NOTICE OF CANCELLATION</em> is handled via status, not appended to title
    assert parsed_items[8]["title"] == "Youth and Human Services Committee"


def test_description():
    assert parsed_items[0]["description"] == ""


def test_start():
    assert parsed_items[0]["start"] == datetime(2026, 8, 5, 14, 0)


def test_end():
    assert parsed_items[0]["end"] is None


def test_time_notes():
    assert parsed_items[0]["time_notes"] == ""


def test_id():
    assert (
        parsed_items[0]["id"]
        == "cinoh_city_council/202608051400/x/cincinnati_city_council"
    )


def test_status():
    assert parsed_items[0]["status"] == "passed"


def test_status_cancelled():
    assert parsed_items[8]["status"] == "cancelled"


def test_status_tentative():
    assert parsed_items[9]["status"] == "tentative"


def test_location():
    # Real data: <font>-wrapped, empty <em></em> -- confirms the <font> tag
    # doesn't leak into the parsed name.
    assert parsed_items[0]["location"] == {
        "address": "801 Plum St. Cincinnati, OH 45202",
        "name": "Council Chambers, Room 300",
    }


def test_location_multiline_address():
    # "Sayler Park Recreation Center\n6720 Home City Avenue\nCincinnati, OH 45233"
    assert parsed_items[7]["location"] == {
        "address": "6720 Home City Avenue, Cincinnati, OH 45233",
        "name": "Sayler Park Recreation Center",
    }


def test_source():
    assert (
        parsed_items[0]["source"]
        == "https://cincinnatioh.legistar.com/DepartmentDetail.aspx"
        "?ID=38076&GUID=1CA48415-BFFD-4857-8A93-48AA89BD31C6"
    )


def test_links():
    assert parsed_items[1]["links"] == [

        {
            "title": "Meeting Details",
            "href": "https://cincinnatioh.legistar.com/MeetingDetail.aspx?ID="
            "1425666&GUID=E91E0675-2E09-49AE-81CA-EB45052DF089&Options=info|&Search=",
        },
        {
            "title": "Agenda",
            "href": "https://cincinnatioh.legistar.com/View.ashx?M=A&ID=1425666&GUID="
            "E91E0675-2E09-49AE-81CA-EB45052DF089",
        },
        {
            "title": "Agenda Packet",
            "href": "https://cincinnatioh.legistar.com/View.ashx?M=PA&ID=1425666&GUID="
            "E91E0675-2E09-49AE-81CA-EB45052DF089",
        },
        {
            "title": "Minutes",
            "href": "https://cincinnatioh.legistar.com/View.ashx?M=M&ID=1425666&GUID="
            "E91E0675-2E09-49AE-81CA-EB45052DF089",
        },
        {
            "title": "Video",
            "href": "https://archive.org/details/18260804-hg",
        },
    ]


def test_video_link_matched():
    # 8/5/2026 "Cincinnati City Council" matches the videos-page entry for
    # the same date + title -- confirms _match_video_link pairs them up.
    video_links = [
        link for link in parsed_items[0]["links"] if link["title"] == "Video"
    ]
    assert video_links == [
        {"title": "Video", "href": "https://archive.org/details/10260805-coun"}
    ]


def test_classification():
    assert parsed_items[0]["classification"] == CITY_COUNCIL
    assert parsed_items[1]["classification"] == COMMITTEE


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
