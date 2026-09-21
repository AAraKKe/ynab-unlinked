"""Tests for the selection tree used by the reconcile TUI.

The reconcile screen builds one ``Choice`` per account with one child per
transaction. Selecting an account must drag its transactions along, except for
the uncleared ones, which the app pins with a forced selection.
"""

import pytest

from ynab_unlinked.choices import Choice


def account_with_transactions() -> Choice:
    return Choice(id="account", title="Checking", choices=["First", "Second"])


def test_string_choices_become_children_with_derived_ids():
    account = account_with_transactions()

    assert [(c.id, c.title) for c in account.choices] == [
        ("account-0", "First"),
        ("account-1", "Second"),
    ]
    assert all(child.parent is account for child in account.choices)


def test_only_string_choices_consume_a_generated_id():
    prebuilt = Choice(id="transaction-1")

    account = Choice(id="account", choices=[prebuilt, "From string"])

    assert [c.id for c in account.choices] == ["transaction-1", "account-0"]
    assert prebuilt.parent is account


def test_selecting_a_parent_selects_every_descendant():
    account = account_with_transactions()
    subtransaction = Choice(id="split", parent=account.choices[0])
    account.choices[0].choices.append(subtransaction)

    account.select()

    assert all(child.is_selected for child in account.choices)
    assert subtransaction.is_selected


def test_deselecting_a_parent_keeps_the_children_own_selection():
    account = account_with_transactions()
    account.choices[0].select()
    account.select()

    account.deselect()

    assert account.choices[0].is_selected
    assert not account.choices[1].is_selected


@pytest.mark.parametrize(
    ("forced", "parent_selected", "expected"),
    [
        pytest.param(False, True, False, id="forced off inside a selected account"),
        pytest.param(True, False, True, id="forced on inside an unselected account"),
        pytest.param(False, False, False, id="forced off on its own"),
        pytest.param(True, True, True, id="forced on inside a selected account"),
    ],
)
def test_forced_selection_wins_over_the_parent(forced: bool, parent_selected: bool, expected: bool):
    account = account_with_transactions()
    uncleared = account.choices[0]
    uncleared.enable_forced_selected(forced)

    if parent_selected:
        account.select()

    assert uncleared.is_selected is expected


def test_forced_selection_makes_toggling_a_no_op():
    uncleared = Choice(id="transaction")
    uncleared.enable_forced_selected(False)

    uncleared.toggle_selection()

    assert not uncleared.selected
    assert not uncleared.is_selected


def test_disabling_the_forced_selection_restores_the_parent_inheritance():
    account = account_with_transactions()
    uncleared = account.choices[0]
    uncleared.enable_forced_selected(False)
    account.select()

    uncleared.disable_forced_selected()

    assert uncleared.is_selected


def test_a_forced_selection_of_none_leaves_the_normal_logic_in_place():
    # `build_choices` passes None for cleared transactions, meaning "not forced"
    cleared = Choice(id="transaction")
    cleared.enable_forced_selected(None)

    cleared.toggle_selection()

    assert cleared.is_forced_selected() is False
    assert cleared.is_selected


@pytest.mark.parametrize(
    ("select_account", "select_child", "expected"),
    [
        pytest.param(False, False, False, id="nothing is selected"),
        pytest.param(False, True, True, id="a transaction was picked on its own"),
        pytest.param(True, False, True, id="the whole account was picked"),
    ],
)
def test_has_selected_choices_accounts_for_inherited_selection(
    select_account: bool, select_child: bool, expected: bool
):
    account = account_with_transactions()
    if select_account:
        account.select()
    if select_child:
        account.choices[0].select()

    assert account.has_selected_choices is expected


def test_to_dict_flattens_the_whole_tree():
    account = account_with_transactions()
    split = Choice(id="split", parent=account.choices[1])
    account.choices[1].choices.append(split)

    flattened = account.to_dict()

    assert set(flattened) == {"account", "account-0", "account-1", "split"}
    assert flattened["split"] is split


@pytest.mark.xfail(
    reason=(
        "choices.py:100 guards the memoisation with hasattr(self, '__dict') but stores the value "
        "in the name-mangled _Choice__dict, so the cache is never read"
    ),
    strict=True,
)
def test_to_dict_is_memoised():
    account = account_with_transactions()

    first = account.to_dict()
    account.choices.append(Choice(id="late", parent=account))

    assert account.to_dict() is first


@pytest.mark.parametrize(
    "attribute",
    [
        pytest.param("transaction", id="a choice built without a transaction"),
        pytest.param("account", id="a choice built without an account"),
    ],
)
def test_accessing_missing_payload_names_the_choice(attribute: str):
    choice = Choice(id="transaction-42")

    with pytest.raises(ValueError, match="transaction-42"):
        getattr(choice, attribute)
