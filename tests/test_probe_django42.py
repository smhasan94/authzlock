import django


def test_probe_requires_django_5() -> None:
    assert django.VERSION[0] >= 5
