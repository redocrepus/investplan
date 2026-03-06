"""Dialog for editing an investment bucket with multi-trigger support."""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QListWidget, QLabel,
)
from models.bucket import (
    InvestmentBucket, BucketTrigger, TriggerType, SellSubtype, BuySubtype,
    CostBasisMethod,
)
from utils.currency_list import COMMON_CURRENCIES
from utils.volatility import VolatilityProfile


class TriggerDialog(QDialog):
    """Dialog for adding/editing a single trigger."""

    def __init__(
        self,
        trigger: Optional[BucketTrigger] = None,
        existing_bucket_names: Optional[list[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Bucket Trigger")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._type = QComboBox()
        self._type.addItems([t.value for t in TriggerType])
        self._type.setToolTip("Sell: sell this bucket when condition is met. Buy: buy this bucket when condition is met.")
        self._type.currentTextChanged.connect(self._on_type_changed)
        form.addRow("Type:", self._type)

        self._subtype = QComboBox()
        self._subtype.setToolTip("Trigger condition subtype")
        form.addRow("Subtype:", self._subtype)

        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.01, 10000)
        self._threshold.setDecimals(2)
        self._threshold.setToolTip(
            "Threshold value. For Take Profit: ratio of actual/target growth. "
            "For Share Exceeds/Below: portfolio share %. For Discount: discount %."
        )
        form.addRow("Threshold:", self._threshold)

        self._target_bucket = QComboBox()
        self._target_bucket.setEditable(True)
        self._target_bucket.addItem("")
        self._target_bucket.setToolTip(
            "Sell triggers: target bucket to buy with proceeds. "
            "Buy triggers: source bucket to sell from to fund the purchase."
        )
        for name in (existing_bucket_names or []):
            self._target_bucket.addItem(name)
        form.addRow("Target/Source Bucket:", self._target_bucket)

        self._frequency = QComboBox()
        self._frequency.addItems(["monthly", "yearly"])
        self._frequency.setToolTip("How often to check this trigger")
        form.addRow("Frequency:", self._frequency)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Initialize subtypes
        self._on_type_changed(self._type.currentText())

        if trigger:
            self._load(trigger)
        else:
            self._threshold.setValue(1.5)

    def _on_type_changed(self, type_text: str):
        self._subtype.clear()
        if type_text == TriggerType.SELL.value:
            self._subtype.addItems([s.value for s in SellSubtype])
        else:
            self._subtype.addItems([s.value for s in BuySubtype])

    def _load(self, t: BucketTrigger):
        self._type.setCurrentText(t.trigger_type.value)
        self._on_type_changed(t.trigger_type.value)
        self._subtype.setCurrentText(t.subtype)
        self._threshold.setValue(t.threshold_pct)
        if t.target_bucket:
            self._target_bucket.setCurrentText(t.target_bucket)
        self._frequency.setCurrentText(t.frequency)

    def get_trigger(self) -> BucketTrigger:
        target = self._target_bucket.currentText().strip() or None
        return BucketTrigger(
            trigger_type=TriggerType(self._type.currentText()),
            subtype=self._subtype.currentText(),
            threshold_pct=self._threshold.value(),
            target_bucket=target,
            frequency=self._frequency.currentText(),
        )


class BucketDialog(QDialog):
    def __init__(
        self,
        bucket: Optional[InvestmentBucket] = None,
        existing_bucket_names: Optional[list[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Investment Bucket")
        self._existing_names = existing_bucket_names or []
        self._triggers: list[BucketTrigger] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._name = QLineEdit()
        self._name.setToolTip("Unique name for this bucket")
        form.addRow("Name:", self._name)

        self._currency = QComboBox()
        self._currency.addItems(COMMON_CURRENCIES)
        self._currency.setEditable(True)
        self._currency.setToolTip("Currency for this bucket")
        form.addRow("Currency:", self._currency)

        self._initial_price = QDoubleSpinBox()
        self._initial_price.setRange(0.0001, 1e9)
        self._initial_price.setDecimals(4)
        self._initial_price.setToolTip("Initial price per unit in bucket currency")
        form.addRow("Initial Price:", self._initial_price)

        self._initial_amount = QDoubleSpinBox()
        self._initial_amount.setRange(0, 1e12)
        self._initial_amount.setDecimals(2)
        self._initial_amount.setToolTip("Initial holding in bucket currency")
        form.addRow("Initial Amount:", self._initial_amount)

        self._growth_min = QDoubleSpinBox()
        self._growth_min.setRange(-100, 1000)
        self._growth_min.setDecimals(1)
        self._growth_min.setSuffix("%")
        self._growth_min.setToolTip("Minimum expected yearly growth")
        form.addRow("Growth Min:", self._growth_min)

        self._growth_max = QDoubleSpinBox()
        self._growth_max.setRange(-100, 1000)
        self._growth_max.setDecimals(1)
        self._growth_max.setSuffix("%")
        self._growth_max.setToolTip("Maximum expected yearly growth")
        form.addRow("Growth Max:", self._growth_max)

        self._growth_avg = QDoubleSpinBox()
        self._growth_avg.setRange(-100, 1000)
        self._growth_avg.setDecimals(1)
        self._growth_avg.setSuffix("%")
        self._growth_avg.setToolTip("Average expected yearly growth")
        form.addRow("Growth Avg:", self._growth_avg)

        self._volatility = QComboBox()
        self._volatility.addItems([v.value for v in VolatilityProfile])
        self._volatility.setToolTip("Volatility profile for price movement")
        form.addRow("Volatility:", self._volatility)

        self._fee = QDoubleSpinBox()
        self._fee.setRange(0, 50)
        self._fee.setDecimals(2)
        self._fee.setSuffix("%")
        self._fee.setToolTip("Buy/sell fee percentage applied on each transaction")
        form.addRow("Buy/Sell Fee:", self._fee)

        self._cost_basis = QComboBox()
        self._cost_basis.addItems([m.value.upper() for m in CostBasisMethod])
        self._cost_basis.setToolTip(
            "Capital gains cost basis method: FIFO (first in first out), "
            "LIFO (last in first out), or AVCO (average cost)"
        )
        form.addRow("Cost Basis Method:", self._cost_basis)

        self._target_growth = QDoubleSpinBox()
        self._target_growth.setRange(-100, 1000)
        self._target_growth.setDecimals(1)
        self._target_growth.setSuffix("%")
        self._target_growth.setToolTip("Target growth for rebalancing triggers")
        form.addRow("Target Growth:", self._target_growth)

        # --- Expense coverage section ---
        exp_group = QGroupBox("Expense Coverage")
        exp_form = QFormLayout(exp_group)

        self._spending_priority = QSpinBox()
        self._spending_priority.setRange(0, 100)
        self._spending_priority.setToolTip(
            "Lower number = sell first for expenses. All buckets are eligible "
            "for selling to cover expenses, in this priority order."
        )
        exp_form.addRow("Spending Priority:", self._spending_priority)

        self._cash_floor = QDoubleSpinBox()
        self._cash_floor.setRange(0, 120)
        self._cash_floor.setDecimals(1)
        self._cash_floor.setSuffix(" months")
        self._cash_floor.setToolTip(
            "Keep at least this many months of expenses in this bucket "
            "when selling to cover expenses. If hit, cascade to next bucket."
        )
        exp_form.addRow("Cash Floor:", self._cash_floor)

        self._runaway = QDoubleSpinBox()
        self._runaway.setRange(0, 120)
        self._runaway.setDecimals(1)
        self._runaway.setSuffix(" months")
        self._runaway.setToolTip(
            "Required months of expenses runway before trigger-based selling "
            "(to avoid selling in a market crash when price is low)"
        )
        exp_form.addRow("Required Runaway:", self._runaway)

        layout.addWidget(exp_group)

        # --- Triggers section ---
        trig_group = QGroupBox("Triggers")
        trig_layout = QVBoxLayout(trig_group)

        self._trigger_list = QListWidget()
        trig_layout.addWidget(self._trigger_list)

        trig_btn_row = QHBoxLayout()
        self._btn_add_trigger = QPushButton("Add")
        self._btn_edit_trigger = QPushButton("Edit")
        self._btn_remove_trigger = QPushButton("Remove")
        for btn in (self._btn_add_trigger, self._btn_edit_trigger, self._btn_remove_trigger):
            trig_btn_row.addWidget(btn)
        trig_layout.addLayout(trig_btn_row)

        self._btn_add_trigger.clicked.connect(self._add_trigger)
        self._btn_edit_trigger.clicked.connect(self._edit_trigger)
        self._btn_remove_trigger.clicked.connect(self._remove_trigger)

        layout.addWidget(trig_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if bucket:
            self._load(bucket)
        else:
            self._initial_price.setValue(100)
            self._growth_avg.setValue(7)
            self._target_growth.setValue(7)
            self._runaway.setValue(6)

    def _trigger_display(self, t: BucketTrigger) -> str:
        target = f" -> {t.target_bucket}" if t.target_bucket else ""
        return f"{t.trigger_type.value}/{t.subtype}: {t.threshold_pct}{target} ({t.frequency})"

    def _refresh_triggers(self):
        self._trigger_list.clear()
        for t in self._triggers:
            self._trigger_list.addItem(self._trigger_display(t))

    def _add_trigger(self):
        dlg = TriggerDialog(
            existing_bucket_names=self._existing_names,
            parent=self,
        )
        if dlg.exec():
            self._triggers.append(dlg.get_trigger())
            self._refresh_triggers()

    def _edit_trigger(self):
        row = self._trigger_list.currentRow()
        if row < 0:
            return
        dlg = TriggerDialog(
            trigger=self._triggers[row],
            existing_bucket_names=self._existing_names,
            parent=self,
        )
        if dlg.exec():
            self._triggers[row] = dlg.get_trigger()
            self._refresh_triggers()

    def _remove_trigger(self):
        row = self._trigger_list.currentRow()
        if row < 0:
            return
        self._triggers.pop(row)
        self._refresh_triggers()

    def _load(self, b: InvestmentBucket):
        self._name.setText(b.name)
        idx = self._currency.findText(b.currency)
        if idx >= 0:
            self._currency.setCurrentIndex(idx)
        else:
            self._currency.setCurrentText(b.currency)
        self._initial_price.setValue(b.initial_price)
        self._initial_amount.setValue(b.initial_amount)
        self._growth_min.setValue(b.growth_min_pct)
        self._growth_max.setValue(b.growth_max_pct)
        self._growth_avg.setValue(b.growth_avg_pct)
        idx = self._volatility.findText(b.volatility.value)
        if idx >= 0:
            self._volatility.setCurrentIndex(idx)
        self._fee.setValue(b.buy_sell_fee_pct)
        self._cost_basis.setCurrentText(b.cost_basis_method.value.upper())
        self._target_growth.setValue(b.target_growth_pct)
        self._spending_priority.setValue(b.spending_priority)
        self._cash_floor.setValue(b.cash_floor_months)
        self._runaway.setValue(b.required_runaway_months)
        self._triggers = list(b.triggers)
        self._refresh_triggers()

    def get_bucket(self) -> InvestmentBucket:
        cost_basis_text = self._cost_basis.currentText().lower()
        return InvestmentBucket(
            name=self._name.text().strip(),
            currency=self._currency.currentText(),
            initial_price=self._initial_price.value(),
            initial_amount=self._initial_amount.value(),
            growth_min_pct=self._growth_min.value(),
            growth_max_pct=self._growth_max.value(),
            growth_avg_pct=self._growth_avg.value(),
            volatility=VolatilityProfile(self._volatility.currentText()),
            buy_sell_fee_pct=self._fee.value(),
            cost_basis_method=CostBasisMethod(cost_basis_text),
            target_growth_pct=self._target_growth.value(),
            spending_priority=self._spending_priority.value(),
            cash_floor_months=self._cash_floor.value(),
            required_runaway_months=self._runaway.value(),
            triggers=list(self._triggers),
        )
