"""Gemeinsame Gestaltungskonstanten der SSB-I-Oberflaeche.

Zwei Seiten (`ssb_ui.app` und `ssb_ui.pages.savegame_page`) pflegten bisher
je eine eigene Kopie der Farbkonstanten. Das fuehrte zu driftenden Werten
und war der Grund dafuer, dass Panels, Textfelder und Buttons unterschiedlich
wirkten.

Grundsaetze:

  * **Neutrale Oberflaeche.** Panels, Karten und Textfelder benutzen
    Flaechenfarben, keine Akzentfarben. Ein farbiger Rand ist Dekoration —
    er kommt weg.
  * **Eine Akzentfarbe.** Sie markiert ausschliesslich aktive Zustaende:
    Auswahl, Fokus, die eine ausgewaehlte Aktion. Nicht fuer jedes Element.
  * **Statusfarben tragen Bedeutung.** PASS/WARNING/FAILED/Fehler bleiben
    unterscheidbar. Sie sind kein Dekor fuer gewoehnliche Felder.
  * **Eine Schriftfamilie.** Monospace ueber `QFont.setStyleHint`, nicht
    ueber einen fest verdrahteten Namen — der Name ist nicht ueberall
    installiert, der Style-Hint findet eine Monospace-Schrift immer.
"""
from __future__ import annotations

from PySide6.QtGui import QFont

# --------------------------------------------------------------------------
# Neutrale Flaechen
# --------------------------------------------------------------------------
#: Hintergrund der Anwendung.
SURFACE = "#12161C"
#: Flaeche eines Panels / einer Karte.
CARD = "#171B22"
#: Rahmen eines Panels (1 px, ruhig).
CARD_EDGE = "#252B35"
#: Hintergrund eines Textfeldes (etwas dunkler als die Karte).
FIELD = "#12161C"
#: Hintergrund einer Zeile im Plugin-Baum (alternating).
ROW_ALT = "#1A1F27"

# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------
#: Haupttext.
TEXT = "#DCE3EC"
#: Nebentext (Beschriftungen, Zusammenfassungen).
TEXT_DIM = "#8A94A3"
#: Sehr schwacher Text (Platzhalter).
TEXT_FAINT = "#5C6673"

# --------------------------------------------------------------------------
# Akzent — genau eine
# --------------------------------------------------------------------------
#: Auswahl, Fokus, ausgewaehlte Aktion.
ACCENT = "#4C9AFF"
#: Text auf akzentfarbigem Grund.
ON_ACCENT = "#0D1117"

# --------------------------------------------------------------------------
# Statusfarben — semantisch, nicht dekorativ
# --------------------------------------------------------------------------
#: Erfolg / PASS.
STATUS_OK = "#5FBF7F"
#: Warnung / WARNING.
STATUS_WARN = "#D9A441"
#: Fehler / FAILED.
STATUS_FAIL = "#E06C6C"
#: Hinweis / unbekannt / nicht bewertet.
STATUS_INFO = "#8A94A3"

#: Semantische Farbe zu einem Statuswert. Geschlossen — unbekannte Werte
#: bekommen die neutrale Textfarbe, keine erfundene Farbe.
STATUS_COLORS = {
    "PASS": STATUS_OK,
    "OK": STATUS_OK,
    "WARNING": STATUS_WARN,
    "WARN": STATUS_WARN,
    "FAILED": STATUS_FAIL,
    "FAIL": STATUS_FAIL,
    "ERROR": STATUS_FAIL,
    "UNKNOWN": STATUS_INFO,
    "NOT_CHECKED": STATUS_INFO,
    "UNVERIFIED": STATUS_INFO,
}


def status_color(status: str) -> str:
    """Farbe zu einem Statuswert — ``TEXT`` fuer unbekannte Werte."""
    if not isinstance(status, str):
        return TEXT_DIM
    return STATUS_COLORS.get(status.strip().upper(), TEXT_DIM)


# --------------------------------------------------------------------------
# Typografie
# --------------------------------------------------------------------------
#: Einzige Schriftfamilie. Der Name ist ein Wunsch; der Style-Hint sorgt
#: dafuer, dass Qt eine Monospace-Schrift findet, auch wenn die Familie
#: fehlt. Ein reiner ``font-family``-Name im Stylesheet genuegt nicht —
#: dort faellt Qt still auf die Standardproportionale zurueck.
FONT_FAMILY = "Cascadia Code"

