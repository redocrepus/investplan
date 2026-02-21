# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'models', 'models.config', 'models.bucket', 'models.expense',
        'models.currency', 'models.inflation',
        'engine', 'engine.simulator', 'engine.montecarlo', 'engine.inflation',
        'engine.currency', 'engine.bucket', 'engine.expenses', 'engine.rebalancer',
        'utils', 'utils.volatility', 'utils.currency_list',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='InvestmentPlanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
