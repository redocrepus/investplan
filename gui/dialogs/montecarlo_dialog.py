"""Monte Carlo simulation dialog with progress bar and results."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSpinBox,
    QPushButton, QProgressBar, QLabel, QDialogButtonBox, QGroupBox,
)
from PyQt6.QtCore import QThread, pyqtSignal
from models.config import SimConfig
from engine.montecarlo import run_monte_carlo, MonteCarloResult


class MonteCarloThread(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)  # MonteCarloResult

    def __init__(self, config: SimConfig, n_sims: int, parent=None):
        super().__init__(parent)
        self.config = config
        self.n_sims = n_sims

    def run(self):
        result = run_monte_carlo(
            self.config,
            n_simulations=self.n_sims,
            progress_callback=lambda cur, total: self.progress.emit(cur, total),
        )
        self.finished.emit(result)


class MonteCarloDialog(QDialog):
    def __init__(self, config: SimConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Monte Carlo Simulation")
        self.setMinimumWidth(400)
        self._config = config
        self._thread: MonteCarloThread | None = None

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._n_sims = QSpinBox()
        self._n_sims.setRange(1, 10000)
        self._n_sims.setValue(100)
        self._n_sims.setToolTip("Number of simulations to run")
        form.addRow("Simulations:", self._n_sims)
        layout.addLayout(form)

        self._btn_run = QPushButton("Run")
        self._btn_run.clicked.connect(self._on_run)
        layout.addWidget(self._btn_run)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        # Results section
        self._results_group = QGroupBox("Results")
        results_layout = QFormLayout(self._results_group)
        self._lbl_success = QLabel("—")
        self._lbl_success.setStyleSheet("font-size: 16px; font-weight: bold;")
        results_layout.addRow("Success Rate:", self._lbl_success)

        self._lbl_p10 = QLabel("—")
        results_layout.addRow("10th Percentile (final):", self._lbl_p10)
        self._lbl_p50 = QLabel("—")
        results_layout.addRow("50th Percentile (final):", self._lbl_p50)
        self._lbl_p90 = QLabel("—")
        results_layout.addRow("90th Percentile (final):", self._lbl_p90)

        self._results_group.hide()
        layout.addWidget(self._results_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_run(self):
        self._btn_run.setEnabled(False)
        self._n_sims.setEnabled(False)
        self._results_group.hide()
        n = self._n_sims.value()
        self._progress.setRange(0, n)
        self._progress.setValue(0)

        self._thread = MonteCarloThread(self._config, n)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)

    def _on_finished(self, result: MonteCarloResult):
        self._btn_run.setEnabled(True)
        self._n_sims.setEnabled(True)

        self._lbl_success.setText(f"{result.success_rate * 100:.1f}%")

        # Show final-month portfolio value at each percentile
        def _final_portfolio(df):
            cols = [c for c in df.columns if c.endswith("_amount_exp")]
            if cols:
                return df[cols].iloc[-1].sum()
            return 0

        p10 = _final_portfolio(result.percentile_10)
        p50 = _final_portfolio(result.percentile_50)
        p90 = _final_portfolio(result.percentile_90)

        self._lbl_p10.setText(f"{p10:,.0f}")
        self._lbl_p50.setText(f"{p50:,.0f}")
        self._lbl_p90.setText(f"{p90:,.0f}")

        self._results_group.show()
