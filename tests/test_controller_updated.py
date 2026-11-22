import pytest

from mogi_tracker import __version__, settings
from mogi_tracker.controller import Controller


@pytest.fixture
def check(monkeypatch):
    monkeypatch.setattr(settings, "save", lambda s: dict(s))

    def run(last, first_run=False):
        c = Controller.__new__(Controller)     # only the version check
        c.settings = {"last_version": last}
        return c._just_updated(first_run), c.settings["last_version"]
    return run


def test_update_notice_only_on_the_first_start_of_a_newer_version(check):
    assert check("0.9.0") == (True, __version__)
    assert check(__version__) == (False, __version__)
    assert check("") == (True, __version__)                    # settings from before this (1.0.0 - 1.0.2)
    assert check("", first_run=True) == (False, __version__)   # fresh install
    assert check("99.0.0") == (False, __version__)             # downgrade
