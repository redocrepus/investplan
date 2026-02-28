"""QAbstractTableModel backed by simulator DataFrame."""

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex
import pandas as pd
from models.config import SimConfig


# Columns always shown
FIXED_COLUMNS = ["year", "month", "inflation", "expenses", "total_net_spent"]

# Per-bucket columns when expanded
BUCKET_EXPANDED_COLS = [
    "price", "price_exp", "amount", "amount_exp",
    "sold", "sold_exp", "bought", "fees", "tax", "net_spent",
]

# Per-bucket columns when collapsed (summary)
BUCKET_COLLAPSED_COLS = ["price", "price_exp", "amount", "amount_exp"]


class SimTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._df: pd.DataFrame | None = None
        self._config: SimConfig | None = None
        self._columns: list[str] = []
        self._display_names: list[str] = []
        self._collapsed_buckets: set[str] = set()
        self._yearly_view = False

    def set_dataframe(self, df: pd.DataFrame, config: SimConfig):
        self.beginResetModel()
        self._df = df
        self._config = config
        self._rebuild_columns()
        self.endResetModel()

    def toggle_yearly_view(self, yearly: bool):
        self.beginResetModel()
        self._yearly_view = yearly
        self.endResetModel()

    def toggle_bucket_collapse(self, bucket_name: str):
        self.beginResetModel()
        if bucket_name in self._collapsed_buckets:
            self._collapsed_buckets.discard(bucket_name)
        else:
            self._collapsed_buckets.add(bucket_name)
        self._rebuild_columns()
        self.endResetModel()

    def _rebuild_columns(self):
        self._columns = list(FIXED_COLUMNS)
        self._display_names = ["Year", "Month", "Inflation", "Expenses", "Total Net-Spent"]

        if self._config is None:
            return

        for bucket in self._config.buckets:
            name = bucket.name
            if name in self._collapsed_buckets:
                cols = BUCKET_COLLAPSED_COLS
            else:
                cols = BUCKET_EXPANDED_COLS
            for col in cols:
                self._columns.append(f"{name}_{col}")
                self._display_names.append(col)

    def _get_view_df(self) -> pd.DataFrame:
        if self._df is None:
            return pd.DataFrame()
        if not self._yearly_view:
            return self._df
        # Aggregate to yearly: sum expenses/net_spent, take last price/amount
        df = self._df.copy()
        agg = {}
        for col in self._columns:
            if col == "year":
                continue
            elif col == "month":
                agg[col] = "last"
            elif col == "inflation":
                agg[col] = "mean"
            elif "price" in col:
                agg[col] = "last"
            elif "amount" in col and "sold" not in col and "bought" not in col:
                agg[col] = "last"
            else:
                agg[col] = "sum"
        # Only aggregate columns that exist in the dataframe
        agg = {k: v for k, v in agg.items() if k in df.columns}
        return df.groupby("year").agg(agg).reset_index()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        df = self._get_view_df()
        return len(df)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        df = self._get_view_df()
        col_name = self._columns[index.column()]
        if col_name not in df.columns:
            return None
        value = df.iloc[index.row()][col_name]

        if role == Qt.ItemDataRole.DisplayRole:
            if col_name in ("year", "month"):
                return str(int(value))
            elif col_name == "inflation":
                return f"{value * 100 * 12:.2f}%"
            elif "pct" in col_name or col_name == "inflation":
                return f"{value:.2f}%"
            else:
                return f"{value:,.2f}"
        elif role == Qt.ItemDataRole.UserRole:
            # Raw value for delegates
            return float(value)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section < len(self._display_names):
                return self._display_names[section]
        elif orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def to_dataframe(self) -> pd.DataFrame:
        """Return the current view DataFrame for export."""
        return self._get_view_df()

    def get_column_name(self, col_index: int) -> str:
        if 0 <= col_index < len(self._columns):
            return self._columns[col_index]
        return ""

    def get_bucket_names(self) -> list[str]:
        if self._config:
            return [b.name for b in self._config.buckets]
        return []
