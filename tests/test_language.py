"""English or Hindi.

The load-bearing test in this file is
`test_a_hindi_buyer_and_an_english_buyer_land_in_one_group`. Everything else
is presentation; that one is the product. If the language a buyer reads in can
split the pool, the app has quietly stopped doing the only thing it does.
"""
from __future__ import annotations

import pytest

from app import i18n
from app.db import loads
from app.nlu import rules
from app.services import conversation, groups, intents

from conftest import address_from

DONE = "__addons_done__"

#: Answers in each language, keyed by slot. The values a chip sends are always
#: English -- these are what a buyer would *type*.
EN = {
    "grade": "BWR", "thickness": "18mm", "sheet_size": "8x4", "core": "hardwood",
    "finish": "plain", "preferred_brand": "Century", "brand_flexible": "yes",
    "quantity": "120", "city": "Ahmedabad", "area": "Satellite",
    "desired_purchase_date": "within 15 days", "can_wait": "yes", "name": "Havish",
}
HI = {
    **EN,
    "brand_flexible": "हाँ", "quantity": "१२०", "city": "अहमदाबाद",
    "area": "सैटेलाइट", "can_wait": "हाँ", "name": "हविश",
}


@pytest.fixture(autouse=True)
def plywood_only(monkeypatch):
    """The suite enables every category; the live config offers one. These
    tests are about the language, not the menu, so they use the live shape."""
    import app.catalog as cat

    monkeypatch.setattr(cat, "CATEGORIES", {"PLY": cat.ALL_CATEGORIES["PLY"]})


def run(chat, session, lang, answers, mobile, picks=(), limit=45):
    """Play a whole conversation in one language. Returns every reply."""
    answers = address_from(answers)
    replies = [chat(session, "")]
    replies.append(chat(session, lang))
    picks = list(picks)
    for _ in range(limit):
        reply = replies[-1]
        question = reply.get("question")
        if not question or reply.get("done"):
            break
        slot = question["slot"]
        if slot == "_addons":
            value = f"addon:{picks.pop(0)}" if picks else DONE
        elif slot == "mobile":
            value = mobile
        else:
            bare = slot.split(":")[-1]
            value = answers.get(bare) or (
                question["chips"][0]["value"] if question["chips"] else "skip"
            )
        replies.append(chat(session, value))
    return replies


def said(replies):
    return " ".join(
        m.get("text", "") for reply in replies for m in reply["messages"]
    )


# --------------------------------------------------------------------------- #
# the choice
# --------------------------------------------------------------------------- #
def test_the_language_is_the_very_first_thing_asked(chat):
    reply = chat("l1", "")

    assert reply["question"]["slot"] == "_lang"
    assert [c["value"] for c in reply["chips"]] == ["en", "hi"]
    # Readable by someone who cannot read the other option.
    blurb = said([reply])
    assert "language" in blurb.lower() and "भाषा" in blurb


def test_choosing_english_leaves_the_flow_exactly_as_it_was(chat):
    reply = chat("l2", "")
    reply = chat("l2", "en")

    assert reply["question"]["slot"] == "thickness"
    assert "what thickness" in said([reply]).lower()


def test_choosing_hindi_switches_the_questions(chat):
    chat("l3", "")
    reply = chat("l3", "hi")

    blurb = said([reply])
    assert "कितनी मोटाई" in blurb, blurb
    assert "what thickness" not in blurb.lower()


@pytest.mark.parametrize("typed,expected", [
    ("hindi", "hi"), ("हिंदी", "hi"), ("Hindi", "hi"),
    ("english", "en"), ("English", "en"),
])
def test_the_choice_can_be_typed_as_well_as_tapped(typed, expected):
    assert i18n.language_of(typed) == expected


def test_someone_who_ignores_the_question_is_not_ignored(chat):
    """Skipping straight to "I need plywood" must not lose the message --
    throwing away the first thing someone says is worse than not knowing
    their language."""
    chat("l4", "")
    reply = chat("l4", "I need 100 sheets of plywood")

    assert reply["summary"]["category"] == "PLY"
    assert reply["summary"]["quantity"] == 100
    assert reply["question"]["slot"] != "_lang"


