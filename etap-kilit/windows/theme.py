"""Windows yönetim programı teması: koyu lacivert zemin, mavi vurgu, amber uyarı rengi."""
P = dict(bg="#0B1020", side="#0E1630", card="#141D38", card2="#1B2750", border="#26335C",
         text="#E8ECF8", muted="#8FA0C4", accent="#4F8CFF", accent_h="#6BA0FF",
         amber="#F5B301", ok="#34D399", bad="#F87171")


def menu_qss():
    """Sistem tepsisi / bağlam menüleri: koyu zemin üstünde açık renkli, okunaklı yazı."""
    return f"""
QMenu {{ background: {P['card']}; color: {P['text']}; border: 1px solid {P['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ background: transparent; color: {P['text']}; padding: 9px 32px 9px 16px; border-radius: 6px; min-width: 130px; }}
QMenu::item:selected {{ background: {P['accent']}; color: white; }}
QMenu::item:disabled {{ color: {P['muted']}; }}
QMenu::separator {{ height: 1px; background: {P['border']}; margin: 6px 8px; }}
"""


def qss(check_url=""):
    img = f"image: url(\"{check_url}\");" if check_url else ""
    return menu_qss() + f"""
* {{ font-family: 'Segoe UI','Noto Sans',sans-serif; font-size: 14px; color: {P['text']}; }}
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {P['bg']}; }}
QWidget#sidebar {{ background: {P['side']}; border-right: 1px solid {P['border']}; }}
QPushButton#nav {{ text-align: left; padding: 12px 16px; border: none; border-radius: 10px;
    color: {P['muted']}; font-size: 15px; background: transparent; }}
QPushButton#nav:hover {{ background: {P['card']}; color: {P['text']}; }}
QPushButton#nav:checked {{ background: {P['card2']}; color: white; font-weight: 600; }}
QFrame#card {{ background: {P['card']}; border: 1px solid {P['border']}; border-radius: 14px; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 26px; font-weight: 700; }}
QLabel#sub {{ color: {P['muted']}; font-size: 14px; }}
QLabel#muted {{ color: {P['muted']}; }}
QLabel#statv {{ font-size: 32px; font-weight: 700; }}
QLabel#cardT {{ font-size: 16px; font-weight: 600; }}
QLabel#brand {{ font-size: 18px; font-weight: 700; }}
QLabel#toast {{ background: {P['card2']}; border: 1px solid {P['accent']}; border-radius: 10px; padding: 10px 18px; }}
QPushButton {{ background: {P['card2']}; border: 1px solid {P['border']}; border-radius: 9px; padding: 9px 16px; }}
QPushButton:hover {{ border-color: {P['accent']}; }}
QPushButton:disabled {{ color: #5b6a8f; }}
QPushButton[variant="primary"] {{ background: {P['accent']}; border-color: {P['accent']}; color: white; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {P['accent_h']}; }}
QPushButton[variant="amber"] {{ background: {P['amber']}; border-color: {P['amber']}; color: #1A1400; font-weight: 600; }}
QPushButton[variant="danger"] {{ background: transparent; border-color: {P['bad']}; color: {P['bad']}; }}
QPushButton[variant="danger"]:hover {{ background: {P['bad']}; color: white; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{ background: {P['bg']}; border: 1px solid {P['border']};
    border-radius: 9px; padding: 8px 10px; selection-background-color: {P['accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {P['accent']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {P['card']}; border: 1px solid {P['border']};
    selection-background-color: {P['accent']}; outline: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 5px; border: 1px solid {P['border']}; background: {P['bg']}; }}
QCheckBox::indicator:checked, QTableWidget::indicator:checked {{ background: {P['accent']}; border-color: {P['accent']}; {img} }}
QCheckBox::indicator:indeterminate {{ background: {P['card2']}; border: 2px solid {P['accent']}; }}
QTableWidget::indicator {{ width: 20px; height: 20px; border-radius: 6px; border: 1px solid {P['border']}; background: {P['bg']}; }}
QTableWidget::indicator:hover {{ border-color: {P['accent']}; }}
QTableWidget {{ background: transparent; border: none; gridline-color: transparent;
    selection-background-color: rgba(79,140,255,70); outline: 0; }}
QTableWidget::item {{ padding: 10px 8px; border-bottom: 1px solid {P['border']}; }}
QTableWidget::item:selected {{ color: white; }}
QHeaderView::section {{ background: transparent; color: {P['muted']}; border: none;
    border-bottom: 1px solid {P['border']}; padding: 8px; font-weight: 600; }}
QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 10px 12px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(79,140,255,70); color: white; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {P['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QMessageBox, QDialog, QInputDialog {{ background: {P['card']}; }}
QToolTip {{ background: {P['card2']}; color: white; border: 1px solid {P['border']}; padding: 6px; }}
"""
