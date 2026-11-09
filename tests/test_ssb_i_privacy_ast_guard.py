"""SSBI R1_6 — Tests des statischen Privacy-Guards.

Der Guard (``tools/privacy_ast_guard.py``) ist eine **statische
Regressionserkennung**. Er beweist keine Erreichbarkeit und keine
Leckfreiheit — die Runtime-Grenze tut das.

Diese Tests sichern die in R1_5 nachgewiesenen Befunde ab:

  * False Negative ``f"{x:s}"``  -> BEHOBEN (ERROR)
  * False Positive Registry-Code -> BEHOBEN (0 Befunde)
  * False Positive Enum-Ausgabe  -> BEHOBEN (0 Befunde)
  * False Positive annotierte Integer-Felder -> BEHOBEN fuer
    annotierte Parameter; die Grenze fuer nicht belegbare Herkunft
    (``ctx.count``) bleibt als WARN bestehen und wird hier festgeschrieben.

Zusaetzlich: der Guard muss im Produktionscode **0 ERROR** melden.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import privacy_ast_guard as G  # noqa: E402


def _scan(tmp_path, source: str):
    """Kontrolliert eine Quelldatei mit dem Guard."""
    env = G.TypeEnv()
    guard = G.Guard(env)
    target = tmp_path / "probe.py"
    target.write_text(source, encoding="utf-8")
    env.learn(target)
    return G.check_file(target, tmp_path, guard)


def _rules(violations):
    return [v.rule for v in violations]


# ===========================================================================
# Der vom R1_5-Audit nachgewiesene False Negative
# ===========================================================================
class TestFalseNegative:
    """f"{x:s}" wurde faelschlich akzeptiert."""

    def test_fn01_fstring_mit_s_spec_wird_erkannt(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED",
                       f"erste {ctx.disk[:4]:s}", {})
''')
        assert "V2_UNBOUNDED_CONVERSION" in _rules(v), _rules(v)

    def test_fn02_fstring_mit_r_spec_wird_erkannt(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED",
                       f"erste {ctx.disk[:4]!r}", {})
''')
        assert "V2_UNBOUNDED_CONVERSION" in _rules(v), _rules(v)

    def test_fn03_der_befund_ist_ein_error(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED",
                       f"erste {ctx.disk[:4]:s}", {})
''')
        errors = [x for x in v if x.severity == "ERROR"]
        assert errors, "der Befund muss ERROR sein, nicht nur gesetzt"


# ===========================================================================
# Die vom R1_5-Audit nachgewiesenen False Positives
# ===========================================================================
class TestFalsePositives:
    """Legitime Muster duerfen nicht beanstandet werden."""

    def test_fp01_registry_code_ist_clean(self, tmp_path):
        """Der Aufruf der geschlossenen Meldungsregistry ist kontrolliert."""
        v = _scan(tmp_path, '''
def render_public_message(code, **kw):
    return code

def f(ctx):
    return CheckResult("I-01", "T", "FAILED",
                       render_public_message("X", magic=ctx.disk[:4]), {})
''')
        assert v == [], _rules(v)

    def test_fp02_enum_ausgabe_ist_clean(self, tmp_path):
        """Ein Enum ist eine geschlossene Wertemenge."""
        v = _scan(tmp_path, '''
from enum import Enum

class Status(Enum):
    OK = "ok"

def f(ctx, status: Status):
    return CheckResult("I-01", "T", "FAILED", "Status: %s" % status, {})
''')
        assert v == [], _rules(v)

    def test_fp03_annotierter_integer_parameter_ist_clean(self, tmp_path):
        """Ein annotierter Integer-Parameter ist belegt."""
        v = _scan(tmp_path, '''
def f(ctx, count: int):
    return CheckResult("I-04", "T", "PASS", "Summe %d" % count,
                       {"count": count})
''')
        assert v == [], _rules(v)

    def test_fp04_bekannter_formatteger_ist_clean(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-04", "T", "PASS", "Summe %d" % 5, {"count": 5})
''')
        assert v == [], _rules(v)

    def test_fp05_fstring_mit_numerischem_spec_ist_clean(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    n = 5
    return CheckResult("I-04", "T", "PASS", f"Summe {n:d}", {})
''')
        assert v == [], _rules(v)

    def test_fp06_steuertext_ist_clean(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "PASS", "Container beginnt mit BCPS", {})
''')
        assert v == [], _rules(v)


# ===========================================================================
# Echte Lecks muessen erkannt werden (Negativtests)
# ===========================================================================
class TestDetection:
    """Der Guard muss echte Lecks finden."""

    def test_d01_percent_r_wird_erkannt(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED", "erste %r" % ctx.disk[:4], {})
''')
        assert "V2_UNBOUNDED_CONVERSION" in _rules(v), _rules(v)

    def test_d02_percent_s_auf_bytes_wird_erkannt(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED", "erste %s" % ctx.disk[:4], {})
''')
        assert "V2_UNBOUNDED_CONVERSION" in _rules(v), _rules(v)

    def test_d03_freier_string_wird_erkannt(self, tmp_path):
        v = _scan(tmp_path, '''
def f(ctx, name: str):
    return CheckResult("I-01", "T", "FAILED", "Spieler %s" % name, {})
''')
        assert "V2_UNBOUNDED_CONVERSION" in _rules(v), _rules(v)

    def test_d04_unklare_herkunft_ist_warn(self, tmp_path):
        """Nicht belegbare Herkunft wird gemeldet — als WARN."""
        v = _scan(tmp_path, '''
def f(ctx):
    n = ctx.count
    return CheckResult("I-04", "T", "PASS", "Summe %d" % n, {"count": n})
''')
        assert "V3_UNKNOWN_ORIGIN" in _rules(v), _rules(v)

    def test_d05_umgehungen_werden_erkannt(self, tmp_path):
        """Alias, Wrapper und getattr-Umgehung werden erkannt."""
        for source in (
            '''
def f(ctx):
    fmt = public_error
    return CheckResult("I-01", "T", "FAILED", "x %s" % fmt(ctx.disk), {})
''',
            '''
def wrap(v):
    return str(v)

def f(ctx):
    return CheckResult("I-01", "T", "FAILED", "x %s" % wrap(ctx.disk), {})
''',
            '''
def f(ctx):
    return CheckResult("I-01", "T", "FAILED", "x %s" % getattr(ctx, "disk"), {})
''',
        ):
            v = _scan(tmp_path, source)
            assert v, "Umgehung wurde nicht erkannt"


# ===========================================================================
# Der Guard im Produktionscode
# ===========================================================================
class TestProduktionscode:
    """Der Guard darf im Produktionscode keinen ERROR melden."""

    @pytest.fixture(scope="class")
    def scan(self):
        env = G.TypeEnv()
        for rel in ("ssb_i/savegame_provider.py", "ssb_i/save_integrity.py",
                    "ssb_i/errors.py", "ssb_i/savegame_differential.py",
                    "sfda_cli.py", "ssb_ui/app.py",
                    "ssb_ui/pages/savegame_page.py"):
            path = REPO / rel
            if path.exists():
                env.learn(path)
        guard = G.Guard(env)
        violations = []
        for rel in ("ssb_i/savegame_provider.py", "ssb_i/save_integrity.py",
                    "ssb_i/errors.py", "ssb_i/savegame_differential.py",
                    "sfda_cli.py", "ssb_ui/app.py",
                    "ssb_ui/pages/savegame_page.py"):
            path = REPO / rel
            if path.exists():
                violations.extend(G.check_file(path, REPO, guard))
        return violations

    def test_p01_kein_error_im_produktionscode(self, scan):
        errors = [v for v in scan if v.severity == "ERROR"]
        assert not errors, [(v.file, v.lineno, v.rule) for v in errors[:10]]

    def test_p02_kein_unbounded_conversion_im_produktionscode(self, scan):
        """Die Runtime-Grenze ersetzt keine Konvertierung."""
        unbounded = [v for v in scan
                     if v.rule == "V2_UNBOUNDED_CONVERSION"]
        assert not unbounded, [(v.file, v.lineno) for v in unbounded[:10]]

    def test_p03_guard_meldet_keine_erreichbarkeit(self):
        """Der Guard behauptet keine Erreichbarkeit — das ist dokumentiert."""
        doc = (REPO / "tools/privacy_ast_guard.py").read_text(encoding="utf-8")
        assert "Erreichbarkeit" in doc or "erreichbarkeit" in doc
        # Es darf keine Formulierung geben, die Erreichbarkeit behauptet.
        for claim in ("beweist die Erreichbarkeit",
                      "garantiert keine Lecks",
                      "vollstaendig leakfrei"):
            assert claim not in doc


class TestSelbsttest:
    """Der Guard bringt seinen eigenen Selbsttest mit."""

    def test_s01_selftest_laeuft_durch(self):
        env = G.TypeEnv()
        for rel in ("ssb_i/save_integrity.py", "ssb_i/errors.py"):
            path = REPO / rel
            if path.exists():
                env.learn(path)
        assert G.selftest(env) == 0