def test_reloading_before_answering_asks_again(chat):
    chat("l5", "")
    reply = chat("l5", "")          # a reload, not an answer
    assert reply["question"]["slot"] == "_lang"


# --------------------------------------------------------------------------- #
# the rule the whole feature rests on
# --------------------------------------------------------------------------- #
def test_a_hindi_buyer_and_an_english_buyer_land_in_one_group(chat):
    """Two buyers, same board, same city, different languages -- one group.

    If this fails the app has split its own pool along a language line, which
    defeats the entire purpose of pooling.
    """
    run(chat, "m1", "en", EN, "9812500001")
    run(chat, "m2", "hi", HI, "9812500002")

    pooled = groups.list_groups(category="PLY")
    assert len(pooled) == 1, [g["code"] for g in pooled]
    assert pooled[0]["strong_intent_qty"] == 240
    assert pooled[0]["city"] == "Ahmedabad"
    assert pooled[0]["code"].startswith("PLY-AHM-")


def test_the_specification_is_stored_in_one_language(chat):
    """The spec is matched on, so it is canonical English whatever was read."""
    run(chat, "m3", "hi", HI, "9812500003")

    group = groups.list_groups(category="PLY")[0]
    assert groups.spec_of(group) == {
        # Grade is not asked, so it takes the category default -- in
        # English, like every other stored value.
        "grade": "MR", "thickness": "18 mm", "sheet_size": "8 x 4 ft",
        "preferred_brand": "Century",
    }


def test_a_chip_sends_english_however_it_is_labelled(chat):
    """The label is for the buyer, the value is for the server."""
    chat("m4", "")
    reply = chat("m4", "hi")                  # -> the thickness question

    labels = [c["label"] for c in reply["chips"]]
    values = [c["value"] for c in reply["chips"]]
    assert "पता नहीं" in labels, labels
    assert "Not Sure" in values, values
    assert "पता नहीं" not in values


def test_the_transcript_records_the_conversation_the_buyer_actually_had(chat):
    """Not half English and half Hindi -- that would be a transcript in
    neither language. Their own messages stay in their words."""
    run(chat, "m5", "hi", HI, "9812500005")

    stored = loads(conversation.get("m5")["messages"], [])
    bot = " ".join(m.get("text", "") for m in stored if m.get("role") == "bot")
    assert "मोबाइल" in bot, bot
    assert "mobile number" not in bot.lower()

    typed = " ".join(m.get("text", "") for m in stored if m.get("role") == "user")
    assert "अहमदाबाद" in typed, typed


def test_the_customer_record_is_not_translated(chat):
    run(chat, "m6", "hi", HI, "9812500006")

    record = intents.list_intents(category="PLY")[0]
    assert record["city"] == "Ahmedabad"
    # No grade was stated, and the intent keeps it that way: that is what
    # lets this buyer pool into whichever grade group already exists.
    # The group resolves it to the default only when one is created.
    assert record["product"] == "18 mm 8 x 4 ft Plywood"
    assert groups.spec_of(groups.list_groups(category="PLY")[0])["grade"] == "MR"


# --------------------------------------------------------------------------- #
# understanding Hindi input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("typed,city", [
    ("अहमदाबाद", "Ahmedabad"),
    ("मुंबई", "Mumbai"),
    ("दिल्ली", "Delhi"),
    ("बेंगलुरु", "Bengaluru"),
])
def test_a_city_typed_in_hindi_is_stored_in_english(typed, city):
    assert rules.extract_city(typed) == city


@pytest.mark.parametrize("typed,number", [("१२०", 120), ("५०", 50), ("१०००", 1000)])
def test_devanagari_digits_are_read_as_numbers(typed, number):
    assert rules.extract(typed, {"category": "PLY"}, expecting="quantity") == {
        "quantity": number
    }


