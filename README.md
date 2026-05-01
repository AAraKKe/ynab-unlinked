# YNAB Unlinked

YNAB Unlinked is a CLI tools that allows creating transactions in your YNAB account from any input file.

Want to know more? Check out our [wiki](https://github.com/AAraKKe/ynab-unlinked/wiki) where you'll find all the details on how to get started, add new entities, and make the most of this tool. It's pretty straightforward once you get the hang of it!

> [!IMPORTANT]
> This project just started and is open to contributions!

## Privacy

YNAB Unlinked runs entirely on your computer and only talks to YNAB's API. There is no telemetry and no data is shared with any third party. Your YNAB Personal Access Token is stored locally, in plaintext, in the standard config directory for your OS.

Run `yul privacy` to see what is stored on your machine and where, or read the full [privacy notice](./PRIVACY.md).

To wipe all locally stored data, including your API key, run:

```sh
yul config reset
```

## Disclaimer

We are not affiliated, associated, or in any way officially connected with YNAB or any of its subsidiaries or affiliates. The names "YNAB" and "You Need A Budget" are trademarks of their respective owners.

## License

`ynab-unlinked` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
