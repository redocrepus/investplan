"""Expense panel — expense periods list + one-time expenses."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import pyqtSignal
from models.config import SimConfig
from models.expense import ExpensePeriod, OneTimeExpense
from gui.dialogs.expense_dialog import ExpensePeriodDialog, OneTimeExpenseDialog


class ExpensePanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, config: SimConfig, parent=None):
        super().__init__("Expenses", parent)
        layout = QVBoxLayout(self)

        # --- Expense Periods ---
        layout.addWidget(QGroupBox_label("Expense Periods"))
        self._period_list = QListWidget()
        layout.addWidget(self._period_list)

        btn_row = QHBoxLayout()
        self._btn_add_period = QPushButton("Add")
        self._btn_edit_period = QPushButton("Edit")
        self._btn_remove_period = QPushButton("Remove")
        btn_row.addWidget(self._btn_add_period)
        btn_row.addWidget(self._btn_edit_period)
        btn_row.addWidget(self._btn_remove_period)
        layout.addLayout(btn_row)

        self._btn_add_period.clicked.connect(self._add_period)
        self._btn_edit_period.clicked.connect(self._edit_period)
        self._btn_remove_period.clicked.connect(self._remove_period)

        # --- One-Time Expenses ---
        layout.addWidget(QGroupBox_label("One-Time Expenses"))
        self._ote_list = QListWidget()
        layout.addWidget(self._ote_list)

        btn_row2 = QHBoxLayout()
        self._btn_add_ote = QPushButton("Add")
        self._btn_edit_ote = QPushButton("Edit")
        self._btn_remove_ote = QPushButton("Remove")
        btn_row2.addWidget(self._btn_add_ote)
        btn_row2.addWidget(self._btn_edit_ote)
        btn_row2.addWidget(self._btn_remove_ote)
        layout.addLayout(btn_row2)

        self._btn_add_ote.clicked.connect(self._add_ote)
        self._btn_edit_ote.clicked.connect(self._edit_ote)
        self._btn_remove_ote.clicked.connect(self._remove_ote)

        self._periods: list[ExpensePeriod] = []
        self._one_time: list[OneTimeExpense] = []

        self.read_from_config(config)

    def read_from_config(self, config: SimConfig):
        self._periods = list(config.expense_periods)
        self._one_time = list(config.one_time_expenses)
        self._refresh_lists()

    def write_to_config(self, config: SimConfig):
        config.expense_periods = list(self._periods)
        config.one_time_expenses = list(self._one_time)

    def _refresh_lists(self):
        self._period_list.clear()
        for p in self._periods:
            text = (f"Y{p.start_year} M{p.start_month}: "
                    f"{p.amount_avg:,.0f} [{p.amount_min:,.0f}-{p.amount_max:,.0f}] "
                    f"({p.volatility.value})")
            self._period_list.addItem(text)

        self._ote_list.clear()
        for o in self._one_time:
            self._ote_list.addItem(f"Y{o.year} M{o.month}: {o.amount:,.0f}")

    def _add_period(self):
        dlg = ExpensePeriodDialog(parent=self)
        if dlg.exec():
            self._periods.append(dlg.get_period())
            self._refresh_lists()
            self.changed.emit()

    def _edit_period(self):
        row = self._period_list.currentRow()
        if row < 0:
            return
        dlg = ExpensePeriodDialog(self._periods[row], parent=self)
        if dlg.exec():
            self._periods[row] = dlg.get_period()
            self._refresh_lists()
            self.changed.emit()

    def _remove_period(self):
        row = self._period_list.currentRow()
        if row < 0:
            return
        self._periods.pop(row)
        self._refresh_lists()
        self.changed.emit()

    def _add_ote(self):
        dlg = OneTimeExpenseDialog(parent=self)
        if dlg.exec():
            self._one_time.append(dlg.get_expense())
            self._refresh_lists()
            self.changed.emit()

    def _edit_ote(self):
        row = self._ote_list.currentRow()
        if row < 0:
            return
        dlg = OneTimeExpenseDialog(self._one_time[row], parent=self)
        if dlg.exec():
            self._one_time[row] = dlg.get_expense()
            self._refresh_lists()
            self.changed.emit()

    def _remove_ote(self):
        row = self._ote_list.currentRow()
        if row < 0:
            return
        self._one_time.pop(row)
        self._refresh_lists()
        self.changed.emit()


def QGroupBox_label(title: str):
    """Simple label-like group box (just a titled separator)."""
    from PyQt6.QtWidgets import QLabel
    lbl = QLabel(f"<b>{title}</b>")
    return lbl
