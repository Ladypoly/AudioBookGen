"""Dark theme stylesheet.

Plain QSS for a polished dark look without extra deps. Can be swapped for
qfluentwidgets later (PLAN UI requirements) without touching widget logic.
"""

ROLE_COLORS = {
    "narrator": "#7c5cff",
    "main": "#3aa0ff",
    "secondary": "#27c498",
    "minor": "#9aa3b2",
    "crowd": "#6b7280",
}

DARK_QSS = """
* {
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
    color: #e6e8ee;
}
QWidget { background: #0f1117; }
QLabel { background: transparent; }
QWidget#Root, QMainWindow {
    background: #0f1117;
}
QGroupBox {
    background: #161a26;
    border: 1px solid #232838;
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 8px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: #9DAAF2;
    font-weight: 600;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0e1320;
    border: 1px solid #2e3650;
    border-radius: 6px;
    padding: 5px 8px;
    color: #e6e8ee;
    selection-background-color: #3a6df0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #3a6df0;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #161a26;
    color: #e6e8ee;
    border: 1px solid #2e3650;
    selection-background-color: #2b3450;
}
QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 2px solid #46527a; border-radius: 5px; background: #0e1320;
}
QCheckBox::indicator:hover { border: 2px solid #5a6aa0; }
QCheckBox::indicator:checked { background: #4ade80; border: 2px solid #4ade80; }
QCheckBox::indicator:checked:hover { background: #65e695; border: 2px solid #65e695; }
QCheckBox::indicator:disabled { border: 2px solid #2a3148; background: #141a28; }
QCheckBox:disabled { color: #5b6376; }
QCheckBox:checked { color: #ffffff; font-weight: 600; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2e3650; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar#OverallBar { height: 18px; color: #e6e8ee; text-align: center; }
QWidget#Sidebar {
    background: #151823;
    border-right: 1px solid #232838;
}
QListWidget#Nav {
    background: transparent;
    border: none;
    padding: 8px;
}
QListWidget#Nav::item {
    padding: 10px 14px;
    border-radius: 8px;
    margin: 2px 4px;
    color: #aab2c5;
}
QListWidget#Nav::item:selected {
    background: #232a3d;
    color: #ffffff;
}
QListWidget#Nav::item:hover {
    background: #1c2233;
}
QLabel#TitleLabel {
    font-size: 22px;
    font-weight: 600;
    color: #ffffff;
}
QLabel#Subtle { color: #8b93a7; }
QPushButton {
    background: #232a3d;
    border: 1px solid #2e3650;
    border-radius: 8px;
    padding: 8px 16px;
    color: #e6e8ee;
}
QPushButton:hover { background: #2b3450; }
QPushButton:disabled { color: #5b6376; background: #1a1f2e; }
QPushButton#Primary {
    background: #3a6df0;
    border: none;
    font-weight: 600;
}
QPushButton#Primary:hover { background: #4a7bff; }
QFrame#Card {
    background: #161a26;
    border: 1px solid #232838;
    border-radius: 12px;
}
QFrame#Card:hover { border: 1px solid #3a4a6e; }
QLabel#CardName { font-size: 15px; font-weight: 600; color: #ffffff; }
QLabel#PortraitSlot {
    background: #10141f;
    border: 1px solid #232838;
    border-radius: 8px;
    color: #5b6376;
}
QLabel#SectionHead {
    color: #7c89a3;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#DropHint {
    color: #5b6376;
    font-size: 11px;
    border: 1px dashed #2e3650;
    border-radius: 6px;
    padding: 5px;
}
QFrame#Divider { background: #232838; border: none; }
QPushButton#Ghost {
    background: transparent;
    border: 1px solid #2e3650;
    color: #aab2c5;
    padding: 6px 10px;
}
QPushButton#Ghost:hover { background: #1c2233; color: #e6e8ee; }
QLabel#Chip {
    background: #222a3c;
    border-radius: 9px;
    padding: 2px 9px;
    color: #b9c2d6;
    font-size: 11px;
}
QLabel#Badge {
    border-radius: 9px;
    padding: 2px 10px;
    color: #0c0f17;
    font-size: 11px;
    font-weight: 700;
}
QProgressBar {
    background: #1a1f2e;
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #3a6df0; border-radius: 6px; }
QScrollArea { border: none; }
QScrollArea#CardsScroll, QScrollArea#CardsScroll > QWidget > QWidget,
QWidget#CardsHost {
    background: #0b1430;
}
QWidget#CardsHost { border-radius: 12px; }
"""