@pytest.mark.parametrize("typed,value", [
    ("हाँ", True), ("हां", True), ("जी", True), ("बिल्कुल", True),
    ("नहीं", False), ("नही", False),
])
def test_yes_and_no_are_understood_in_hindi(typed, value):
    assert rules.extract_bool(typed) is value


def test_a_hindi_name_is_accepted_first_time(chat):
    """A character class of A-Z strips a Devanagari name to nothing and asks
    again forever."""
    from app.utils import clean_name

    assert clean_name("हविश शाह") == "हविश शाह"
    assert rules.extract("हविश", {}, expecting="name") == {"name": "हविश"}


def test_an_unknown_area_in_hindi_is_kept(chat):
    assert rules.extract("सैटेलाइट", {"city": "Ahmedabad"}, expecting="area") == {
        "area": "सैटेलाइट"
    }


# --------------------------------------------------------------------------- #
# coverage and fallback
# --------------------------------------------------------------------------- #
#: Said the same way in Hindi: brand names, trade codes and standards. A buyer
#: asks for BWR plywood and Fevicol in either language, so "translating" these
#: would only make them harder to recognise.
UNTRANSLATED = {
    "MR", "BWR", "BWP Marine", "PVC", "ABS", "Acrylic",
    "Century", "Greenply", "Kitply", "Merino", "Archidply", "Greenlam",
    "Royale Touche", "Fevicol", "Astral Resibond", "Euro 7000", "Jubilant",
    "₹1,000 - ₹2,000",
}


def test_every_question_and_chip_in_the_live_flow_has_hindi(chat):
    """A half-translated conversation is worse than an English one."""
    from app import catalog

    missing = []
    for key in ["PLY"] + [a.category_key for a in catalog.get("PLY").addons]:
        category = catalog.get(key)
        strings = [category.quantity_question, category.intro, category.addon_prompt]
        strings += [s.question for s in category.slots]
        strings += [c for s in category.slots for c in s.chips if "{" not in c]
        for text in strings:
            if not text or text in UNTRANSLATED:
                continue
            # Numbers and measurements are handled by the unit pass.
            if i18n.t(text, "hi") == text and not text[:1].isdigit():
                missing.append(f"{key}: {text[:60]}")
    assert not missing, "no Hindi for:\n" + "\n".join(missing)


@pytest.mark.parametrize("text,expected", [
    ("18 mm", "18 मिमी"),
    ("8 x 4 ft", "8 x 4 फ़ुट"),
    ("120 sheets", "120 शीट"),
    ("2 inch", "2 इंच"),
    ("5 kg", "5 किलो"),
])
def test_measurements_are_said_in_hindi_without_a_dictionary_entry(text, expected):
    assert i18n.t(text, "hi") == expected


def test_an_untranslated_string_falls_back_to_english():
    """Missing a translation must degrade, never blank out."""
    assert i18n.t("Something nobody translated", "hi") == "Something nobody translated"
    assert i18n.t("Not Sure", "en") == "Not Sure"


def test_group_codes_and_urls_are_never_translated():
    card = {"type": "status", "url": "http://x/my/ABC", "group_code": "PLY-AHM-001",
            "title": "Your requests"}
    out = i18n.localise(card, "hi")
    assert out["url"] == "http://x/my/ABC"
    assert out["group_code"] == "PLY-AHM-001"
    assert out["title"] == "आपकी रिक्वेस्ट"


# --------------------------------------------------------------------------- #
# the companion products
# --------------------------------------------------------------------------- #
def test_companion_products_are_asked_in_hindi_too(chat):
    replies = run(chat, "m7", "hi", HI, "9812500007", picks=["nails"])

    blurb = said(replies)
    assert "कील का साइज़" in blurb, blurb
    assert "What size nails" not in blurb

    nails = groups.list_groups(category="NAILS")
    assert len(nails) == 1
    # Still canonical, so it pools with an English buyer's nails.
    assert groups.spec_of(nails[0])["nail_type"] == "Wire"
