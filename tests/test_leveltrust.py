import os
import tempfile
import unittest

from leveltrust import checks, parse, seal


def _row(adr, c1, c2="", c3="", c4=""):
    return f"For M5|Adr {adr:>5}|{c1:<31}|{c2:<22}|{c3:<22}|{c4:<22}|"


def build(edit=None):
    """Two-station closed loop, with one intermediate sight; instrument-consistent numbers."""
    hd = lambda v: f"HD {v:>10.3f} m"
    rd = lambda c, v: f"{c} {v:>10.5f} m"
    z = lambda v: f"Z {v:>11.5f} m"
    rb1, rf1, rb2, rf2, rz = 1.40000, 1.30000, 1.20000, 1.30000, 1.15000
    z1 = rb1 - rf1                   # 0.1
    z2 = z1 + rb2 - rf2              # 0.0
    hi = z1 + rf1                    # instrument height at station 1 (=rb1)
    zi = hi - rz
    rows = [
        _row(1, "TO  t.dat"), _row(2, "TO  Start-Line      aBFFB   1"),
        _row(3, "KD1     A                  1", c4=z(0.0)),
        _row(4, "KD1     A      06:00:00  1", rd("Rb", rb1), hd(20)),
        _row(5, "KD1        1      06:00:10  1", rd("Rf", rf1), hd(20)),
        _row(6, "KD1        1      06:00:13  1", rd("Rf", rf1), hd(20)),
        _row(7, "KD1     A      06:00:23  1", rd("Rb", rb1), hd(20)),
        _row(8, "KD1        1      06:00:23  1", c4=z(z1)),
        _row(9, "TO  Intermediate sight.     1"),
        _row(10, "KD1     P1       06:00:50  1", rd("Rz", rz), hd(10), z(zi)),
        _row(11, "TO  End of interm. sight.   1"),
        _row(12, "KD1        1      06:04:00  1", rd("Rb", rb2), hd(25)),
        _row(13, "KD1     A      06:04:10  1", rd("Rf", rf2), hd(25)),
        _row(14, "KD1     A      06:04:13  1", rd("Rf", rf2), hd(25)),
        _row(15, "KD1        1      06:04:23  1", rd("Rb", rb2), hd(25)),
        _row(16, "KD1     A      06:04:23  1", c4=z(z2)),
        _row(17, "KD1     A                  1", rd("Sh", z2), "dz " + f"{-z2:>10.5f} m", z(0.0)),
        _row(18, "KD2     A        2       1", f"Db {45.0:>10.2f} m", f"Df {45.0:>10.2f} m", z(z2)),
        _row(19, "TO  End-Line                1"),
    ]
    text = "\r\n".join(["    水准观测原始记录", "", "仪器型号: DNA03    出厂编号: 1",
                        "观测日期: 2026-01-01  14:00 - 14:10", "观测者: X      检查者: Y", ""] + rows) + "\r\n"
    if edit:
        text = edit(text)
    path = os.path.join(tempfile.mkdtemp(), "t.DAT")
    open(path, "wb").write(text.encode("gbk"))
    return path


class T(unittest.TestCase):
    def levels(self, path, layer):
        rec = parse.parse_file(path)
        fs = checks.run_all([rec])
        return [f.level for f in fs if f.layer == layer], fs

    def test_clean_file_has_no_arithmetic_flags(self):
        lv, _ = self.levels(build(), "L3")
        self.assertNotIn(checks.HIGH, lv)

    def test_same_width_edit_of_intermediate_reading_is_caught(self):
        edited = build(lambda t: t.replace("1.15000", "1.17000"))
        lv, _ = self.levels(edited, "L3")
        self.assertIn(checks.HIGH, lv)

    def test_edit_of_station_reading_is_caught(self):
        edited = build(lambda t: t.replace("1.20000", "1.21000", 1))
        lv, _ = self.levels(edited, "L3")
        self.assertIn(checks.HIGH, lv)

    def test_mixed_line_endings_flagged(self):
        edited = build(lambda t: t.replace("\r\n", "\n", 3))
        lv, _ = self.levels(edited, "L2")
        self.assertIn(checks.MED, lv)

    def test_seal_verify_names_changed_line(self):
        p = build()
        m = seal.seal([p])
        self.assertEqual(seal.verify(m, [p]), [])
        raw = open(p, "rb").read().replace(b"1.15000", b"1.16000")
        open(p, "wb").write(raw)
        probs = seal.verify(m, [p])
        self.assertEqual(len(probs), 1)
        self.assertIn("变动行", probs[0])

    def test_hmac_manifest_rewrite_detected(self):
        p = build()
        m = seal.seal([p], key="k")
        m["files"]["t.DAT"]["sha256"] = "0" * 64
        self.assertTrue(any("HMAC" in x for x in seal.verify(m, [p], key="k")))


if __name__ == "__main__":
    unittest.main()
