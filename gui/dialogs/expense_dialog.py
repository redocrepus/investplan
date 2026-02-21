"""Dialogs for editing expense periods and one-time expenses."""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox,
    QDialogButtonBox, QVBoxLayout,
)
from models.expense import ExpensePeriod, OneTimeExpense
from utils.volatility import ExpenseVolatility


class ExpensePeriodDialog(QDialog):
    def __init__(self, period: Optional[ExpensePeriod] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Expense Period")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._start_year = QSpinBox()
        self._start_year.setRange(1, 100)
        self._start_year.setToolTip("Simulation year when this period starts")
        form.addRow("Start Year:", self._start_year)

        self._start_month = QSpinBox()
        self._start_month.setRange(1, 12)
        self._start_month.setToolTip("Month (1-12) when this period starts")
        form.addRow("Start Month:", self._start_month)

        self._amount_min = QDoubleSpinBox()
        self._amount_min.setRange(0, 1e9)
        self._amount_min.setDecimals(2)
        self._amount_min.setToolTip("Minimum monthly expense amount")
        form.addRow("Amount Min:", self._amount_min)

        self._amount_max = QDoubleSpinBox()
        self._amount_max.setRange(0, 1e9)
        self._amount_max.setDecimals(2)
        self._amount_max.setToolTip("Maximum monthly expense amount")
        form.addRow("Amount Max:", self._amount_max)

        self._amount_avg = QDoubleSpinBox()
        self._amount_avg.setRange(0, 1e9)
        self._amount_avg.setDecimals(2)
        self._amount_avg.setToolTip("Average monthly expense amount")
        form.addRow("Amount Average:", self._amount_avg)

        self._volatility = QComboBox()
        self._volatility.addItems([v.value for v in ExpenseVolatility])
        self._volatility.setToolTip("Expense volatility during this period")
        form.addRow("Volatility:", self._volatility)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if period:
            self._start_year.setValue(period.start_year)
            self._start_month.setValue(period.start_month)
            self._amount_min.setValue(period.amount_min)
            self._amount_max.setValue(period.amount_max)
            self._amount_avg.setValue(period.amount_avg)
            idx = self._volatility.findText(period.volatility.value)
            if idx >= 0:
                self._volatility.setCurrentIndex(idx)

    def get_period(self) -> ExpensePeriod:
        return ExpensePeriod(
            start_month=self._start_month.value(),
            start_year=self._start_year.value(),
            amount_min=self._amount_min.value(),
            amount_max=self._amount_max.value(),
            amount_avg=self._amount_avg.value(),
            volatility=ExpenseVolatility(self._volatility.currentText()),
        )


class OneTimeExpenseDialog(QDialog):
    def __init__(self, expense: Optional[OneTimeExpense] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("One-Time Expense")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._year = QSpinBox()
        self._year.setRange(1, 100)
        self._year.setToolTip("Simulation year of the expense")
        form.addRow("Year:", self._year)

        self._month = QSpinBox()
        self._month.setRange(1, 12)
        self._month.setToolTip("Month (1-12) of the expense")
        form.addRow("Month:", self._month)

        self._amount = QDoubleSpinBox()
        self._amount.setRange(0, 1e9)
        self._amount.setDecimals(2)
        self._amount.setToolTip("Expense amount")
        form.addRow("Amount:", self._amount)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if expense:
            self._year.setValue(expense.year)
            self._month.setValue(expense.month)
            self._amount.setValue(expense.amount)

    def get_expense(self) -> OneTimeExpense:
        return OneTimeExpense(
            month=self._month.value(),
            year=self._year.value(),
            amount=self._amount.value(),
        )
