"""Bucket panel — list of investment buckets with add/edit/remove/reorder."""

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
)
from PyQt6.QtCore import pyqtSignal
from models.config import SimConfig
from models.bucket import InvestmentBucket
from gui.dialogs.bucket_dialog import BucketDialog


class BucketPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, config: SimConfig, parent=None):
        super().__init__("Investment Buckets", parent)
        layout = QVBoxLayout(self)

        self._list = QListWidget()
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("Add")
        self._btn_edit = QPushButton("Edit")
        self._btn_remove = QPushButton("Remove")
        self._btn_up = QPushButton("Up")
        self._btn_down = QPushButton("Down")
        for btn in (self._btn_add, self._btn_edit, self._btn_remove,
                    self._btn_up, self._btn_down):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._btn_add.clicked.connect(self._add)
        self._btn_edit.clicked.connect(self._edit)
        self._btn_remove.clicked.connect(self._remove)
        self._btn_up.clicked.connect(self._move_up)
        self._btn_down.clicked.connect(self._move_down)

        self._buckets: list[InvestmentBucket] = []
        self.read_from_config(config)

    def read_from_config(self, config: SimConfig):
        self._buckets = list(config.buckets)
        self._refresh()

    def write_to_config(self, config: SimConfig):
        config.buckets = list(self._buckets)

    def _refresh(self):
        self._list.clear()
        for b in self._buckets:
            text = (f"{b.name} ({b.currency}) — "
                    f"{b.initial_amount:,.0f} @ {b.initial_price:,.2f}, "
                    f"growth {b.growth_avg_pct}%")
            self._list.addItem(text)

    def _add(self):
        dlg = BucketDialog(
            existing_bucket_names=[b.name for b in self._buckets],
            parent=self,
        )
        if dlg.exec():
            self._buckets.append(dlg.get_bucket())
            self._refresh()
            self.changed.emit()

    def _edit(self):
        row = self._list.currentRow()
        if row < 0:
            return
        other_names = [b.name for i, b in enumerate(self._buckets) if i != row]
        dlg = BucketDialog(
            bucket=self._buckets[row],
            existing_bucket_names=other_names,
            parent=self,
        )
        if dlg.exec():
            self._buckets[row] = dlg.get_bucket()
            self._refresh()
            self.changed.emit()

    def _remove(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._buckets.pop(row)
        self._refresh()
        self.changed.emit()

    def _move_up(self):
        row = self._list.currentRow()
        if row <= 0:
            return
        self._buckets[row - 1], self._buckets[row] = (
            self._buckets[row], self._buckets[row - 1]
        )
        self._refresh()
        self._list.setCurrentRow(row - 1)
        self.changed.emit()

    def _move_down(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._buckets) - 1:
            return
        self._buckets[row], self._buckets[row + 1] = (
            self._buckets[row + 1], self._buckets[row]
        )
        self._refresh()
        self._list.setCurrentRow(row + 1)
        self.changed.emit()
