#!/usr/bin/env python3
"""Offline regression test for the shared learning card architecture."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
ENGLISH_DIR = CODEX_HOME / "skills" / "family-english-cards" / "scripts"
CONCEPT_DIR = CODEX_HOME / "skills" / "concept-fables" / "scripts"
HUB_DIR = CODEX_HOME / "learning-hub" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_value(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def iter_buttons(value):
    if isinstance(value, dict):
        if value.get("tag") == "button":
            yield value
        for child in value.values():
            yield from iter_buttons(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_buttons(child)


def encoded_size(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="learning-hub-test-") as temporary:
        os.environ["CODEX_HOME"] = temporary
        temp_home = Path(temporary)
        sys.path.insert(0, str(ENGLISH_DIR))
        english = load_module("english_flow_test", ENGLISH_DIR / "flow.py")
        concept = load_module("concept_flow_test", CONCEPT_DIR / "flow.py")
        hub = load_module("learning_hub_test", HUB_DIR / "hub.py")

        today = date.today()
        english_session = {
            "date": today.isoformat(),
            "view_id": 4,
            "runtime": {
                "queue": [{"id": "family-001", "kind": "new", "attempt": 1, "is_retry": False}],
                "current_index": 0,
                "completed": False,
                "next_ready": False,
                "processed_actions": [],
                "rating_counts": {"会": 0, "模糊": 0, "不会": 0},
            },
        }
        question = english.build_question_card(english_session)
        answer = english.build_answer_card(english_session)
        summary = english.summary_card(english_session)
        for card in (question, answer, summary):
            assert_value(encoded_size(card) < 30000, "English card exceeds 30 KB")
        question_values = [button["behaviors"][0]["value"] for button in iter_buttons(question)]
        assert_value(any(value.get("module") == "english" and value.get("view_id") == 4 for value in question_values), "English actions missing module/view")
        assert_value(any(value.get("module") == "hub" and value.get("target") == "concept_fable" for value in question_values), "English switch button missing")
        try:
            english.callback_card(english_session, "family-001", "reveal", english.turn_id(english_session), view_id=3)
        except english.FlowError:
            pass
        else:
            raise AssertionError("stale English card was accepted")

        concept.ensure_dirs()
        concept_session = concept.create_session(today)
        concept_bank = concept.load_bank()
        for item in concept_bank.values():
            assert_value(len(item["story"]) >= 700, "Concept story is shorter than 700 characters: {}".format(item["id"]))
            assert_value(item["concept"].lower() not in item["story"].lower(), "Concept name leaked into story: {}".format(item["id"]))
            assert_value(sum(1 for option in item["options"] if option.get("correct")) == 1, "Concept quiz must have one correct answer: {}".format(item["id"]))

        story = concept_bank[concept_session["story_id"]]
        story_card = concept.story_card(concept_session, story)
        quiz_card = concept.quiz_card(concept_session, story)
        concept_session["page"] = "result"
        concept_session["answer"] = {"choice": next(o["id"] for o in story["options"] if o["correct"]), "correct": True}
        result_card = concept.result_card(concept_session, story)
        for card in (story_card, quiz_card, result_card):
            assert_value(encoded_size(card) < 30000, "Concept card exceeds 30 KB")
        story_values = [button["behaviors"][0]["value"] for button in iter_buttons(story_card)]
        assert_value(any(value.get("module") == "concept_fable" and value.get("view_id") == 1 for value in story_values), "Concept actions missing module/view")
        assert_value(any(value.get("module") == "hub" and value.get("target") == "english" for value in story_values), "Concept switch button missing")

        concept_session["page"] = "story"
        concept_session["answer"] = None
        concept_session["completed"] = False
        concept.save_session(concept_session)
        started = concept.callback_card(concept_session, concept_session["story_id"], "start_quiz", concept_session["view_id"])
        assert_value(started["card"] == concept.quiz_card(concept_session, story), "Concept quiz transition failed")
        correct_choice = next(option["id"] for option in story["options"] if option["correct"])
        answered = concept.callback_card(concept_session, concept_session["story_id"], "answer", concept_session["view_id"], correct_choice)
        assert_value(answered["toast"].get("i18n") is not None and len(answered["toast"]["i18n"]) == 8, "Localized answer toast is incomplete")
        assert_value(answered["card"] == concept.result_card(concept_session, story), "Concept result transition failed")

        hub_card = hub.build_card(today)
        assert_value(encoded_size(hub_card) < 30000, "Learning center card exceeds 30 KB")
        hub_values = [button["behaviors"][0]["value"] for button in iter_buttons(hub_card)]
        assert_value({value.get("target") for value in hub_values} == {"english", "concept_fable"}, "Learning center targets are incomplete")

    print("offline learning-hub smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
