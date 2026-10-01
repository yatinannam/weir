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
