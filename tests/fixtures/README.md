# Fixture Django projects

Each directory here is a small, self-contained Django project used to test extraction,
one per view style. The directory name is the style it covers, in snake case, for example
`function_views`, `class_views`, `drf_apiview`, `drf_viewsets`, `scenario_loosen`.

## Layout

Every fixture project must contain:

- `settings.py` with `ROOT_URLCONF`, `INSTALLED_APPS` and, where DRF is used,
  `REST_FRAMEWORK` defaults.
- `urls.py` as the root URLconf.
- One or more app packages holding the views the fixture exists to exercise.

Keep fixtures minimal: only the routes and views the tests assert on.

## How tests select a fixture

Extraction imports the target project in-process and Django can only be set up once per
process, so tests never import two fixtures into the same interpreter. The `run_extract`
helper (added in SHA-197) runs extraction in a subprocess with `PYTHONPATH` pointing at the
fixture directory and `DJANGO_SETTINGS_MODULE` set to `settings`, then returns the parsed
result. A test names the fixture it wants by directory name, for example
`run_extract("drf_viewsets")`.
