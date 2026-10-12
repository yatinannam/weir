from weir.router.coverage import check, details, passage, required_types, strip_type

CAMP = "The blood donation camp is held on the first Saturday of every month, 10 am to 3 pm, in the Main Block lobby."
ICU = "ICU visiting hours: 11 am to 1 pm and 5 pm to 7 pm daily. Two visitors at a time."
PARKING = "Cars: ₹40 for the first 2 hours on weekdays and ₹60 on weekends."
DIRECTORY = "| Pediatric ward | Mother and Child Wing, 1st | ext. 2171 |"


def test_canonical_forms_compare_equal():
    assert details("10am, 10:00 am and 10 AM")["time"] == {"10am"}
    assert details("Rs. 500 or ₹ 500 or INR 500")["money"] == {"500"}
    assert details("ext. 2150 and extension 2150")["extension"] == {"2150"}
    assert details("Saturdays and saturday")["day"] == {"saturday"}


def test_daily_is_not_a_day_detail():  # Review Focus 1
    assert "day" not in details("open daily and every day")


def test_required_types_follow_the_question():
    assert required_types("When is the blood donation camp held?") == {"time", "day"}
    assert required_types("What time does ICU visiting start in the morning?") == {"time"}
    assert required_types("How much is car parking for 2 hours?") == {"money"}     # "2 hours" is a quantity
    assert required_types("What are the ICU visiting hours?") == {"time"}
    assert required_types("What is the pediatric ward desk extension?") == {"extension"}
    assert required_types("How many visitors are allowed in the ICU?") == {"quantity"}
    assert required_types("Which floor is cardiology on?") == frozenset()


def test_the_best_matching_line_is_the_passage():
    assert passage("When is the blood donation camp held?", ["Blood bank opens 24 hours.\n" + CAMP]) == [CAMP]
    assert passage("Where is the cafeteria?", [CAMP]) == []


def test_a_day_without_its_time_fails():  # q-036
    c = check("When is the blood donation camp held?", "It is held on the first Saturday of every month.", [CAMP])
    assert not c.passed and c.reason == "missing:time" and c.missing == ("time",)


def test_the_full_answer_passes():
    c = check("When is the blood donation camp held?", "First Saturday of every month, 10 am to 3 pm.", [CAMP])
    assert c.passed and c.reason is None and c.strict_passed


def test_one_of_two_times_is_enough():  # Review Focus 2 (q-001)
    c = check("What time does ICU visiting start in the morning?", "Morning visiting starts at 11 am.", [ICU])
    assert c.passed and not c.strict_passed      # the strict variant wants every time on the line


def test_times_without_daily_pass():  # Review Focus 1
    assert check("When can I visit the ICU?", "11 am to 1 pm and 5 pm to 7 pm.", [ICU]).passed


def test_a_price_question_needs_a_price():
    q = "How much is car parking for 2 hours on a weekday?"
    assert check(q, "₹40 for the first 2 hours.", [PARKING]).passed
    assert check(q, "Parking is charged by the hour.", [PARKING]).reason == "missing:money"


def test_an_extension_without_the_prefix_counts():  # Review Focus 3 (q-129)
    q = "What is the pediatric ward desk extension?"
    assert check(q, "The extension is 2171.", [DIRECTORY]).passed
    assert check(q, "Call the pediatric ward desk.", [DIRECTORY]).reason == "missing:extension"


def test_nothing_to_judge_passes():
    assert check("Which floor is cardiology on?", "The first floor.", [DIRECTORY]).passed
    assert check("When is the camp held?", "Saturday.", ["Unrelated text about parking."]).passed


def test_strip_type_removes_every_detail_of_one_type():
    assert details(strip_type("First Saturday, 10 am to 3 pm.", "time")).get("time") is None
    assert details(strip_type("First Saturday, 10 am to 3 pm.", "time"))["day"] == {"first saturday"}


# --- Final review: real hospital-rag chunks start with a "<title>: <heading>" line (chunking.py). That line holds
# the question's topic words but no details, so it must never be the passage on its own.

GENERAL_WEEKDAYS = ("General ward visiting hours: Weekdays\n"
                    "Visitors to the general wards (Main Block, 4th floor) are welcome from Monday to Friday between "
                    "4 pm and 7 pm. Visiting is not allowed outside this window except for the registered attendant.")
ICU_WINDOWS = ("ICU visiting hours: Visiting windows\n"
               "The Intensive Care Unit (ICU) is on the 3rd floor of the Main Block. Visiting is allowed twice a day.\n\n"
               "- Morning: 11 am to 11:30 am\n- Evening: 5 pm to 6 pm")


def test_the_heading_line_is_never_the_passage_alone():
    assert passage("What are the visiting hours for the general ward on weekdays?", [GENERAL_WEEKDAYS])[0].startswith(
        "Visitors to the general wards")
    assert passage("What time does ICU visiting start in the morning?", [ICU_WINDOWS]) == ["- Morning: 11 am to 11:30 am"]


def test_real_chunks_catch_a_missing_time():
    q = "What are the visiting hours for the general ward on weekdays?"
    assert check(q, "You can visit the general ward on weekdays.", [GENERAL_WEEKDAYS]).reason == "missing:time"
    assert check(q, "Weekdays from 4 pm to 7 pm.", [GENERAL_WEEKDAYS]).passed
    q = "What time does ICU visiting start in the morning?"
    assert check(q, "ICU visiting starts in the morning.", [ICU_WINDOWS]).reason == "missing:time"
    assert check(q, "It starts at 11 am.", [ICU_WINDOWS]).passed


def test_visiting_and_opening_times_ask_for_a_time():  # final review: "times" never triggered the check
    assert required_types("What are the visiting times?") == {"time"}
    assert required_types("What are the pharmacy opening times?") == {"time"}
