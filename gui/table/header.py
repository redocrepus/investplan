"""Two-level header view: bucket group row + column name row."""

from PyQt6.QtWidgets import QHeaderView, QStyleOptionHeader, QStyle
from PyQt6.QtCore import Qt, QRect, QPoint
from PyQt6.QtGui import QPainter, QMouseEvent
from models.config import SimConfig
from gui.table.model import FIXED_COLUMNS, BUCKET_EXPANDED_COLS, BUCKET_COLLAPSED_COLS


# Short display labels for column sub-headers
_COL_LABELS = {
    "year": "Year", "month": "Month", "inflation": "Inflation",
    "expenses": "Expenses", "total_net_spent": "Total Net-Spent",
    "price": "Price", "price_exp": "Price ($)", "amount": "Amount",
    "amount_exp": "Amount ($)", "sold": "Sold", "sold_exp": "Sold ($)",
    "bought": "Bought", "fees": "Fees", "tax": "Tax", "net_spent": "Net-Spent",
}


class TwoLevelHeaderView(QHeaderView):
    """Custom horizontal header with a top row for bucket group names."""

    BAND_HEIGHT = 22  # height of the top bucket-name band

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._config: SimConfig | None = None
        self._bucket_spans: list[tuple[str, int, int]] = []  # (name, start_col, end_col)
        self.setSectionsClickable(True)
        self.sectionClicked.connect(self._on_section_clicked)

    def set_config(self, config: SimConfig):
        self._config = config
        self._compute_spans()
        self.viewport().update()

    def _compute_spans(self):
        """Compute which columns belong to each bucket group."""
        self._bucket_spans = []
        if not self._config:
            return
        model = self.model()
        if not model:
            return

        n_fixed = len(FIXED_COLUMNS)
        col = n_fixed
        for bucket in self._config.buckets:
            # Determine how many cols this bucket has by checking the model
            from gui.table.model import SimTableModel
            if isinstance(model, SimTableModel):
                collapsed = bucket.name in model._collapsed_buckets
            else:
                collapsed = False
            n_cols = len(BUCKET_COLLAPSED_COLS) if collapsed else len(BUCKET_EXPANDED_COLS)
            self._bucket_spans.append((bucket.name, col, col + n_cols - 1))
            col += n_cols

    def sizeHint(self):
        s = super().sizeHint()
        s.setHeight(s.height() + self.BAND_HEIGHT)
        return s

    def _is_bucket_column(self, logicalIndex: int) -> bool:
        """Return True if this column belongs to a bucket group."""
        for _, start, end in self._bucket_spans:
            if start <= logicalIndex <= end:
                return True
        return False

    def paintSection(self, painter: QPainter, rect: QRect, logicalIndex: int):
        """Paint column header; bucket columns are shifted down for the band."""
        if not painter:
            return

        is_bucket = self._is_bucket_column(logicalIndex)

        if is_bucket:
            # Shift bucket column labels down to make room for the band
            painter.save()
            shifted = QRect(rect.x(), rect.y() + self.BAND_HEIGHT,
                            rect.width(), rect.height() - self.BAND_HEIGHT)
            super().paintSection(painter, shifted, logicalIndex)
            painter.restore()
        else:
            # Fixed columns use the full height — no band above
            super().paintSection(painter, rect, logicalIndex)

        # Draw bucket group band for columns that belong to a bucket
        for name, start, end in self._bucket_spans:
            if start <= logicalIndex <= end:
                if logicalIndex == start:
                    x = self.sectionViewportPosition(start)
                    w = sum(self.sectionSize(i) for i in range(start, end + 1))
                    band_rect = QRect(x, rect.y(), w, self.BAND_HEIGHT)
                    painter.save()
                    painter.fillRect(band_rect, self.palette().midlight())
                    painter.drawRect(band_rect)
                    painter.drawText(band_rect, Qt.AlignmentFlag.AlignCenter, name)
                    painter.restore()
                break

    def _sub_label(self, logicalIndex: int) -> str:
        """Get the short column label for a logical index."""
        model = self.model()
        if not model:
            return ""
        from gui.table.model import SimTableModel
        if isinstance(model, SimTableModel):
            col_name = model.get_column_name(logicalIndex)
            # Strip bucket prefix
            for part in col_name.split("_"):
                pass
            suffix = col_name.rsplit("_", 1)[-1] if "_" in col_name else col_name
            # Try two-part suffix for things like "price_exp"
            parts = col_name.split("_")
            if len(parts) >= 3:
                suffix2 = "_".join(parts[-2:])
                if suffix2 in _COL_LABELS:
                    return _COL_LABELS[suffix2]
            return _COL_LABELS.get(suffix, suffix)
        return ""

    def _on_section_clicked(self, logicalIndex: int):
        """Toggle bucket collapse when clicking on a bucket group header."""
        model = self.model()
        if not model:
            return
        from gui.table.model import SimTableModel
        if not isinstance(model, SimTableModel):
            return
        for name, start, end in self._bucket_spans:
            if start <= logicalIndex <= end:
                model.toggle_bucket_collapse(name)
                self._compute_spans()
                self.viewport().update()
                break
