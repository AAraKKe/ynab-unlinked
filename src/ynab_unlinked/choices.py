from __future__ import annotations

from ynab import Account, TransactionDetail


class Choice:
    def __init__(
        self,
        id: str,
        transaction: TransactionDetail | None = None,
        account: Account | None = None,
        title: str = "",
        choices: list[str | Choice] | None = None,
        selected=False,
        parent: Choice | None = None,
    ):
        self.id = id
        self.title = title
        self._transaction = transaction
        self._account = account
        self.choices: list[Choice] = []
        self.selected = selected
        self._forced_selection: bool | None = None
        self.parent = parent
        if choices is not None:
            n = 0
            for choice in choices:
                if isinstance(choice, str):
                    self.choices.append(Choice(title=choice, id=f"{self.id}-{n}", parent=self))
                    n += 1
                else:
                    choice.parent = self
                    self.choices.append(choice)

    @property
    def transaction(self) -> TransactionDetail:
        if self._transaction is None:
            raise ValueError(
                f"Transaction is needed in choice {self.id!r} but has not been provided."
            )
        return self._transaction

    @property
    def account(self) -> Account:
        if self._account is None:
            raise ValueError(f"Account is needed in choice {self.id!r} but has not been provided.")
        return self._account

    def has_choices(self) -> bool:
        return len(self.choices) > 0

    def select(self):
        """Mark the choice as selected. This implicitely select all child choices."""
        self.selected = True

    def deselect(self):
        """Marks choice as not selected. Child choices keep their value."""
        self.selected = False

    def toggle_selection(self):
        """Toggles the value of the own selected flag."""
        if self.is_forced_selected():
            return
        self.selected = not self.selected

    @property
    def is_selected(self) -> bool:
        """If the choice has a parent that is selected, it is considered selected."""
        if self.is_forced_selected():
            assert self._forced_selection is not None, (
                "Cannot have forced seleciton and not have it set"
            )
            return self._forced_selection

        if self.parent is not None and self.parent.is_selected:
            return True
        return self.selected

    def enable_forced_selected(self, value: bool | None):
        self._forced_selection = value

    def disable_forced_selected(self):
        self._forced_selection = None

    def is_forced_selected(self) -> bool:
        """Whether we need to ignore selected logic and apply any forced selection enforced from the outside"""
        return self._forced_selection is not None

    @property
    def has_selected_choices(self) -> bool:
        """Returns whether or not any of the inner choices is selected"""
        return any(child.is_selected for child in self.choices)

    def to_dict(self) -> dict[str, Choice]:
        """
        Return a dictionary where the key is the id of the Choice and the value is the choice.

        This dictionary flattens out all children choices.
        """
        if not hasattr(self, "__dict"):
            dict_value: dict[str, Choice] = {self.id: self}

            for choice in self.choices:
                dict_value |= choice.to_dict()

            self.__dict = dict_value

        return self.__dict
