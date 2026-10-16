# -*- coding: utf-8 -*-
"""
Builds the test board of the Layout checks: a two-layer board with one case
for every check (and a few cases that must NOT be reported), plus its
project file with the net data (currents, groups).

Output, in docs/test_board of the repository (or in the folder given):
    si_toolkit_test.kicad_pcb        the board (opens in KiCad 7-10)
    si_toolkit_test.si_toolkit.json  net data of the board for the plugin

Run it with a Python that has the pcbnew module, e.g. the one of KiCad:
    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" make_test_board.py
Not needed to use the plugin: the board is already in the repository.
"""
import json
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "test_board")
NAME = "si_toolkit_test"

MM = pcbnew.FromMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu


def V(x, y):
    """Point in mm -> VECTOR2I in nm."""
    return pcbnew.VECTOR2I(MM(x), MM(y))


class TestBoard:
    """Small helpers to place footprints, pads, tracks, vias and zones."""

    def __init__(self):
        self.board = pcbnew.BOARD()
        self.nets = {}
        self.copper = []   # (x, y, radius mm) of every pad/via/track point: no stitching via there

    def net(self, name):
        if name not in self.nets:
            ni = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(ni)
            self.nets[name] = ni
        return self.nets[name]

    def outline(self, w, h):
        for a, b in (((0, 0), (w, 0)), ((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0))):
            s = pcbnew.PCB_SHAPE(self.board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetStart(V(*a))
            s.SetEnd(V(*b))
            s.SetWidth(MM(0.1))
            self.board.Add(s)

    def text(self, x, y, txt, size=1.2):
        """Label on the silkscreen, to find the cases on the board."""
        t = pcbnew.PCB_TEXT(self.board)
        t.SetText(txt)
        t.SetLayer(pcbnew.F_SilkS)
        t.SetTextSize(V(size, size))
        t.SetTextThickness(MM(size * 0.15))
        t.SetPosition(V(x, y))
        self.board.Add(t)

    def footprint(self, ref, pads, layer=F, pin_types=None):
        """pads: (number, x, y, net, size x, size y); absolute positions in mm."""
        fp = pcbnew.FOOTPRINT(self.board)
        fp.SetReference(ref)
        fp.SetValue(ref)
        self.board.Add(fp)
        for k, (num, x, y, n, sx, sy) in enumerate(pads):
            p = pcbnew.PAD(fp)
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetShape(pcbnew.PAD_SHAPE_RECT)
            p.SetSize(V(sx, sy))
            ls = pcbnew.LSET()
            ls.AddLayer(layer)
            ls.AddLayer(pcbnew.F_Mask if layer == F else pcbnew.B_Mask)
            p.SetLayerSet(ls)
            p.SetNumber(num)
            fp.Add(p)
            p.SetPosition(V(x, y))
            try:
                p.SetPos0(V(x, y))   # KiCad 7 saves the footprint-relative position
            except AttributeError:
                pass
            p.SetNet(self.net(n))
            if pin_types and num in pin_types:
                p.SetPinType(pin_types[num])
            self.copper.append((x, y, max(sx, sy) / 2 + 0.6))
        return fp

    def track(self, pts, layer, n, w=0.25):
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.board)
            t.SetStart(V(*a))
            t.SetEnd(V(*b))
            t.SetLayer(layer)
            t.SetWidth(MM(w))
            t.SetNet(self.net(n))
            self.board.Add(t)
            # Points along the track, to keep the stitching vias away
            steps = max(1, int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) / 0.5))
            for k in range(steps + 1):
                f = k / steps
                self.copper.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, w / 2 + 0.8))

    def via(self, x, y, n, drill=0.3, size=0.6):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(V(x, y))
        v.SetWidth(MM(size))
        v.SetDrill(MM(drill))
        v.SetLayerPair(F, B)
        v.SetNet(self.net(n))
        self.board.Add(v)
        self.copper.append((x, y, size / 2 + 0.5))

    def zone(self, layer, pts, n, holes=(), full_pads=False):
        z = pcbnew.ZONE(self.board)
        z.SetLayer(layer)
        z.SetNet(self.net(n))
        ol = z.Outline()
        ol.NewOutline()
        for x, y in pts:
            ol.Append(MM(x), MM(y))
        for hole in holes:
            h = ol.NewHole()
            for x, y in hole:
                ol.Append(MM(x), MM(y), -1, h)
        z.SetLocalClearance(MM(0.3))
        z.SetMinThickness(MM(0.2))
        if full_pads:
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        self.board.Add(z)
        return z

    def free(self, x, y):
        """True if a stitching via at (x, y) stays away from all the copper placed."""
        return all((x - cx) ** 2 + (y - cy) ** 2 > r * r for cx, cy, r in self.copper)


