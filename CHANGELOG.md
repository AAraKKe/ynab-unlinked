# Release notes

Welcome to the official ledger for `ynab-unlinked`! Just like you meticulously track your transactions, we keep a detailed account of every change we make to the project. Here you'll find a transparent record of new features hitting the market, bugs we've written off, and all the behind-the-scenes investments in our codebase.

To help us keep our books in order, these release notes are automatically generated using the wonderful [Towncrier](https://github.com/twisted/towncrier).

<!-- towncrier release notes start -->

## ynab-unlinked 0.0.3 (2025-05-18)

### Fresh Out of the Feature Oven
* Add new reconcile command. Run `yul reconcile` and reconcile all your accounts in one go.

### Bugs Squashed, Peace Restored
* Fix reconcile command that would break when selecting all accounts

### For the Builders: Dev Experience Upgrades
* [[#4](https://github.com/AAraKKe/ynab-unlinked/issues/4)] Add towncrier support. This includes configuration, hatch environment and scripts.
* [[#5](https://github.com/AAraKKe/ynab-unlinked/issues/5)] Add GitHub workflow to validate PRs. This includes: format checkts, linter, type checker and towncrier validation
