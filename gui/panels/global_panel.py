"""Global settings panel — period, currency, tax, inflation, cash pool."""

from PyQt6.QtWidgets import (
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox, QVBoxLayout,
)
from PyQt6.QtCore import pyqtSignal
from models.config import SimConfig, CashPool
from models.inflation import InflationSettings
from utils.currency_list import COMMON_CURRENCIES, get_locale_currency
from utils.volatility import InflationVolatility


class GlobalPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, config: SimConfig, parent=None):
        super().__init__("Global Settings", parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._period = QSpinBox()
        self._period.setRange(1, 100)
        self._period.setSuffix(" years")
        self._period.setToolTip("Total investment period in years")
        form.addRow("Period:", self._period)

        self._currency = QComboBox()
        self._currency.addItems(COMMON_CURRENCIES)
        self._currency.setToolTip("Currency used for expenses and reporting")
        form.addRow("Expenses Currency:", self._currency)

        self._tax = QDoubleSpinBox()
        self._tax.setRange(0, 100)
        self._tax.setDecimals(1)
        self._tax.setSuffix("%")
        self._tax.setToolTip("Capital gains tax percentage")
        form.addRow("Capital Gain Tax:", self._tax)

        # Inflation sub-section
        inf_group = QGroupBox("Inflation")
        inf_form = QFormLayout(inf_group)

        self._inf_min = QDoubleSpinBox()
        self._inf_min.setRange(-10, 50)
        self._inf_min.setDecimals(1)
        self._inf_min.setSuffix("%")
        self._inf_min.setToolTip("Minimum expected annual inflation")
        inf_form.addRow("Min:", self._inf_min)

        self._inf_max = QDoubleSpinBox()
        self._inf_max.setRange(-10, 50)
        self._inf_max.setDecimals(1)
        self._inf_max.setSuffix("%")
        self._inf_max.setToolTip("Maximum expected annual inflation")
        inf_form.addRow("Max:", self._inf_max)

        self._inf_avg = QDoubleSpinBox()
        self._inf_avg.setRange(-10, 50)
        self._inf_avg.setDecimals(1)
        self._inf_avg.setSuffix("%")
        self._inf_avg.setToolTip("Average expected annual inflation")
        inf_form.addRow("Average:", self._inf_avg)

        self._inf_vol = QComboBox()
        self._inf_vol.addItems([v.value for v in InflationVolatility])
        self._inf_vol.setToolTip("Inflation volatility profile")
        inf_form.addRow("Volatility:", self._inf_vol)

        layout.addWidget(inf_group)

        # Cash Pool sub-section
        cp_group = QGroupBox("Cash Pool")
        cp_form = QFormLayout(cp_group)

        self._cp_initial = QDoubleSpinBox()
        self._cp_initial.setRange(0, 1e9)
        self._cp_initial.setDecimals(2)
        self._cp_initial.setToolTip("Starting cash reserve in expenses currency. All expenses are drawn from here.")
        cp_form.addRow("Initial Amount:", self._cp_initial)

        self._cp_refill_trigger = QDoubleSpinBox()
        self._cp_refill_trigger.setRange(0, 120)
        self._cp_refill_trigger.setDecimals(1)
        self._cp_refill_trigger.setSuffix(" months")
        self._cp_refill_trigger.setToolTip(
            "Start refilling the cash pool when it drops below this many months of expenses. "
            "Must be <= Refill Target."
        )
        cp_form.addRow("Refill Trigger:", self._cp_refill_trigger)

        self._cp_refill_target = QDoubleSpinBox()
        self._cp_refill_target.setRange(0, 120)
        self._cp_refill_target.setDecimals(1)
        self._cp_refill_target.setSuffix(" months")
        self._cp_refill_target.setToolTip(
            "Refill the cash pool up to this many months of expenses. "
            "Must be >= Refill Trigger. "
            "Buckets are sold in order of highest profitability to refill."
        )
        cp_form.addRow("Refill Target:", self._cp_refill_target)

        self._cp_floor = QDoubleSpinBox()
        self._cp_floor.setRange(0, 120)
        self._cp_floor.setDecimals(1)
        self._cp_floor.setSuffix(" months")
        self._cp_floor.setToolTip(
            "Hard floor for the cash pool in months of current expenses. "
            "Recalculated monthly using inflation-adjusted expenses."
        )
        cp_form.addRow("Cash Floor:", self._cp_floor)

        layout.addWidget(cp_group)

        # Connect signals
        for w in (self._period, self._tax,
                  self._inf_min, self._inf_max, self._inf_avg,
                  self._cp_initial, self._cp_refill_trigger, self._cp_refill_target, self._cp_floor):
            w.valueChanged.connect(self.changed.emit)
        for w in (self._currency, self._inf_vol):
            w.currentTextChanged.connect(lambda _: self.changed.emit())

        self.read_from_config(config)

    def read_from_config(self, config: SimConfig):
        self._period.setValue(config.period_years)
        idx = self._currency.findText(config.expenses_currency)
        if idx >= 0:
            self._currency.setCurrentIndex(idx)
        self._tax.setValue(config.capital_gain_tax_pct)
        self._inf_min.setValue(config.inflation.min_pct)
        self._inf_max.setValue(config.inflation.max_pct)
        self._inf_avg.setValue(config.inflation.avg_pct)
        idx = self._inf_vol.findText(config.inflation.volatility.value)
        if idx >= 0:
            self._inf_vol.setCurrentIndex(idx)
        self._cp_initial.setValue(config.cash_pool.initial_amount)
        self._cp_refill_trigger.setValue(config.cash_pool.refill_trigger_months)
        self._cp_refill_target.setValue(config.cash_pool.refill_target_months)
        self._cp_floor.setValue(config.cash_pool.cash_floor_months)

    def write_to_config(self, config: SimConfig):
        config.period_years = self._period.value()
        config.expenses_currency = self._currency.currentText()
        config.capital_gain_tax_pct = self._tax.value()
        config.inflation = InflationSettings(
            min_pct=self._inf_min.value(),
            max_pct=self._inf_max.value(),
            avg_pct=self._inf_avg.value(),
            volatility=InflationVolatility(self._inf_vol.currentText()),
        )
        config.cash_pool = CashPool(
            initial_amount=self._cp_initial.value(),
            refill_trigger_months=self._cp_refill_trigger.value(),
            refill_target_months=self._cp_refill_target.value(),
            cash_floor_months=self._cp_floor.value(),
        )
