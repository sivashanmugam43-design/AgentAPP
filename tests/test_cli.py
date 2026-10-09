import pytest

from main import parse_args


def test_defaults_run_everything():
    a = parse_args([])
    assert (a.stage, a.district, a.limit, a.no_translate) == ("all", None, None, False)


def test_test_run_args():
    a = parse_args(["--district", "46", "--limit", "5", "--stage", "3"])
    assert (a.stage, a.district, a.limit) == ("3", "46", 5)


@pytest.mark.parametrize("argv", [
    ["--stage", "4"],
    ["--district", "chennai"],
    ["--limit", "0"],
])
def test_bad_args_rejected(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)
