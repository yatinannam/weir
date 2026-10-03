import pytest

from weir.cache.entities import Lexicon

from .conftest import CONFIGS

LEX = Lexicon.from_yaml(CONFIGS / "entities.yaml")


@pytest.mark.parametrize(("a", "b"), [
    ("What are the ICU visiting hours?", "What are the general ward visiting hours?"),
    ("When is the Cardiology OPD open?", "When is the Neurology OPD open?"),
    ("How much is parking for a car?", "How much is parking for a two-wheeler?"),
    ("When is the adult vaccination clinic?", "When is the child vaccination clinic?"),
    ("When does the night shift start for nurses?", "When does the night shift start for doctors?"),
    ("What is the deposit for cashless insurance admission?", "What is the deposit for self-pay admission?"),
    ("What is the private room tariff?", "What is the semi-private room tariff?"),
    ("What are the main pharmacy hours?", "What are the OPD pharmacy hours?"),
    ("Is parking free on weekdays?", "Is parking free on weekends?"),
    ("Can I visit for 2 hours?", "Can I visit for 3 hours?"),
    ("Is there parking on Sunday?", "Is there no parking on Sunday?"),
    ("Can kids visit the ICU?", "Can adults visit the ICU?"),
])
def test_kb_look_alike_pairs_conflict(a, b):
    assert LEX.conflicts(a, b)


@pytest.mark.parametrize(("a", "b"), [
    ("What are the ICU visiting hours?", "When can I visit someone in intensive care?"),
    ("How much does a CT scan cost?", "What is the charge for a CT?"),
    ("What is the standard discharge time?", "When do patients usually get discharged?"),
    ("Parking fee for a bike?", "How much do two-wheelers pay for parking?"),
])
def test_paraphrases_do_not_conflict(a, b):
    assert not LEX.conflicts(a, b)


def test_longest_phrase_wins():
    assert LEX.extract("semi-private room tariff").terms == frozenset({"wards:semi-private room"})
    assert LEX.extract("intensive care unit hours").terms == frozenset({"wards:icu"})


def test_numbers_and_units_are_normalised():
    assert LEX.extract("Rs 1,200 for 2 hours at 4pm").numbers == frozenset({"1200", "2 hour", "4 pm"})


def test_negation_forms():
    assert LEX.extract("I can't visit").negated and LEX.extract("non-veg thali").negated
    assert not LEX.extract("I can visit").negated


def test_duplicate_phrase_rejected():
    with pytest.raises(ValueError, match="two terms"):
        Lexicon({"a": {"x": ["shared"]}, "b": {"y": ["shared"]}})


@pytest.mark.parametrize(("a", "b"), [
    ("What is the replacement cost of a lost ID badge?", "What is the replacement cost of a damaged ID badge?"),
    ("How quickly must the Code Blue team arrive in the Main Block?", "How quickly must the Code Blue team arrive in the OPD Block?"),
    ("What is the price of the Basic health checkup package?", "What is the price of the Executive health checkup package?"),
])
def test_sweep_found_look_alikes_conflict(a, b):  # added after the Phase 2 threshold sweep
    assert LEX.conflicts(a, b)


@pytest.mark.parametrize(("a", "b"), [
    ("If I cancel the Executive health checkup three days before, what refund applies?",
     "If I cancel the Executive health checkup one day before, what refund applies?"),
    ("Which departments are on the 2nd floor?", "Which departments are on the 3rd floor?"),
    ("Which departments are on the second floor?", "Which departments are on the third floor?"),
    ("Can two attendants stay overnight?", "Can one attendant stay overnight?"),
])
def test_number_words_and_ordinals_conflict(a, b):  # final-review finding C1
    assert LEX.conflicts(a, b)


@pytest.mark.parametrize(("a", "b"), [
    ("Cancel three days before?", "Cancel 3 days before?"),
    ("Which departments are on the 2nd floor?", "Which departments are on the second floor?"),
    ("What does the first copy cost?", "What does the 1st copy cost?"),
])
def test_number_words_equal_digits(a, b):
    assert not LEX.conflicts(a, b)
