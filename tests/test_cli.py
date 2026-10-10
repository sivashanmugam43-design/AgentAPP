import pytest

from main import parse_args


def test_defaults_run_everything():
    a = parse_args([])
    assert (a.stage, a.district, a.limit) == ("all", None, None)


def test_test_run_args():
    a = parse_args(["--district", "46", "--limit", "5", "--stage", "3"])
    assert (a.stage, a.district, a.limit) == ("3", "46", 5)


def test_categories_stage_args():
    a = parse_args(["--stage", "categories", "--category", "7", "--limit", "5"])
    assert (a.stage, a.category, a.limit) == ("categories", 7, 5)


@pytest.mark.parametrize("argv", [
    ["--stage", "4"],
    ["--district", "chennai"],
    ["--limit", "0"],
    ["--category", "23"],
])
def test_bad_args_rejected(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)
