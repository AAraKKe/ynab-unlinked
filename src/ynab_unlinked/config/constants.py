from ynab_unlinked.config.migrations import Version

TRANSACTION_GRACE_PERIOD_DAYS = 2

MAX_CONFIG_VERSION = 2
LATEST_VERSION = Version("Config", f"V{MAX_CONFIG_VERSION}")
