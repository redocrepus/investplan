"""Dialog for editing an investment bucket and its rebalancing parameters."""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
    QDialogButtonBox, QVBoxLayout, QGroupBox,
)
from models.bucket import InvestmentBucket, RebalancingParams
from utils.currency_list import COMMON_CURRENCIES
from utils.volatility import VolatilityProfile


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
        self._fee.setToolTip("Buy/sell fee percentage")
        form.addRow("Buy/Sell Fee:", self._fee)

        self._target_growth = QDoubleSpinBox()
        self._target_growth.setRange(-100, 1000)
        self._target_growth.setDecimals(1)
        self._target_growth.setSuffix("%")
        self._target_growth.setToolTip("Target growth for rebalancing triggers")
        form.addRow("Target Growth:", self._target_growth)

        # --- Rebalancing section ---
        reb_group = QGroupBox("Rebalancing")
        reb_form = QFormLayout(reb_group)

        self._frequency = QComboBox()
        self._frequency.addItems(["monthly", "yearly"])
        self._frequency.setToolTip("How often to check rebalancing triggers")
        reb_form.addRow("Frequency:", self._frequency)

        self._sell_trigger = QDoubleSpinBox()
        self._sell_trigger.setRange(0.01, 100)
        self._sell_trigger.setDecimals(2)
        self._sell_trigger.setToolTip("Sell if actual_growth/target_growth > this value")
        reb_form.addRow("Sell Trigger:", self._sell_trigger)

        self._standby = QComboBox()
        self._standby.setEditable(True)
        self._standby.addItem("")  # no standby
        self._standby.setToolTip("Bucket to buy with proceeds from selling")
        reb_form.addRow("Standby Bucket:", self._standby)

        self._buy_trigger = QDoubleSpinBox()
        self._buy_trigger.setRange(0, 1000)
        self._buy_trigger.setDecimals(1)
        self._buy_trigger.setSuffix("%")
        self._buy_trigger.setToolTip("Buy standby if discount > this percent")
        reb_form.addRow("Buy Trigger:", self._buy_trigger)

        self._buying_priority = QSpinBox()
        self._buying_priority.setRange(0, 100)
        self._buying_priority.setToolTip("Lower number = buy first (ordering)")
        reb_form.addRow("Buying Priority:", self._buying_priority)

        self._runaway = QDoubleSpinBox()
        self._runaway.setRange(0, 120)
        self._runaway.setDecimals(1)
        self._runaway.setSuffix(" months")
        self._runaway.setToolTip("Required months of expenses runway before selling")
        reb_form.addRow("Required Runaway:", self._runaway)

        self._spending_priority = QSpinBox()
        self._spending_priority.setRange(0, 100)
        self._spending_priority.setToolTip("Lower number = sell first for expenses")
        reb_form.addRow("Spending Priority:", self._spending_priority)

        self._cash_floor = QDoubleSpinBox()
        self._cash_floor.setRange(0, 120)
        self._cash_floor.setDecimals(1)
        self._cash_floor.setSuffix(" months")
        self._cash_floor.setToolTip(
            "Keep at least this many months of expenses in this bucket class"
        )
        reb_form.addRow("Cash Floor:", self._cash_floor)

        layout.addWidget(reb_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Populate standby bucket options
        for name in self._existing_names:
            self._standby.addItem(name)

        if bucket:
            self._load(bucket)
        else:
            self._initial_price.setValue(100)
            self._growth_avg.setValue(7)
            self._target_growth.setValue(7)
            self._sell_trigger.setValue(1.5)
            self._buy_trigger.setValue(5.0)
            self._runaway.setValue(6)

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
        self._target_growth.setValue(b.target_growth_pct)

        r = b.rebalancing
        self._frequency.setCurrentText(r.frequency)
        self._sell_trigger.setValue(r.sell_trigger)
        if r.standby_bucket:
            self._standby.setCurrentText(r.standby_bucket)
        self._buy_trigger.setValue(r.buy_trigger)
        self._buying_priority.setValue(r.buying_priority)
        self._runaway.setValue(r.required_runaway_months)
        self._spending_priority.setValue(r.spending_priority)
        self._cash_floor.setValue(r.cash_floor_months)

    def get_bucket(self) -> InvestmentBucket:
        standby = self._standby.currentText().strip() or None
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
            target_growth_pct=self._target_growth.value(),
            rebalancing=RebalancingParams(
                frequency=self._frequency.currentText(),
                sell_trigger=self._sell_trigger.value(),
                standby_bucket=standby,
                buy_trigger=self._buy_trigger.value(),
                buying_priority=self._buying_priority.value(),
                required_runaway_months=self._runaway.value(),
                spending_priority=self._spending_priority.value(),
                cash_floor_months=self._cash_floor.value(),
            ),
        )
