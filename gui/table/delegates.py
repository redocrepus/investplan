"""Cell delegates for formatting and coloring."""

from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtGui import QColor, QPalette
from models.config import SimConfig


class SimDelegate(QStyledItemDelegate):
    """Custom delegate for simulation table cells.

    - Red background when total_net_spent < expenses
    - Currency formatting for monetary values
    - Percent formatting for rate values
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config: SimConfig | None = None

    def set_config(self, config: SimConfig):
        self._config = config

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex):
        super().initStyleOption(option, index)

        model = index.model()
        if not model:
            return

        from gui.table.model import SimTableModel
        if not isinstance(model, SimTableModel):
            return

        col_name = model.get_column_name(index.column())

        # Red background for total_net_spent < expenses
        if col_name == "total_net_spent":
            row = index.row()
            expenses_col = model._columns.index("expenses") if "expenses" in model._columns else -1
            if expenses_col >= 0:
                expenses_val = model.data(
                    model.index(row, expenses_col), Qt.ItemDataRole.UserRole
                )
                net_val = model.data(index, Qt.ItemDataRole.UserRole)
                if expenses_val is not None and net_val is not None:
                    if net_val < expenses_val - 0.01:
                        option.backgroundBrush = QColor(255, 200, 200)
                        option.palette.setColor(
                            QPalette.ColorRole.Highlight, QColor(255, 150, 150)
                        )
