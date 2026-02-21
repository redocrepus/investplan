"""Currency panel — FX settings for each non-expenses currency."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QDoubleSpinBox, QComboBox, QLabel,
)
from PyQt6.QtCore import pyqtSignal
from models.config import SimConfig
from models.currency import CurrencySettings
from utils.volatility import VolatilityProfile


class CurrencyEntryWidget(QGroupBox):
    """Settings for a single non-expenses currency."""
    changed = pyqtSignal()

    def __init__(self, settings: CurrencySettings, parent=None):
        super().__init__(settings.code, parent)
        form = QFormLayout(self)

        self._code = settings.code

        self._initial = QDoubleSpinBox()
        self._initial.setRange(0.0001, 1e6)
        self._initial.setDecimals(4)
        self._initial.setToolTip("Initial price in expenses currency")
        form.addRow("Initial Price:", self._initial)

        self._min = QDoubleSpinBox()
        self._min.setRange(0.0001, 1e6)
        self._min.setDecimals(4)
        self._min.setToolTip("Expected minimum price")
        form.addRow("Min Price:", self._min)

        self._max = QDoubleSpinBox()
        self._max.setRange(0.0001, 1e6)
        self._max.setDecimals(4)
        self._max.setToolTip("Expected maximum price")
        form.addRow("Max Price:", self._max)

        self._avg = QDoubleSpinBox()
        self._avg.setRange(0.0001, 1e6)
        self._avg.setDecimals(4)
        self._avg.setToolTip("Expected average price")
        form.addRow("Avg Price:", self._avg)

        self._vol = QComboBox()
        self._vol.addItems([v.value for v in VolatilityProfile])
        self._vol.setToolTip("Volatility profile for FX rate")
        form.addRow("Volatility:", self._vol)

        self._fee = QDoubleSpinBox()
        self._fee.setRange(0, 50)
        self._fee.setDecimals(2)
        self._fee.setSuffix("%")
        self._fee.setToolTip("Conversion fee percentage")
        form.addRow("Conversion Fee:", self._fee)

        self._load(settings)

        for w in (self._initial, self._min, self._max, self._avg, self._fee):
            w.valueChanged.connect(self.changed.emit)
        self._vol.currentTextChanged.connect(lambda _: self.changed.emit())

    def _load(self, s: CurrencySettings):
        self._initial.setValue(s.initial_price)
        self._min.setValue(s.min_price)
        self._max.setValue(s.max_price)
        self._avg.setValue(s.avg_price)
        idx = self._vol.findText(s.volatility.value)
        if idx >= 0:
            self._vol.setCurrentIndex(idx)
        self._fee.setValue(s.conversion_fee_pct)

    def get_settings(self) -> CurrencySettings:
        return CurrencySettings(
            code=self._code,
            initial_price=self._initial.value(),
            min_price=self._min.value(),
            max_price=self._max.value(),
            avg_price=self._avg.value(),
            volatility=VolatilityProfile(self._vol.currentText()),
            conversion_fee_pct=self._fee.value(),
        )


class CurrencyPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, config: SimConfig, parent=None):
        super().__init__("Currency Settings", parent)
        self._layout = QVBoxLayout(self)
        self._widgets: list[CurrencyEntryWidget] = []
        self._label = QLabel("Add buckets with non-expenses currencies to configure FX settings.")
        self._layout.addWidget(self._label)
        self.read_from_config(config)

    def read_from_config(self, config: SimConfig):
        # Clear existing
        for w in self._widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

        if not config.currencies:
            self._label.show()
        else:
            self._label.hide()

        for cs in config.currencies:
            w = CurrencyEntryWidget(cs)
            w.changed.connect(self.changed.emit)
            self._widgets.append(w)
            self._layout.addWidget(w)

    def write_to_config(self, config: SimConfig):
        config.currencies = [w.get_settings() for w in self._widgets]
