import transit
import api


def test_packages_import():
    assert transit.__doc__
    assert api.__doc__
