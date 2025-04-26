# YNAB Unlinked

YNAB Unlinked is a CLI tools that allows creating transactions in your YNAB account from any input file.

You only need a [Parser](src/ynab_unlinked/parser.py) that knows how to parse your specific file and the tool will take care of the rest.

## Usage

Just run

```bash
hatch run cli --help
```

## Supported Parsers

At the moment, the following parsers are supported:

- [TXT from Banco Sabadell](/src/ynab_unlinked/parsers/sabadell.py)

## License

`ynab-unlinked` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
