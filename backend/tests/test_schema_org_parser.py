"""Tests for the schema.org lodging reader.

The markup here is **synthetic**, deliberately. Real confirmation mail carries a
property's street address, the host's phone number and a booking reference, and
the fixture-scrubbing rules in CLAUDE.md exist because that kind of data has
repeatedly survived into committed fixtures. Every shape below was copied from
a real email's *structure* and then filled with invented values, which gives the
same coverage with nothing to redact.
"""

from backend.parsers.schema_org import extract_lodging_reservations


class _Email:
    def __init__(self, html_body="", body="", sender="test@example.com", subject="Booking"):
        self.html_body = html_body
        self.body = body
        self.sender = sender
        self.subject = subject


def _json_ld(payload: str) -> str:
    return f'<html><body><script type="application/ld+json">{payload}</script></body></html>'


AIRBNB_JSON_LD = """{
 "@type": "LodgingReservation",
 "@context": "http://schema.org",
 "reservationNumber": "HMTESTREF1",
 "reservationStatus": "http://schema.org/ReservationConfirmed",
 "underName": {"@type": "Person", "name": "Alex"},
 "reservationFor": {
  "@type": "LodgingBusiness",
  "name": "Riverside Studio",
  "address": {
   "@type": "PostalAddress",
   "streetAddress": "12 Example Street",
   "addressLocality": "Porto",
   "addressRegion": "Porto",
   "postalCode": "4000-000",
   "addressCountry": "PT"
  },
  "telephone": "+351 000 000 000"
 },
 "checkinDate": "2026-04-10T15:00",
 "checkoutDate": "2026-04-14T11:00"
}"""


class TestJsonLd:
    def test_reads_a_confirmation(self):
        (stay,) = extract_lodging_reservations(_Email(_json_ld(AIRBNB_JSON_LD)))
        assert stay["name"] == "Riverside Studio"
        assert stay["address"] == "12 Example Street"
        assert stay["city"] == "Porto"
        assert stay["country_code"] == "PT"
        assert stay["booking_reference"] == "HMTESTREF1"
        assert stay["contact"] == "+351 000 000 000"
        assert stay["check_in_datetime"] == "2026-04-10T15:00"
        assert stay["check_out_datetime"] == "2026-04-14T11:00"

    def test_entity_escaped_block_still_parses(self):
        """Two of six real Airbnb blocks arrived HTML-escaped; a literal
        json.loads fails on `&quot;` and the booking would be lost."""
        escaped = AIRBNB_JSON_LD.replace('"', "&quot;")
        (stay,) = extract_lodging_reservations(_Email(_json_ld(escaped)))
        assert stay["name"] == "Riverside Studio"

    def test_graph_wrapper(self):
        payload = f'{{"@context":"http://schema.org","@graph":[{AIRBNB_JSON_LD}]}}'
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["booking_reference"] == "HMTESTREF1"

    def test_list_of_objects(self):
        payload = f"[{AIRBNB_JSON_LD}]"
        assert len(extract_lodging_reservations(_Email(_json_ld(payload)))) == 1

    def test_unparseable_block_is_skipped_not_raised(self):
        html = _json_ld("{ this is not json LodgingReservation")
        assert extract_lodging_reservations(_Email(html)) == []


class TestOffsetsAreDiscarded:
    """The offsets in real lodging markup were the *recipient's*, not the
    property's — a flat +01:00 on properties that were all on CEST. The wall
    clock was right every time, and StayService re-localises it from the
    property's own coordinates, so honouring the offset breaks a right answer."""

    def test_offset_is_stripped_keeping_wall_clock(self):
        payload = AIRBNB_JSON_LD.replace(
            '"checkinDate": "2026-04-10T15:00"', '"checkinDate": "2026-04-10T15:00:00+01:00"'
        )
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_in_datetime"] == "2026-04-10T15:00"

    def test_trailing_z_is_stripped_too(self):
        payload = AIRBNB_JSON_LD.replace(
            '"checkinDate": "2026-04-10T15:00"', '"checkinDate": "2026-04-10T15:00:00Z"'
        )
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_in_datetime"] == "2026-04-10T15:00"


class TestDegradedRecords:
    def test_bare_date_takes_the_default_time(self):
        """One real record's checkoutDate was '2020-08-15' with no time at all."""
        payload = AIRBNB_JSON_LD.replace(
            '"checkoutDate": "2026-04-14T11:00"', '"checkoutDate": "2026-04-14"'
        )
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_out_datetime"] == "2026-04-14T11:00"

    def test_missing_name_falls_back_to_locality(self):
        """A real record had neither a property name nor a reservation number.
        `trip_stays.name` is NOT NULL, and a row reading 'Porto' beats a lost
        booking."""
        payload = AIRBNB_JSON_LD.replace('"name": "Riverside Studio",\n', "")
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["name"] == "Porto"
        assert stay["booking_reference"] == "HMTESTREF1"

    def test_country_name_is_not_mistaken_for_a_code(self):
        payload = AIRBNB_JSON_LD.replace('"addressCountry": "PT"', '"addressCountry": "Portugal"')
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["country_code"] is None

    def test_missing_dates_drops_the_record(self):
        payload = AIRBNB_JSON_LD.replace('"checkoutDate": "2026-04-14T11:00"', '"checkoutDate": ""')
        assert extract_lodging_reservations(_Email(_json_ld(payload))) == []

    def test_checkout_before_checkin_is_refused(self):
        payload = AIRBNB_JSON_LD.replace(
            '"checkoutDate": "2026-04-14T11:00"', '"checkoutDate": "2026-04-09T11:00"'
        )
        assert extract_lodging_reservations(_Email(_json_ld(payload))) == []


