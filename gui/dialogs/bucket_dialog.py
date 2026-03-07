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
        self._bucket_names = existing_bucket_names or []
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
            "Threshold value (%). For Take Profit: percentage of target growth "
            "(e.g. 150 = fire when growth reaches 150% of target). "
            "For Share Exceeds/Below: portfolio share %. For Discount: discount %."
        )
        form.addRow("Threshold:", self._threshold)

        # --- Sell trigger: single target bucket ---
        self._target_bucket = QComboBox()
        self._target_bucket.setEditable(True)
        self._target_bucket.addItem("")
        self._target_bucket.setToolTip(
            "Target bucket to buy with sell proceeds."
        )
        for name in self._bucket_names:
            self._target_bucket.addItem(name)
        self._target_label = QLabel("Target Bucket:")
        form.addRow(self._target_label, self._target_bucket)

        # --- Buy trigger: ordered source bucket list ---
        self._source_group = QGroupBox("Source Buckets (priority order)")
        self._source_group.setToolTip(
            "Ordered list of buckets to sell from to fund this buy. "
            "Profitable sources are sold first; within unprofitable, this order is used."
        )
        source_layout = QVBoxLayout(self._source_group)
        self._source_list = QListWidget()
        source_layout.addWidget(self._source_list)
        source_btn_row = QHBoxLayout()
        self._source_add_combo = QComboBox()
        self._source_add_combo.addItems(self._bucket_names)
        self._source_add_combo.setEditable(True)
        source_btn_row.addWidget(self._source_add_combo)
        self._btn_source_add = QPushButton("Add")
        self._btn_source_remove = QPushButton("Remove")
        self._btn_source_up = QPushButton("Up")
        self._btn_source_down = QPushButton("Down")
        for btn in (self._btn_source_add, self._btn_source_remove,
                     self._btn_source_up, self._btn_source_down):
            source_btn_row.addWidget(btn)
        source_layout.addLayout(source_btn_row)
        layout.addWidget(self._source_group)

        self._btn_source_add.clicked.connect(self._add_source)
        self._btn_source_remove.clicked.connect(self._remove_source)
        self._btn_source_up.clicked.connect(self._move_source_up)
        self._btn_source_down.clicked.connect(self._move_source_down)

        self._period_months = QSpinBox()
        self._period_months.setRange(1, 120)
        self._period_months.setSuffix(" months")
        self._period_months.setToolTip(
            "Check this trigger every N months (1 = monthly, 12 = yearly)"
        )
        form.addRow("Period:", self._period_months)

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
        is_sell = type_text == TriggerType.SELL.value
        if is_sell:
            self._subtype.addItems([s.value for s in SellSubtype])
        else:
            self._subtype.addItems([s.value for s in BuySubtype])
        # Show/hide appropriate widgets
        self._target_label.setVisible(is_sell)
        self._target_bucket.setVisible(is_sell)
        self._source_group.setVisible(not is_sell)

    def _add_source(self):
        name = self._source_add_combo.currentText().strip()
        if name:
            self._source_list.addItem(name)

    def _remove_source(self):
        row = self._source_list.currentRow()
        if row >= 0:
            self._source_list.takeItem(row)

    def _move_source_up(self):
        row = self._source_list.currentRow()
        if row > 0:
            item = self._source_list.takeItem(row)
            self._source_list.insertItem(row - 1, item)
            self._source_list.setCurrentRow(row - 1)

    def _move_source_down(self):
        row = self._source_list.currentRow()
        if 0 <= row < self._source_list.count() - 1:
            item = self._source_list.takeItem(row)
            self._source_list.insertItem(row + 1, item)
            self._source_list.setCurrentRow(row + 1)

    def _load(self, t: BucketTrigger):
        self._type.setCurrentText(t.trigger_type.value)
        self._on_type_changed(t.trigger_type.value)
        self._subtype.setCurrentText(t.subtype)
        self._threshold.setValue(t.threshold_pct)
        if t.trigger_type == TriggerType.SELL:
            if t.target_bucket:
                self._target_bucket.setCurrentText(t.target_bucket)
        else:
            self._source_list.clear()
            for name in t.source_buckets:
                self._source_list.addItem(name)
        self._period_months.setValue(t.period_months)

    def get_trigger(self) -> BucketTrigger:
        trigger_type = TriggerType(self._type.currentText())
        if trigger_type == TriggerType.SELL:
            target = self._target_bucket.currentText().strip() or None
            return BucketTrigger(
                trigger_type=trigger_type,
                subtype=self._subtype.currentText(),
                threshold_pct=self._threshold.value(),
                target_bucket=target,
                period_months=self._period_months.value(),
            )
        else:
            sources = [
                self._source_list.item(i).text()
                for i in range(self._source_list.count())
            ]
            return BucketTrigger(
                trigger_type=trigger_type,
                subtype=self._subtype.currentText(),
                threshold_pct=self._threshold.value(),
                source_buckets=sources,
                period_months=self._period_months.value(),
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
        if t.trigger_type == TriggerType.BUY:
            sources = ", ".join(t.source_buckets) if t.source_buckets else "none"
            target = f" <- [{sources}]"
        else:
            target = f" -> {t.target_bucket}" if t.target_bucket else ""
        period = f"every {t.period_months}mo" if t.period_months > 1 else "monthly"
        return f"{t.trigger_type.value}/{t.subtype}: {t.threshold_pct}{target} ({period})"

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
