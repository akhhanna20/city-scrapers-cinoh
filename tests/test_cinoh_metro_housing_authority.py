from datetime import datetime
from os.path import dirname, join

import pytest
from city_scrapers_core.constants import CANCELLED, COMMISSION, PASSED
from city_scrapers_core.utils import file_response
from freezegun import freeze_time

from city_scrapers.spiders.cinoh_metro_housing_authority import (
    CinohMetroHousingAuthoritySpider,
)

test_response = file_response(
    join(dirname(__file__), "files", "cinoh_metro_housing_authority.html"),
    url="https://cintimha.com/wp-admin/admin-ajax.php?action=get_calendar_events"
    "&noheader=true&start_date=1719938796&end_date=1751475199&show_expired=true"
    "&event_category_id=executive-office-1466450825",
)
spider = CinohMetroHousingAuthoritySpider()

freezer = freeze_time("2025-01-02")
freezer.start()

parsed_items = [item for item in spider.parse(test_response)]

freezer.stop()


def test_count():
    assert len(parsed_items) == 6


def test_title():
    assert parsed_items[0]["title"] == "Board of Commissioners Meeting - RESCHEDULED"
    assert (
        parsed_items[1]["title"] == "Board of Commissioners meeting - "
        "Rescheduled from August 20"
    )
    assert parsed_items[2]["title"] == "Board of Commissioners Meeting"
    assert parsed_items[5]["title"] == "Annual & Board of Commissioners Meetings"


def test_description():
    assert parsed_items[0]["description"] == (
        "<p><strong>CANCELLED! Rescheduled for Thursday, August 22. 2024 at 3:30 p.m. "
        "to 5:30 p.m.</strong></p><p>The Cincinnati Metropolitan Housing Authority "
        "Board of Commissioners Meeting will take place in the CMHA Boardroom located "
        "at 1635 Western Avenue (45214) beginning at 6pm.</p><p><strong><a "
        'href="https://cintimha.com/about/board-of-commissioners/">Click here</a></str'
        "ong> for information on Requests to Speak and to see the meeting agenda.</p>"
    )


def test_start():
    assert parsed_items[0]["start"] == datetime(2024, 8, 20, 18, 0)
    assert parsed_items[5]["start"] == datetime(2024, 12, 17, 17, 45)


def test_end():
    assert parsed_items[0]["end"] == datetime(2024, 8, 20, 20, 0)
    assert parsed_items[5]["end"] == datetime(2024, 12, 17, 20, 0)


def test_time_notes():
    assert parsed_items[0]["time_notes"] == ""


def test_id():
    assert (
        parsed_items[0]["id"] == "cinoh_metro_housing_authority/202408201800/x/"
        "board_of_commissioners_meeting"
    )


def test_status():
    assert parsed_items[0]["status"] == CANCELLED
    assert parsed_items[1]["status"] == CANCELLED
    assert parsed_items[2]["status"] == PASSED
    assert parsed_items[3]["status"] == PASSED
    assert parsed_items[4]["status"] == PASSED
    assert parsed_items[5]["status"] == PASSED


def test_location():
    assert parsed_items[0]["location"] == {
        "name": "CMHA Boardroom",
        "address": "1635 Western Ave, Cincinnati, OH 45214",
    }
    assert parsed_items[1]["location"] == {
        "name": "CMHA Boardroom",
        "address": "1635 Western Ave, Cincinnati, OH 45214",
    }
    assert parsed_items[2]["location"] == {
        "name": "CMHA Boardroom",
        "address": "1635 Western Ave, Cincinnati, OH 45214",
    }
    assert parsed_items[3]["location"] == {
        "name": "West Union Square",
        "address": "2942 Banning Road, Cincinnati, OH 45239",
    }
    assert parsed_items[4]["location"] == {
        "name": "The Reserve on South Martin",
        "address": "7363 Martin Street, Cincinnati, OH 45231 (Mt. Healthy)",
    }
    assert parsed_items[5]["location"] == {
        "name": "CMHA Boardroom",
        "address": "1635 Western Ave, Cincinnati, OH 45214",
    }


def test_source():
    assert parsed_items[0]["source"] == "https://cintimha.com/calendar/"


def test_links():
    assert parsed_items[0]["links"] == [
        {
            "title": "Event Link",
            "href": "https://cintimha.com/events/board-of-commissioners-meeting-63/",
        }
    ]


def test_classification():
    assert parsed_items[0]["classification"] == COMMISSION


@pytest.mark.parametrize("item", parsed_items)
def test_all_day(item):
    assert item["all_day"] is False
