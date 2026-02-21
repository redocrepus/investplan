"""Main application window with splitter, toolbar, and status bar."""

from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QToolBar, QStatusBar, QWidget, QVBoxLayout,
    QScrollArea, QTableView, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction
import numpy as np
import json
import os

from models.config import SimConfig
from engine.simulator import run_simulation
from engine.montecarlo import run_monte_carlo
from gui.table.model import SimTableModel
from gui.table.header import TwoLevelHeaderView
from gui.table.delegates import SimDelegate
from gui.panels.global_panel import GlobalPanel
from gui.panels.bucket_panel import BucketPanel
from gui.panels.expense_panel import ExpensePanel
from gui.panels.currency_panel import CurrencyPanel
from gui.dialogs.montecarlo_dialog import MonteCarloDialog


class SimulationThread(QThread):
    """Run simulation in a background thread."""
    finished = pyqtSignal(object)  # emits the DataFrame

    def __init__(self, config: SimConfig, parent=None):
        super().__init__(parent)
        self.config = config

    def run(self):
        rng = np.random.default_rng()
        df = run_simulation(self.config, rng)
        self.finished.emit(df)


_AUTOSAVE_PATH = os.path.join(
    os.path.expanduser("~"), ".investplan_autosave.json"
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Investment Planner")
        self.resize(1400, 800)

        self._config = SimConfig()
        self._dirty = False
        self._current_file: str | None = None
        self._sim_thread: SimulationThread | None = None

        self._setup_toolbar()
        self._setup_ui()
        self._setup_statusbar()
        self._restore_autosave()

    # --- UI Setup ---

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._act_run = QAction("Run Simulation", self)
        self._act_run.triggered.connect(self._on_run_simulation)
        toolbar.addAction(self._act_run)

        self._act_mc = QAction("Run Monte Carlo", self)
        self._act_mc.triggered.connect(self._on_run_monte_carlo)
        toolbar.addAction(self._act_mc)

        toolbar.addSeparator()

        self._act_save = QAction("Save Config", self)
        self._act_save.triggered.connect(self._on_save_config)
        toolbar.addAction(self._act_save)

        self._act_load = QAction("Load Config", self)
        self._act_load.triggered.connect(self._on_load_config)
        toolbar.addAction(self._act_load)

        toolbar.addSeparator()

        self._act_export = QAction("Export CSV", self)
        self._act_export.triggered.connect(self._on_export_csv)
        toolbar.addAction(self._act_export)

    def _setup_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: input panels in a scroll area
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._global_panel = GlobalPanel(self._config)
        self._global_panel.changed.connect(self._mark_dirty)
        left_layout.addWidget(self._global_panel)

        self._expense_panel = ExpensePanel(self._config)
        self._expense_panel.changed.connect(self._mark_dirty)
        left_layout.addWidget(self._expense_panel)

        self._bucket_panel = BucketPanel(self._config)
        self._bucket_panel.changed.connect(self._mark_dirty)
        left_layout.addWidget(self._bucket_panel)

        self._currency_panel = CurrencyPanel(self._config)
        self._currency_panel.changed.connect(self._mark_dirty)
        left_layout.addWidget(self._currency_panel)

        left_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left_widget)
        scroll.setMinimumWidth(320)

        # Right: simulation table
        self._table_view = QTableView()
        self._table_model = SimTableModel()
        self._table_view.setModel(self._table_model)
        self._header = TwoLevelHeaderView(Qt.Orientation.Horizontal, self._table_view)
        self._table_view.setHorizontalHeader(self._header)
        self._delegate = SimDelegate()
        self._table_view.setItemDelegate(self._delegate)

        splitter.addWidget(scroll)
        splitter.addWidget(self._table_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Ready")

    # --- Config Sync ---

    def _collect_config(self) -> SimConfig:
        """Collect current config from all panels."""
        self._global_panel.write_to_config(self._config)
        self._expense_panel.write_to_config(self._config)
        self._bucket_panel.write_to_config(self._config)
        self._currency_panel.write_to_config(self._config)
        return self._config

    def _distribute_config(self):
        """Push config to all panels."""
        self._global_panel.read_from_config(self._config)
        self._expense_panel.read_from_config(self._config)
        self._bucket_panel.read_from_config(self._config)
        self._currency_panel.read_from_config(self._config)

    def _mark_dirty(self):
        self._dirty = True

    # --- Auto-save / Restore ---

    def _autosave(self):
        try:
            config = self._collect_config()
            with open(_AUTOSAVE_PATH, "w") as f:
                f.write(config.model_dump_json(indent=2))
        except Exception:
            pass  # best-effort

    def _restore_autosave(self):
        if not os.path.exists(_AUTOSAVE_PATH):
            return
        try:
            with open(_AUTOSAVE_PATH, "r") as f:
                data = json.load(f)
            self._config = SimConfig.model_validate(data)
            self._distribute_config()
            self._statusbar.showMessage("Restored last session")
        except Exception:
            pass  # ignore corrupt autosave

    # --- Validation ---

    def _validate_config(self, config: SimConfig) -> str | None:
        """Return an error message if config is invalid, or None if OK."""
        if config.period_years < 1:
            return "Period must be at least 1 year."
        if not config.buckets:
            return "Add at least one investment bucket."
        for b in config.buckets:
            if not b.name.strip():
                return "All buckets must have a name."
            if b.growth_min_pct > b.growth_max_pct:
                return f"Bucket '{b.name}': growth min must be <= max."
        if config.inflation.min_pct > config.inflation.max_pct:
            return "Inflation min must be <= max."
        for ep in config.expense_periods:
            if ep.amount_min > ep.amount_max:
                return "Expense period: amount min must be <= max."
        return None

    # --- Actions ---

    def _on_run_simulation(self):
        config = self._collect_config()
        error = self._validate_config(config)
        if error:
            self._statusbar.showMessage(f"Validation error: {error}")
            QMessageBox.warning(self, "Validation Error", error)
            return
        self._act_run.setEnabled(False)
        self._statusbar.showMessage("Running simulation...")
        self._sim_thread = SimulationThread(config)
        self._sim_thread.finished.connect(self._on_simulation_done)
        self._sim_thread.start()

    def _on_simulation_done(self, df):
        self._table_model.set_dataframe(df, self._config)
        self._header.set_config(self._config)
        self._delegate.set_config(self._config)
        self._table_view.resizeColumnsToContents()
        self._act_run.setEnabled(True)
        self._statusbar.showMessage("Simulation complete")

    def _on_run_monte_carlo(self):
        config = self._collect_config()
        error = self._validate_config(config)
        if error:
            self._statusbar.showMessage(f"Validation error: {error}")
            QMessageBox.warning(self, "Validation Error", error)
            return
        dialog = MonteCarloDialog(config, self)
        dialog.exec()

    def _on_save_config(self):
        config = self._collect_config()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Config", "", "JSON Files (*.json)"
        )
        if path:
            with open(path, "w") as f:
                f.write(config.model_dump_json(indent=2))
            self._current_file = path
            self._dirty = False
            self._statusbar.showMessage(f"Saved to {path}")

    def _on_load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Config", "", "JSON Files (*.json)"
        )
        if path:
            with open(path, "r") as f:
                data = json.load(f)
            self._config = SimConfig.model_validate(data)
            self._distribute_config()
            self._current_file = path
            self._dirty = False
            self._statusbar.showMessage(f"Loaded from {path}")

    def _on_export_csv(self):
        if self._table_model.rowCount() == 0:
            self._statusbar.showMessage("No simulation data to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "", "CSV Files (*.csv)"
        )
        if path:
            self._table_model.to_dataframe().to_csv(path, index=False)
            self._statusbar.showMessage(f"Exported to {path}")

    # --- Close ---

    def closeEvent(self, event):
        self._autosave()
        if self._dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._on_save_config()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