def build(out_dir):
    tb = TestBoard()
    W, H = 120, 90
    tb.outline(W, H)
    PW = {"1": "power_in"}

    # --- 5. Plane edge: a signal 1.2 mm from the top edge for 25 mm
    tb.footprint("U10", [("1", 8, 1.2, "EDGE_SIG", 0.8, 0.6), ("2", 36, 6, "EDGE_SIG", 0.8, 0.6)])
    tb.track([(8, 1.2), (33, 1.2), (36, 4.2), (36, 6)], F, "EDGE_SIG")
    tb.text(20, 4.5, "5 EDGE")

    # --- 1. Decoupling: U1 supply pin, nearest capacitor C1 10 mm away
    tb.footprint("U1", [("1", 46, 10, "+3V3", 0.8, 0.6), ("2", 46, 12, "GND", 0.8, 0.6)], pin_types=PW)
    tb.via(46, 13.2, "GND")
    tb.footprint("C1", [("1", 57, 10, "+3V3", 0.9, 0.95), ("2", 57, 11.6, "GND", 0.9, 0.95)])
    tb.via(57, 12.9, "GND")
    tb.track([(46, 10), (57, 10)], F, "+3V3", 0.4)
    tb.text(51, 7.5, "1 DECAP")

    # --- 9. Dead branch: DATA between U2 and R2 with a 3 mm branch ending in nothing
    tb.footprint("U2", [("1", 66, 10, "DATA", 0.8, 0.6)])
    tb.footprint("R2", [("1", 78, 10, "DATA", 0.8, 0.6)])
    tb.track([(66, 10), (78, 10)], F, "DATA")
    tb.track([(72, 10), (72, 13)], F, "DATA")
    tb.text(72, 7.5, "9 STUB")

    # --- 10. Acute angle: ACUTE comes back at about 14 degrees
    tb.footprint("U3", [("1", 86, 10, "ACUTE", 0.8, 0.6), ("2", 88, 12.5, "ACUTE", 0.8, 0.6)])
    tb.track([(86, 10), (96, 10), (88, 12.5)], F, "ACUTE")
    # A 90 degree corner (fine)
    tb.footprint("U4", [("1", 100, 10, "RIGHT", 0.8, 0.6), ("2", 110, 15, "RIGHT", 0.8, 0.6)])
    tb.track([(100, 10), (110, 10), (110, 15)], F, "RIGHT")
    tb.text(98, 7.5, "10 ACUTE")

    # --- 2. Layer change: SIG_LC goes from top to bottom with no ground via close
    tb.footprint("U5", [("1", 10, 20, "SIG_LC", 0.8, 0.6)])
    tb.footprint("U6", [("1", 26, 20, "SIG_LC", 0.8, 0.6)], B)
    tb.track([(10, 20), (18, 20)], F, "SIG_LC")
    tb.via(18, 20, "SIG_LC")
    tb.track([(18, 20), (26, 20)], B, "SIG_LC")
    tb.copper.append((18, 20, 5.0))   # no stitching via within 5 mm: the case must stay
    tb.text(18, 17.5, "2 LAYER")

    # --- 4. Plane gap: PG_SIG on top crosses an 8 mm slot of the bottom plane
    tb.footprint("U7", [("1", 34, 20, "PG_SIG", 0.8, 0.6), ("2", 58, 20, "PG_SIG", 0.8, 0.6)])
    tb.track([(34, 20), (58, 20)], F, "PG_SIG")
    slot = [(42, 15.5), (50, 15.5), (50, 24.5), (42, 24.5)]
    tb.text(46, 26.5, "4 GAP")

    # --- 6. Track width: +5V at 0.25 mm with 2 A (net data: +5V=2)
    tb.footprint("J1", [("1", 66, 20, "+5V", 1.5, 1.5), ("2", 90, 20, "+5V", 1.5, 1.5)])
    tb.track([(66, 20), (90, 20)], F, "+5V", 0.25)
    tb.text(78, 17.5, "6 WIDTH")

    # --- 7. Isolation: HV_400V 1 mm from a GND track (IPC-2221 B2: 2.5 mm)
    tb.footprint("J2", [("1", 96, 20, "HV_400V", 1.5, 1.5), ("2", 116, 20, "HV_400V", 1.5, 1.5),
                        ("3", 96, 22.6, "GND", 1.5, 1.5), ("4", 116, 22.6, "GND", 1.5, 1.5)])
    tb.track([(96, 20), (116, 20)], F, "HV_400V", 0.5)
    tb.track([(96, 22.6), (116, 22.6)], F, "GND", 0.5)
    tb.text(106, 17.5, "7 ISOL")

    # --- 8. Lengths: USB pair 20 / 23.5 mm; SD group 30 / 25 / 29.5 mm
    tb.footprint("U8", [("1", 6, 32, "USB_DP", 0.8, 0.5), ("2", 6, 33, "USB_DM", 0.8, 0.5)])
    tb.footprint("U9", [("1", 26, 32, "USB_DP", 0.8, 0.5), ("2", 26, 33, "USB_DM", 0.8, 0.5)])
    tb.track([(6, 32), (26, 32)], F, "USB_DP")
    tb.track([(6, 33), (14, 33), (14, 34.75), (17.5, 34.75), (17.5, 33), (26, 33)], F, "USB_DM")
    tb.footprint("U11", [("1", 6, 38, "SD_CLK", 0.8, 0.5), ("2", 6, 40, "SD_D0", 0.8, 0.5),
                         ("3", 6, 42, "SD_D1", 0.8, 0.5)])
    tb.footprint("U12", [("1", 35.5, 38, "SD_CLK", 0.8, 0.5), ("2", 36, 40, "SD_D0", 0.8, 0.5),
                         ("3", 31, 42, "SD_D1", 0.8, 0.5)])
    tb.track([(6, 38), (35.5, 38)], F, "SD_CLK")
    tb.track([(6, 40), (36, 40)], F, "SD_D0")
    tb.track([(6, 42), (31, 42)], F, "SD_D1")
    tb.text(20, 29.5, "8 LENGTH")

    # --- 11. Width step: 0.25 mm for 10 mm then 0.15 mm for 10 mm; and a
    #     neck-down at a pad that must not be reported
    tb.footprint("U13", [("1", 46, 32, "WSTEP", 0.8, 0.6), ("2", 66, 32, "WSTEP", 0.8, 0.6)])
    tb.track([(46, 32), (56, 32)], F, "WSTEP", 0.25)
    tb.track([(56, 32), (66, 32)], F, "WSTEP", 0.15)
    tb.footprint("U14", [("1", 46, 36, "NECK", 0.8, 0.6), ("2", 66, 36, "NECK", 0.8, 0.6)])
    tb.track([(46, 36), (46.6, 36)], F, "NECK", 0.15)
    tb.track([(46.6, 36), (66, 36)], F, "NECK", 0.3)
    tb.text(56, 29.5, "11 WSTEP")

    # --- 12. Via in an SMD pad
    tb.footprint("R3", [("1", 76, 34, "VIP", 0.9, 0.95), ("2", 78, 34, "VIP2", 0.9, 0.95)])
    tb.via(76, 34, "VIP")
    tb.footprint("R4", [("1", 84, 34, "VIP2", 0.9, 0.95)])
    tb.track([(78, 34), (84, 34)], F, "VIP2")
    tb.text(80, 31, "12 VIA-PAD")

    # --- 13. Tombstoning: C9 with the GND pad flooded (solid zone connection)
    tb.footprint("C9", [("1", 94, 34, "GND", 0.9, 0.95), ("2", 95.6, 34, "SIGX", 0.9, 0.95)])
    tb.footprint("R5", [("1", 104, 34, "SIGX", 0.9, 0.95)])
    tb.track([(95.6, 34), (104, 34)], F, "SIGX")
    tomb_zone = [(89, 30), (95.05, 30), (95.05, 38), (89, 38)]
    tb.text(97, 31, "13 TOMB")

    # --- 14. Current in the vias: VIN with 5 A on 3 mm tracks, two 0.3 mm vias (3 needed)
    tb.footprint("J3", [("1", 8, 50, "VIN", 2.0, 2.0)])
    tb.footprint("J4", [("1", 30, 50, "VIN", 2.0, 2.0)], B)
    tb.track([(8, 50), (18, 50)], F, "VIN", 3.0)
    tb.via(17.6, 50, "VIN")
    tb.via(18.6, 50, "VIN")
    tb.track([(18, 50), (30, 50)], B, "VIN", 3.0)
    tb.text(18, 46, "14 VIA-CUR")

    # --- 15. Crystal Y1, 24 mm of tracks to U15, OTHER passing under it on the bottom
    tb.footprint("Y1", [("1", 46, 50, "XIN", 1.0, 1.0), ("2", 49, 50, "XOUT", 1.0, 1.0)])
    tb.footprint("U15", [("1", 66, 50, "XIN", 0.8, 0.6), ("2", 50, 53, "XOUT", 0.8, 0.6)])
    tb.track([(46, 50), (46, 47), (66, 47), (66, 50)], F, "XIN")
    tb.track([(49, 50), (50, 53)], F, "XOUT")
    tb.footprint("U16", [("1", 47.5, 44, "OTHER", 0.8, 0.6), ("2", 47.5, 56, "OTHER", 0.8, 0.6)], B)
    tb.track([(47.5, 44), (47.5, 56)], B, "OTHER")
    tb.text(56, 59, "15 XTAL")

    # --- 16. Overlapping tracks: NA on top over NB on the bottom for 20 mm
    tb.footprint("U17", [("1", 74, 50, "NA", 0.8, 0.6), ("2", 100, 50, "NA", 0.8, 0.6)])
    tb.footprint("U18", [("1", 74, 52, "NB", 0.8, 0.6), ("2", 94, 52, "NB", 0.8, 0.6)], B)
    tb.track([(74, 50), (100, 50)], F, "NA")
    tb.track([(74, 52), (74, 50.05), (94, 50.05), (94, 52)], B, "NB")
    tb.text(86, 46, "16 OVERLAP")

    # --- 3. Stitching: ground on both layers, vias every 8 mm, except in the
    #     lower right corner (an area far from the vias)
    no_vias = (88, 62, 120, 90)
    for gx in range(4, W, 8):
        for gy in range(4, H, 8):
            if no_vias[0] <= gx <= no_vias[2] and no_vias[1] <= gy <= no_vias[3]:
                continue
            if 38 <= gx <= 54 and 12 <= gy <= 28:
                continue  # not inside or next to the slot of the bottom plane
            # The grid point, or the nearest free point around it (the tracks
            # and pads of the cases take some of the grid points)
            for dx, dy in ((0, 0), (1.5, 0), (-1.5, 0), (0, 1.5), (0, -1.5), (1.5, 1.5), (-1.5, -1.5),
                           (1.5, -1.5), (-1.5, 1.5), (3, 0), (-3, 0), (0, 3), (0, -3)):
                x, y = gx + dx, gy + dy
                if 0.8 < x < W - 0.8 and 0.8 < y < H - 0.8 and tb.free(x, y) \
                        and not (38 <= x <= 54 and 12 <= y <= 28):   # slot of the plane: no via near
                    tb.via(x, y, "GND")
                    break
    tb.text(104, 76, "3 STITCH")

    # Ground planes: bottom over the whole board with the slot; top over the
    # whole board too (tombstone zone with solid pad connection)
    tb.zone(B, [(0, 0), (W, 0), (W, H), (0, H)], "GND", holes=[slot])
    tb.zone(F, [(0, 0), (W, 0), (W, H), (0, H)], "GND")
    tb.zone(F, tomb_zone, "GND", full_pads=True)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, NAME + ".kicad_pcb")
    tb.board.Save(path)
    board = pcbnew.LoadBoard(path)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(path)
    # Net data of the board for the plugin (as the tab saves them)
    with open(os.path.join(out_dir, NAME + ".si_toolkit.json"), "w", encoding="utf-8") as f:
        json.dump({"lc_currents": "+5V=2; VIN=5", "lc_voltages": "", "lc_groups": "SD_*"}, f, indent=2)
    return path


if __name__ == "__main__":
    print("Creata", build(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT))