class TestCancellations:
    def test_a_cancelled_reservation_is_not_imported(self):
        payload = AIRBNB_JSON_LD.replace(
            "http://schema.org/ReservationConfirmed", "http://schema.org/ReservationCancelled"
        )
        assert extract_lodging_reservations(_Email(_json_ld(payload))) == []


MICRODATA = """
<html><body>
  <div>
    <table><tr><td>Your booking is confirmed</td></tr></table>
    <div itemscope itemtype="http://schema.org/LodgingReservation">
      <meta itemprop="reservationNumber" content="MD-TEST-9"/>
      <link itemprop="reservationStatus" href="http://schema.org/ReservationConfirmed"/>
      <div itemprop="underName" itemscope itemtype="http://schema.org/Person">
        <meta itemprop="name" content="Alex"/>
      </div>
      <div itemprop="reservationFor" itemscope itemtype="http://schema.org/LodgingBusiness">
        <meta itemprop="name" content="Hotel Example"/>
        <div class="wrapper"><div class="inner">
          <div itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
            <meta itemprop="streetAddress" content="1 Test Road"/>
            <meta itemprop="addressLocality" content="Helsinki"/>
            <meta itemprop="addressCountry" content="FI"/>
          </div>
        </div></div>
        <meta itemprop="telephone" content="+358 00 000 0000"/>
      </div>
      <meta itemprop="checkinDate" content="2026-05-02T14:00"/>
      <meta itemprop="checkoutDate" content="2026-05-05T10:00"/>
    </div>
  </div>
</body></html>
"""


class TestMicrodata:
    def test_reads_a_microdata_reservation(self):
        (stay,) = extract_lodging_reservations(_Email(MICRODATA))
        assert stay["name"] == "Hotel Example"
        assert stay["city"] == "Helsinki"
        assert stay["country_code"] == "FI"
        assert stay["booking_reference"] == "MD-TEST-9"
        assert stay["check_in_datetime"] == "2026-05-02T14:00"

    def test_nested_plain_divs_do_not_close_the_item(self):
        """Marketing HTML wraps markup in layout divs. A parser that pops its
        item on the first matching end tag loses everything after them — here,
        the address sits two wrappers deep."""
        (stay,) = extract_lodging_reservations(_Email(MICRODATA))
        assert stay["address"] == "1 Test Road"
        assert stay["contact"] == "+358 00 000 0000"


class TestNoMarkup:
    def test_plain_email_yields_nothing(self):
        html = "<html><body><p>Your stay at Hotel Example is confirmed for 2 May.</p></body></html>"
        assert extract_lodging_reservations(_Email(html)) == []

    def test_flight_markup_is_not_lodging(self):
        html = """<div itemscope itemtype="http://schema.org/FlightReservation">
          <meta itemprop="reservationNumber" content="ABC123"/></div>"""
        assert extract_lodging_reservations(_Email(html)) == []

    def test_empty_email(self):
        assert extract_lodging_reservations(_Email()) == []


class TestDuplicateBlocks:
    def test_one_booking_restated_per_guest_yields_one_stay(self):
        """Flight markup restates a leg per passenger and lodging markup can do
        the same; two identical blocks are one booking."""
        html = (
            "<html><body>"
            f'<script type="application/ld+json">{AIRBNB_JSON_LD}</script>'
            f'<script type="application/ld+json">{AIRBNB_JSON_LD}</script>'
            "</body></html>"
        )
        assert len(extract_lodging_reservations(_Email(html))) == 1

    def test_two_real_bookings_are_both_kept(self):
        second = AIRBNB_JSON_LD.replace("HMTESTREF1", "HMTESTREF2").replace(
            "Riverside Studio", "Hilltop Flat"
        )
        html = (
            "<html><body>"
            f'<script type="application/ld+json">{AIRBNB_JSON_LD}</script>'
            f'<script type="application/ld+json">{second}</script>'
            "</body></html>"
        )
        assert len(extract_lodging_reservations(_Email(html))) == 2


class TestBothPropertySpellings:
    """Google's Gmail markup reference and schema.org's own vocabulary disagree
    about what the check-in property is called, and both spellings are in the
    wild: Airbnb writes `checkinDate`, while schema.org canonically says
    `checkinTime` — which is what KDE's Itinerary reads and what Hotels.com
    annotates with. Reading only one is a silent miss, not an error."""

    def test_schema_org_spelling_is_read(self):
        payload = AIRBNB_JSON_LD.replace('"checkinDate"', '"checkinTime"').replace(
            '"checkoutDate"', '"checkoutTime"'
        )
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_in_datetime"] == "2026-04-10T15:00"
        assert stay["check_out_datetime"] == "2026-04-14T11:00"

    def test_google_spelling_wins_when_both_are_present(self):
        payload = AIRBNB_JSON_LD.replace(
            '"checkinDate": "2026-04-10T15:00"',
            '"checkinDate": "2026-04-10T15:00", "checkinTime": "2026-04-10T09:00"',
        )
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_in_datetime"] == "2026-04-10T15:00"

    def test_date_only_annotation_takes_the_default_time(self):
        """Hotels.com's markup carries the dates but omits the times — KDE
        scrapes them back out of the HTML. Defaulting is the honest degradation
        here: a 14:00 convention is visible and editable, a fabricated exact
        time would not be."""
        payload = AIRBNB_JSON_LD.replace(
            '"checkinDate": "2026-04-10T15:00"', '"checkinTime": "2026-04-10"'
        ).replace('"checkoutDate": "2026-04-14T11:00"', '"checkoutTime": "2026-04-14"')
        (stay,) = extract_lodging_reservations(_Email(_json_ld(payload)))
        assert stay["check_in_datetime"] == "2026-04-10T14:00"
        assert stay["check_out_datetime"] == "2026-04-14T11:00"
