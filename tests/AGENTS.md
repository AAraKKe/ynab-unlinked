## Running tests

To run tests, run them throught the `dev` hatch environment:

```bash
hatch run dev:cov
```

It also support passing arguments as you would do with pytest:

```bash
hatch run dev:cov -k test_name
```

## Writing tests

Tests are written using the `pytest` framework. Make use of the `pytest` parameterization whenever possible to reduce the number of tests to be written.

If you need to have files to read at some point, you can use store them in the `tests/assets` directory. You can read them using the `assets` module in the `tests/helpers` directory.

## Working with timing

Some tests require to work with the current date. To do so, you can use the `today` fixture in the `tests/conftest.py` file. This uses the `freezegun` library to freeze the time to the date provided in the fixture.

```python
def test_something(today: datetime.datetime):
    assert today == datetime.datetime.now()
```