from weir_eval.keyfacts import check_facts, fact_present, norm


def test_norm_handles_case_space_dashes_and_am_pm():
    assert norm("  4 P.M.– 8 p.m. ") == "4 pm- 8 pm"


def test_alternatives():
    assert fact_present("Visiting ends at 8:00 PM daily.", "8 pm|8:00 pm")
    assert not fact_present("Visiting ends at 9 pm.", "8 pm|8:00 pm")


def test_check_facts_score():
    r = check_facts("ICU visiting is 11 am to 11:30 am, one visitor.", ["11 am", "one visitor|1 visitor", "5 pm"])
    assert (r.hits, r.total) == (2, 3)
    assert abs(r.score - 2 / 3) < 1e-9


import pytest  # noqa: E402


@pytest.mark.parametrize("answer", [
    "Visiting is 4 pm – 7 pm on weekdays.",
    "Visiting is 4:00 PM to 7:00 PM on weekdays.",
    "Visiting is 4-7 pm on weekdays.",
    "Visiting is 4pm to 7pm on weekdays.",
])
def test_time_range_formats_match(answer):
    assert fact_present(answer, "4 pm to 7 pm")


def test_noon_and_midnight_equivalents():
    assert fact_present("It runs 9 am to 12 pm.", "9 am to 12 noon")
    assert fact_present("It runs 9 am to noon.", "9 am to 12 noon")
    assert fact_present("The shift starts at 12 am.", "12 midnight|midnight")


@pytest.mark.parametrize(("answer", "fact"), [
    ("The fee is ₹500.", "₹50"),
    ("It costs 150 rupees.", "50 rupees"),
    ("The fee is ₹1000.", "₹100"),
    ("Call ext. 21110.", "2111"),
])
def test_numbers_do_not_match_inside_other_numbers(answer, fact):
    assert not fact_present(answer, fact)


def test_numbers_match_before_punctuation():
    assert fact_present("The fee is ₹50, payable at the desk.", "₹50")
    assert fact_present("Pay ₹1,200.", "₹1,200")


@pytest.mark.parametrize("answer", [
    "You would receive a 90 % refund.",           # q-151: a space before "%" (D38)
    "You would receive a 90% refund.",
    "You would receive a 90 percent refund.",
    "You would receive a 90 per cent refund.",
])
def test_percent_spellings_match_every_alternative(answer):
    assert fact_present(answer, "90 percent")
    assert fact_present(answer, "90%")


def test_percent_still_needs_the_whole_number():
    assert not fact_present("You get a 190 % refund.", "90%")
    assert not fact_present("You get a 9 % refund.", "90 percent")


@pytest.mark.parametrize("answer", [
    "The pediatric ward desk extension is 2171.",  # q-129: no "ext." prefix (D38)
    "Call ext. 2171.",
    "Call ext 2171.",
    "It can be reached at extension 2171.",
    "Extension number: 2171",
])
def test_extension_spellings_match(answer):
    assert fact_present(answer, "ext. 2171|ext 2171|extension 2171")


def test_extension_still_needs_the_right_number():
    assert not fact_present("The desk extension is 2172.", "ext. 2171|extension 2171")
    assert not fact_present("Call extension 21710.", "ext. 2171")