#: O-7: CSS-Familienliste fuer Stylesheets. Qt waehlt die **erste
#: installierte** Familie der Liste — steht keine davon zur Verfuegung,
#: greift die generische Familie ``monospace``.
#:
#: **Belegt** (Linux, Qt 6.11): ``font-family: 'Cascadia Code'`` allein
#: loest zu *DejaVu Sans* auf — **proportional**, nicht monospace
#: (``QFontMetrics`` i=36 px gegen M=112 px). Mit der Fallback-Kette
#: loest dieselbe Angabe zu *DejaVu Sans Mono* auf (i=78 px, M=78 px).
#: Der Spaltenversatz betraegt 77 px auf der breitesten PLAYER-Zeile.
#:
#: Deshalb: nie ein einzelner fest verdrahteter Name.
MONO_FAMILY_CSS = '"Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace'

#: Groessen in Punkt.
SIZE_BODY = 10
SIZE_SMALL = 9
SIZE_TINY = 8
SIZE_TITLE = 18


def mono_font(size: int = SIZE_BODY, bold: bool = False) -> QFont:
    """Monospace-Schrift der Anwendung — mit plattformuebergreifendem Fallback.

    ``QFont.setStyleHint(QFont.Monospace)`` ist der entscheidende Teil:
    er weist Qt an, eine Monospace-Schrift zu waehlen, falls die gewuenschte
    Familie nicht installiert ist. Ein reiner ``font-family``-Name im
    Stylesheet genuegt nicht — dort faellt Qt still auf die
    Standardproportionale zurueck.

    **Gemessen** (Linux, Qt 6.11): ``QFontMetrics.horizontalAdvance`` ist fuer
    ``iiiiiiiiii`` und ``MMMMMMMMMM`` gleich breit (78 px bei 10 pt), waehrend
    Arial/Helvetica 29 gegen 108 px liefern. Die Familie wird also
    tatsaechlich monospace aufgeloest.

    ``QFont.fixedPitch()`` ist als Anzeigeflag **nicht** verlaesslich — es
    meldet hier ``False``, obwohl die Schrift monospace ist. Fuer die
    Pruefung ist deshalb ``QFontMetrics`` die richtige Groesse.
    """
    font = QFont(FONT_FAMILY)
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(size)
    font.setBold(bold)
    return font


def is_monospace(font: QFont) -> bool:
    """Ist die aufgeloeste Schrift wirklich monospace?

    Gemessen ueber die Zeichenbreite statt ueber ``fixedPitch()`` — das
    liefert bei Qt-Fonts auch bei echten Monospace-Schriften ``False``.
    """
    from PySide6.QtGui import QFontMetrics
    metrics = QFontMetrics(font)
    return (metrics.horizontalAdvance("iiiiiiiiii")
            == metrics.horizontalAdvance("MMMMMMMMMM"))


def body_font(size: int = SIZE_BODY) -> QFont:
    """Lesbare Oberflaechenschrift fuer Beschriftungen und Fliesstext."""
    font = QFont()
    font.setPointSize(size)
    return font


def display_width_meter(font: QFont):
    """Breitenmesser fuer die Spaltenausrichtung: ``(text) -> Anzeigebreite``.

    O-7: Die zweispaltige Spielerkarte richtet ihre Spalten an der
    **Anzeigebreite** aus, nicht an der Zeichenzahl. Ein Breitzeichen
    (CJK, Emoji) belegt in einer Monospace-Schrift zwei Spalten — mit
    ``len()`` gemessen rueckt die rechte Spalte um genau diese
    Differenz nach links.

    Der Breitenmesser nutzt ``QFontMetrics.horizontalAdvance`` — die
    einzige verlaessliche Qt-API dafuer. ``QFont.fixedPitch()`` ist als
    Nachweis unbrauchbar (es meldet ``False`` auch fuer echte
    Monospace-Schriften); die Font-Familie muss ausserdem **nicht**
    fest verdrahtet sein, sonst fehlt sie auf fremden Systemen.
    """
    from PySide6.QtGui import QFontMetrics
    metrics = QFontMetrics(font)

    def measure(text: str) -> int:
        if not text:
            return 0
        return metrics.horizontalAdvance(text)

    return measure
