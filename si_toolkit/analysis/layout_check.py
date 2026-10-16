"""
"Layout checks" module: a "smart DRC" on the whole board.

Unlike the other tabs, these checks do not try to predict a physical
quantity (emissions, noise...). They MEASURE the layout and compare the
measures with well-known good-practice rules: the result is a fact about
the board ("C12 is 9.4 mm from pin 7 of U3"), the rule tells why it matters.

Checks (each one can be enabled or disabled):

1. Decoupling: for every supply pin of an integrated circuit, the closest
   capacitor between that supply net and ground; for every capacitor and
   every IC ground pin, a ground via close to the ground pad (the
   connection to the plane is what makes a decoupling capacitor work).
2. Layer change without return: a signal via changes the reference plane
   (e.g. top track over the inner GND plane, bottom track over another
   plane): the return current has to jump between the two planes, and the
   shortest way is a ground via close to the signal via.
3. Stitching vias: when ground is poured on two or more layers, every point
   of the pour should be close to a ground via that ties the layers
   together. Areas farther than the chosen via spacing are reported.
4. Tracks crossing plane gaps: the Return Path check (return_path.py) run
   on all the tracks of the board.
5. Tracks near the edge of their reference plane: the ground copper of the
   adjacent layer (the real fill) should extend at least a few dielectric
   heights (h) beyond the edge of the track, otherwise part of the field
   (and of the return current) has no plane under it.
6. Track width and current: the tracks of the nets with a current given by
   the user, compared with the IPC-2221 width for the allowed temperature
   rise.
7. Isolation: the copper distance between nets with a voltage difference
   above 30 V, compared with the IPC-2221 table (B1 inner, B2 outer layers).
8. Lengths: length difference (skew) of the differential pairs and of the
   groups of nets that must have the same length.
9. Stubs: tracks that end without connecting to anything (dead copper,
   an antenna), with the length of the dead branch.
10. Acute angles: two tracks of the same net meeting at less than 90
    degrees (acid trap: etching chemicals stay in the corner).
11. Width steps: a signal net whose tracks change width along the way (a
    step of impedance), neck-downs at the pads excluded.
12. Vias in SMD pads: the drill of a via inside a component pad (solder
    flows into the hole); large thermal pads excluded.
13. Tombstoning: small two-pad parts with one pad flooded in a zone and
    the other connected by tracks only (they heat up unevenly).
14. Current in the vias: for the nets with a current, the number of vias at
    every layer change compared with the IPC-2221 number needed.
15. Crystal: tracks of other nets under a crystal, and the length of the
    tracks between the crystal and its IC.
16. Broadside coupling: tracks of different nets running one over the
    other on adjacent layers.

Grounds are all the nets whose name contains the filter of the Options tab
(with "GND": GND, AGND, DGND...), but each ground stays separate: a via, a
pour or a capacitor counts only for its own net. A power plane used as
reference is not considered.

Copper islands: after the fill a pour can be cut into separate pieces. When
the islands can be read (ZONE.GetFilledPolysList), a via counts only for the
piece of copper it really touches; otherwise the checks fall back to the
plain coverage test and say so in a note.
"""
import fnmatch
import math
import re
from dataclasses import dataclass, field

import pcbnew

from ..common import geometry
from ..common.i18n import _
from . import return_path
from .dc_current import copper_thickness_by_layer, ipc2221_limit_a
from .load_estimate import voltage_from_net
from .net_path import _via_radius

# Severity levels (same order as the traffic-light icons of the GUI:
# 1 = yellow, 2 = red)
SEV_WARNING = 1
SEV_ERROR = 2

# Keys of the checks (used for the settings and for the "Check" column)
CHECK_DECAP = "decap"
CHECK_LAYER_CHANGE = "layer_change"
CHECK_STITCHING = "stitching"
CHECK_PLANE_GAP = "plane_gap"
CHECK_PLANE_EDGE = "plane_edge"
CHECK_WIDTH = "width"
CHECK_ISOLATION = "isolation"
CHECK_LENGTH = "length"
CHECK_STUB = "stub"
CHECK_ACUTE = "acute"
CHECK_WIDTH_STEP = "width_step"
CHECK_VIA_IN_PAD = "via_in_pad"
CHECK_TOMBSTONE = "tombstone"
CHECK_VIA_CURRENT = "via_current"
CHECK_CRYSTAL = "crystal"
CHECK_BROADSIDE = "broadside"

# Order of the checks in the table (and in the progress bar)
CHECK_ORDER = (CHECK_DECAP, CHECK_LAYER_CHANGE, CHECK_STITCHING, CHECK_PLANE_GAP,
               CHECK_PLANE_EDGE, CHECK_WIDTH, CHECK_ISOLATION, CHECK_LENGTH,
               CHECK_STUB, CHECK_ACUTE, CHECK_WIDTH_STEP, CHECK_VIA_IN_PAD,
               CHECK_TOMBSTONE, CHECK_VIA_CURRENT, CHECK_CRYSTAL, CHECK_BROADSIDE)

# Voltage difference above which the isolation check applies: up to 30 V the
# IPC-2221 distance is 0.1 mm or less, always met by the normal DRC clearance
ISOLATION_MIN_DV = 30.0

# Reference prefixes of the integrated circuits whose supply pins are checked
IC_PREFIXES = ("U", "IC")

# Words that identify a supply net when the pin type is not available (net
# names such as VCC, +3V3, VDD_IO, VBAT...). The voltage written in the name
# (voltage_from_net) is the other clue.
_POWER_WORDS = re.compile(r"(VCC|VDD|VBAT|VBUS|VIN|VSYS|VREF|VCORE|VIO|VAA|VPP|AVCC|DVCC|PWR|^V\+|^\+)")

# Grounds with a name different from the reference filter: never treated as
# supply nets
_GROUND_WORDS = re.compile(r"(GND|VSS|VEE_GND|EARTH|CHASSIS)")

# Maximum number of grid points per layer for the stitching check: on large
# boards the grid step grows so the check does not take minutes
MAX_GRID_POINTS = 40000



@dataclass
class CheckSettings:
    """
    Thresholds and switches of the checks (from the GUI).

    The default values are good-practice rules for a generic board (digital
    logic up to a few hundred MHz); the GUI uses them as its defaults too:
    - decoupling capacitor within 3 mm of the pin (warning), 8 mm (error),
      edge to edge: beyond about 10 mm a 100 nF capacitor decouples little;
    - ground via within 1 mm of a GND pad (the via goes right next to it);
    - return via within 2 mm of a signal via that changes reference plane;
    - stitching vias every 10 mm (about lambda/20 at 750 MHz in FR4; RF
      areas need less, e.g. 5 mm for GNSS at 1.5 GHz);
    - plane gaps from 5 mm (shorter gaps are the crossings of tracks on the
      other side, unavoidable on two layers);
    - plane edge at least 3 h from the track (h = dielectric between the
      track and its plane): within 3 h most of the field is on the plane;
    - track width for a 10 °C rise (IPC-2221), error beyond 20 °C;
    - skew of the differential pairs up to 0.5 mm, length groups within 2 mm.
    """

    ref_filter: str = "GND"           # substring of the ground net name
    do_decap: bool = True
    do_layer_change: bool = True
    do_stitching: bool = True
    do_plane_gap: bool = True
    # Decoupling: distance pin -> capacitor (warning / error) and
    # capacitor ground pad -> ground via
    decap_warn_mm: float = 3.0
    decap_err_mm: float = 8.0
    gnd_via_mm: float = 1.0
    # Layer change: distance signal via -> ground via (warning; error at 2x)
    return_via_mm: float = 2.0
    # Supply nets are skipped in the layer-change check (their vias are
    # many and their return is handled by the decoupling capacitors)
    skip_power_nets: bool = True
    # Stitching: maximum distance between ground vias (grid spacing)
    stitch_spacing_mm: float = 10.0
    # Plane gaps: minimum gap length, as in the Return Path tab
    min_gap_mm: float = 5.0
    # Read the copper islands of the ground fill: a via counts only for the
    # piece of copper it really touches
    use_islands: bool = True
    # --- Checks 5-8 ---
    do_plane_edge: bool = True
    do_width: bool = True
    do_isolation: bool = True
    do_length: bool = True
    # Plane edge: minimum distance track edge -> plane edge, in multiples of
    # the dielectric height h (error below 1 h)
    edge_h_factor: float = 3.0
    # Track width: allowed temperature rise (°C), error beyond twice as much
    delta_t: float = 10.0
    # Net data typed by the user, "pattern = value" separated by ';'
    # (see parse_net_values): currents in A, voltages in V
    currents: str = ""
    voltages: str = ""
    # Lengths: maximum skew of a differential pair, maximum difference
    # inside a group, and the groups ("SD_*, SD_CLK; ETH_TX*": one group per
    # ';', patterns separated by ',')
    skew_mm: float = 0.5
    group_tol_mm: float = 2.0
    groups: str = ""
    # --- Checks 9-16 ---
    do_stub: bool = True
    do_acute: bool = True
    do_width_step: bool = True
    do_via_in_pad: bool = True
    do_tombstone: bool = True
    do_via_current: bool = True
    do_crystal: bool = True
    do_broadside: bool = True
    # Stub: dead branches from this length (error beyond 5x)
    stub_mm: float = 1.0
    # Acute angles: tracks meeting at less than this (degrees)
    acute_deg: float = 90.0
    # Width steps: difference between the widths of a net (% of the narrower)
    width_step_pct: float = 25.0
    # Current in the vias: plating of the via barrel (from the Options tab)
    via_plating_um: float = 25.0
    # Crystal: maximum length of the tracks between crystal and IC
    crystal_mm: float = 10.0
    # Broadside coupling: overlap length of two tracks on adjacent layers
    broadside_mm: float = 5.0


@dataclass
class LayoutIssue:
    """One problem found by the checks, as shown in a row of the GUI table."""

    severity: int        # SEV_WARNING or SEV_ERROR
    check: str           # CHECK_... key
    obj: str             # object involved, e.g. "U3.7 (+3V3)"
    detail: str          # explanation, already translated
    measured_mm: float = None  # measured value (None = not applicable)
    limit_mm: float = None     # threshold it was compared with
    x_nm: int = 0        # position on the board, for the marker
    y_nm: int = 0
    items: list = field(default_factory=list)   # pcbnew objects to select
    # Stitching areas: outline of the area as polygons [(outer, [holes])],
    # each a list of (x, y) in nm, drawn as a filled shape on the board
    polys: list = field(default_factory=list)
    # End of the measure (x, y in nm), e.g. the via used for a stitching
    # area: a segment with the value is drawn from (x_nm, y_nm) to here
    ref_xy: tuple = None
    # Unit of measured_mm / limit_mm in the table: "mm" (most checks), "°"
    # (angles), "%" (width steps), "via" (number of vias)
    unit: str = "mm"


# ---------------------------------------------------------------- helpers

def _mm(nm):
    """Nanometers (KiCad internal unit) -> millimeters."""
    return nm / 1e6


def _dist(ax, ay, bx, by):
    """Euclidean distance between two points (same unit as the arguments)."""
    return math.hypot(ax - bx, ay - by)


def _is_ref_net(name, ref_filter):
    """True if the net is the ground reference (substring, case-insensitive)."""
    return bool(name) and ref_filter.upper() in name.upper()


def is_power_net(name, ref_filter="GND"):
    """
    True if the net name looks like a supply: a voltage in the name (+3V3,
    5V, VCC_3.3) or a typical supply word (VCC, VDD, VBAT...). Grounds and
    the automatic names of unconnected pins are excluded.
    """
    if not name or _is_ref_net(name, ref_filter):
        return False
    up = name.upper()
    if up.startswith("UNCONNECTED") or _GROUND_WORDS.search(up):
        return False
    # Automatic KiCad names "Net-(U1-Pad3)": the part between brackets is a
    # pin name, not a supply, unless it explicitly contains one (e.g.
    # "Net-(U1-VDD)")
    core = up[5:-1] if up.startswith("NET-(") and up.endswith(")") else up
    return voltage_from_net(core) is not None or bool(_POWER_WORDS.search(core))


def _ref_prefix(ref):
    """Letters at the start of a reference: 'U12' -> 'U', 'IC3' -> 'IC'."""
    out = ""
    for ch in ref:
        if not ch.isalpha():
            break
        out += ch
    return out.upper()


def _pad_ref(pad):
    """
    Reference of the footprint owning the pad ('?' if not available).
    GetParentFootprint() returns the footprint in KiCad 8-10, a generic
    container in KiCad 7: GetParent() is the fallback.
    """
    for getter in ("GetParentFootprint", "GetParent"):
        try:
            return getattr(pad, getter)().GetReference()
        except AttributeError:
            continue
    return "?"


def _pad_label(pad):
    """Readable pad label, e.g. 'U3.7' (same format as the other tabs)."""
    num = pad.GetNumber() if hasattr(pad, "GetNumber") else pad.GetName()
    return f"{_pad_ref(pad)}.{num}"


def _pin_type(pad):
    """Electrical type of the pin from the schematic ('' if not available)."""
    try:
        return (pad.GetPinType() or "").lower()
    except Exception:
        return ""


def _is_pth(pad):
    """True for a plated through-hole pad (it connects all the copper layers)."""
    try:
        return pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
    except Exception:
        return False


def _pad_copper_layers(pad, cu_stack):
    """Copper layers the pad is on (all of them for a through-hole pad)."""
    return [l for l in cu_stack if pad.IsOnLayer(l)]


class _PointIndex:
    """
    Simple spatial index (uniform grid of buckets) of points with a payload,
    to find the nearest ground via without scanning all the vias every time.
    """

    def __init__(self, cell_nm):
        self.cell = max(int(cell_nm), 1)
        self.buckets = {}

    def add(self, x, y, payload):
        key = (int(x // self.cell), int(y // self.cell))
        self.buckets.setdefault(key, []).append((x, y, payload))

    def within(self, x, y, max_nm, accept=None):
        """All the (center distance, payload) within max_nm, nearest first."""
        out = []
        reach = int(max_nm // self.cell) + 1
        cx, cy = int(x // self.cell), int(y // self.cell)
        for i in range(cx - reach, cx + reach + 1):
            for j in range(cy - reach, cy + reach + 1):
                for px, py, payload in self.buckets.get((i, j), ()):
                    if accept is not None and not accept(payload):
                        continue
                    d = _dist(x, y, px, py)
                    if d <= max_nm:
                        out.append((d, payload))
        out.sort(key=lambda t: t[0])
        return out

    def nearest(self, x, y, max_nm, accept=None):
        """
        Nearest point within max_nm (None if there is none). 'accept'
        (payload -> bool) filters the candidates, e.g. vias that reach a
        given layer. Returns (distance_nm, payload).
        """
        best = None
        reach = int(max_nm // self.cell) + 1
        cx, cy = int(x // self.cell), int(y // self.cell)
        for i in range(cx - reach, cx + reach + 1):
            for j in range(cy - reach, cy + reach + 1):
                for px, py, payload in self.buckets.get((i, j), ()):
                    if accept is not None and not accept(payload):
                        continue
                    d = _dist(x, y, px, py)
                    if d <= max_nm and (best is None or d < best[0]):
                        best = (d, payload)
        return best


# ------------------------------------------------- edge-to-edge distances
#
# The distances between a pad and a via (or another pad) are measured from
# copper edge to copper edge: a large pad whose edge is next to the via is
# fine even if its center is far. KiCad's SHAPE.Collide(other, clearance)
# says whether two shapes are closer than 'clearance': a bisection on the
# clearance gives the actual gap (resolution better than 1 um).

def _pad_shape(pad, layer=None):
    """Copper shape of the pad (on its first copper layer if none is given)."""
    if layer is None:
        layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    try:
        return pad.GetEffectiveShape(layer)
    except Exception:
        return pad.GetEffectiveShape()


def _bisect_gap(collides, max_nm):
    """
    Smallest clearance at which collides(clearance) is True, i.e. the gap
    between the two shapes (0 if they touch). None if beyond max_nm.
    """
    if collides(0):
        return 0.0
    hi = int(max_nm)
    if not collides(hi):
        return None
    lo = 0
    while hi - lo > 500:  # 0.5 um
        mid = (lo + hi) // 2
        if collides(mid):
            hi = mid
        else:
            lo = mid
    return float(hi)


def _gap_point_pad(pad, x, y, max_nm, shape=None):
    """Distance from the point to the copper edge of the pad (0 inside)."""
    sh = shape or _pad_shape(pad)
    p = pcbnew.VECTOR2I(int(x), int(y))
    return _bisect_gap(lambda c: sh.Collide(p, int(c)), max_nm)


def _gap_pad_pad(pa, pb, max_nm):
    """Copper gap between two pads (seen from above, whatever their side)."""
    sa, sb = _pad_shape(pa), _pad_shape(pb)
    return _bisect_gap(lambda c: sa.Collide(sb, int(c)), max_nm)


def _item_radius(item):
    """Copper radius of a via (round); 0 for anything else."""
    return _via_radius(item) if item.Type() == pcbnew.PCB_VIA_T else 0.0


def _gap_item_pad(item, pad, max_nm, shape=None):
    """Copper gap between a via or a through-hole pad and a pad."""
    if item.Type() == pcbnew.PCB_VIA_T:
        c = item.GetPosition()
        r = _via_radius(item)
        g = _gap_point_pad(pad, c.x, c.y, max_nm + r, shape)
        return None if g is None else max(g - r, 0.0)
    return _gap_pad_pad(item, pad, max_nm)


def _gap_item_via(item, via, max_nm):
    """Copper gap between a via or a through-hole pad and a (signal) via."""
    c = via.GetPosition()
    r = _via_radius(via)
    if item.Type() == pcbnew.PCB_VIA_T:
        q = item.GetPosition()
        return max(_dist(c.x, c.y, q.x, q.y) - r - _via_radius(item), 0.0)
    g = _gap_point_pad(item, c.x, c.y, max_nm + r)
    return None if g is None else max(g - r, 0.0)


def _pad_reach(pad):
    """Half diagonal of the pad's bounding box: how far its edge can be from its center."""
    bb = pad.GetBoundingBox()
    return math.hypot(bb.GetWidth(), bb.GetHeight()) / 2.0


def _nearest_by_gap(idx, x, y, max_gap_nm, reach_nm, gap_of, accept=None, max_candidates=12):
    """
    Nearest element of the index measured edge to edge: the candidates are
    taken by center distance (within max_gap + reach, where reach covers the
    size of the pad and of the vias), then gap_of(payload) gives the real
    copper gap. Returns (gap_nm, payload) or None.
    """
    best = None
    for _d, pl in idx.within(x, y, max_gap_nm + reach_nm, accept)[:max_candidates]:
        g = gap_of(pl)
        if g is not None and g <= max_gap_nm and (best is None or g < best[0]):
            best = (g, pl)
    return best


class _Islands:
    """
    Ground fill of every layer, split into its copper ISLANDS: the separate
    pieces of copper a zone becomes after the fill (a row of tracks or a slot
    can cut a pour in two). Two points are on the same island only if the
    copper really joins them.

    The islands are read with ZONE.GetFilledPolysList(layer): every outline
    of the polygon set is one island (with its holes). If that call is not
    available or fails, the class falls back to the plain coverage test
    (HitTestFilledArea) and every island key is None ("not known").
    """

    def __init__(self, gnd_zones, enabled=True):
        self.zones = gnd_zones
        self.boxes = {l: [z.GetBoundingBox() for z in zs] for l, zs in gnd_zones.items()}
        self.enabled = False
        self.layers = {}  # layer -> [(zone no., net, polygon set, [(outline no., bbox)])]
        if not enabled:
            return
        try:
            for l, zones in gnd_zones.items():
                entries = []
                for zn, z in enumerate(zones):
                    polys = z.GetFilledPolysList(l)
                    outlines = [(i, polys.Outline(i).BBox()) for i in range(polys.OutlineCount())]
                    entries.append((zn, z.GetNetname(), polys, outlines))
                self.layers[l] = entries
            self.enabled = True
        except Exception:
            self.layers = {}  # fallback: coverage test only

    @staticmethod
    def _in_box(bb, x, y, margin):
        """True if (x, y) is inside the bounding box enlarged by 'margin'."""
        return (bb.GetLeft() - margin <= x <= bb.GetRight() + margin
                and bb.GetTop() - margin <= y <= bb.GetBottom() + margin)

    def find(self, layer, x, y, accuracy=0):
        """
        Ground fill at the point (within 'accuracy' nm): (net, island key) or
        None if there is no ground copper there. The key is None when the
        islands are not available.
        """
        p = pcbnew.VECTOR2I(int(x), int(y))
        acc = int(accuracy)
        if self.enabled:
            for zn, net, polys, outlines in self.layers.get(layer, ()):
                for i, bb in outlines:
                    if self._in_box(bb, x, y, acc) and polys.Contains(p, i, acc):
                        return net, (zn, i)
            return None
        for z, zb in zip(self.zones.get(layer, ()), self.boxes.get(layer, ())):
            if self._in_box(zb, x, y, acc) and z.HitTestFilledArea(layer, p, acc):
                return z.GetNetname(), None
        return None

    def find_ring(self, layer, cx, cy, radius_nm, n=8):
        """
        Ground fill around (cx, cy): the first of n points on a circle that is
        covered, as (net, island key), or None. A ring is used because the
        fill always has a clearance hole around a via or a pad of another
        net: the center itself is never covered.
        """
        for k in range(n):
            a = 2 * math.pi * k / n
            f = self.find(layer, cx + radius_nm * math.cos(a), cy + radius_nm * math.sin(a))
            if f is not None:
                return f
        return None


@dataclass
class _Stitch:
    """A ground via or through-hole ground pad, with where it is connected."""

    obj: object      # the pcbnew via or pad
    net: str         # its ground net (GND, AGND...)
    islands: dict    # {layer: island key} of the ground copper it touches

    def joins(self, layer, net, key):
        """True if it touches the given island (same net) on that layer."""
        if self.net != net or layer not in self.islands:
            return False
        return key is None or self.islands[layer] is None or self.islands[layer] == key


def _ground_stitch_index(board, ref_filter, cu_stack, islands, cell_nm):
    """
    Index of the elements that tie the ground layers together: vias of a
    ground net and plated through-hole pads of a ground net. Each one records
    the island it touches on every layer where it is really connected to the
    pour of ITS OWN net: a via that crosses a layer where the pour is missing
    around it (e.g. inside a plane split), or where the pour belongs to
    another ground (AGND vs GND), does not count for that layer.
    """
    idx = _PointIndex(cell_nm)
    touch = pcbnew.FromMM(0.05)  # small tolerance on the copper edge

    def connected(item, net, x, y, radius):
        found = {}
        for l in cu_stack:
            if not item.IsOnLayer(l):
                continue
            # Connected if the fill touches the copper of the element: with a
            # solid connection it covers it, with a thermal relief the spokes
            # reach it (search within the radius of the element)
            f = islands.find(l, x, y, radius + touch)
            if f is not None and f[0] == net:
                found[l] = f[1]
        return found

    for t in board.GetTracks():
        if t.Type() != pcbnew.PCB_VIA_T or not _is_ref_net(t.GetNetname(), ref_filter):
            continue
        p, net = t.GetPosition(), t.GetNetname()
        idx.add(p.x, p.y, _Stitch(t, net, connected(t, net, p.x, p.y, _via_radius(t))))
    for pad in board.GetPads():
        if _is_pth(pad) and _is_ref_net(pad.GetNetname(), ref_filter):
            p, net = pad.GetPosition(), pad.GetNetname()
            bb = pad.GetBoundingBox()
            radius = max(bb.GetWidth(), bb.GetHeight()) / 2.0
            idx.add(p.x, p.y, _Stitch(pad, net, connected(pad, net, p.x, p.y, radius)))
    return idx


def _ground_zones_by_layer(board, ref_filter, cu_stack):
    """Filled ground zones of every copper layer: {layer: [zones]}."""
    return {l: geometry.find_reference_zones(board, l, ref_filter) for l in cu_stack}


# ------------------------------------------------------- 1. decoupling

def check_decoupling(board, s, cu_stack, gnd_zones, stitch_idx):
    """
    Decoupling capacitors.

    For every supply pin of an integrated circuit (U*, IC*): the nearest
    capacitor (C*) with one pad on the same supply net and the other on the
    SAME ground net as the IC's ground pins (a capacitor to AGND does not
    decouple a chip grounded on DGND). The distance is measured copper edge
    to copper edge between the IC pad and the capacitor pad on the supply
    net. Pins not connected to anything (alone on their net) are skipped.

    For every capacitor found and every SMD ground pin of an IC: a via of the
    same ground net, connected to its pour on another layer (the plane),
    within 'gnd_via_mm' of the pad, again measured edge to edge (pad copper
    to via copper). Not needed if that ground exists only on the pad's own
    layer.
    """
    issues = []
    ref = s.ref_filter

    # Decoupling capacitors grouped by supply net: {net: [(cap, pwr_pad, gnd_pad)]}
    caps_by_net = {}
    for fp in board.GetFootprints():
        if _ref_prefix(fp.GetReference()) != "C":
            continue
        pads = list(fp.Pads())
        nets = {p.GetNetname() for p in pads}
        if len(nets) != 2:
            continue  # not a two-terminal capacitor between two nets
        gnd = [p for p in pads if _is_ref_net(p.GetNetname(), ref)]
        pwr = [p for p in pads if p.GetNetname() and not _is_ref_net(p.GetNetname(), ref)]
        if gnd and pwr:
            caps_by_net.setdefault(pwr[0].GetNetname(), []).append((fp, pwr[0], gnd[0]))

    def ground_via_issue(pad, what):
        """Issue if the SMD ground pad has no ground via close enough (or None)."""
        if _is_pth(pad):
            return None  # a through-hole pad is itself the connection
        net = pad.GetNetname()
        pad_layers = set(_pad_copper_layers(pad, cu_stack))
        # Layers with a pour of the SAME ground net: a via is needed only if
        # that ground also exists on another layer than the pad's own
        net_layers = {l for l, zs in gnd_zones.items() if any(z.GetNetname() == net for z in zs)}
        if not (net_layers - pad_layers):
            return None
        p = pad.GetPosition()
        limit = pcbnew.FromMM(s.gnd_via_mm)

        # The via must be of the same net and connected to its pour on
        # another layer (the plane)
        def to_plane(st):
            return st.net == net and any(l not in pad_layers for l in st.islands)

        # Distance pad edge -> via edge (the shape of the pad is read once)
        shape = _pad_shape(pad)
        reach = _pad_reach(pad) + pcbnew.FromMM(1.0)  # pad size + via radius

        def gap(st):
            return _gap_item_pad(st.obj, pad, pcbnew.FromMM(50), shape)

        if _nearest_by_gap(stitch_idx, p.x, p.y, limit, reach, gap, to_plane) is not None:
            return None
        far = _nearest_by_gap(stitch_idx, p.x, p.y, pcbnew.FromMM(50), reach, gap, to_plane)
        measured = _mm(far[0]) if far else None
        detail = (_("{0}: nessuna via di massa entro {1:g} mm dal pad GND; la via piu' vicina e' a {2:.1f} mm")
                  .format(what, s.gnd_via_mm, measured) if measured is not None else
                  _("{0}: nessuna via di massa entro 50 mm dal pad GND").format(what))
        return LayoutIssue(SEV_WARNING, CHECK_DECAP, f"{_pad_label(pad)} ({net})", detail,
                           measured, s.gnd_via_mm, p.x, p.y, [pad])

    # Number of pads and tracks of every net: a supply pin alone on its net
    # (no other pad, no track) is not connected to anything and needs no
    # capacitor
    pads_per_net, tracks_per_net = {}, {}
    for pd in board.GetPads():
        pads_per_net[pd.GetNetname()] = pads_per_net.get(pd.GetNetname(), 0) + 1
    for t in board.GetTracks():
        tracks_per_net[t.GetNetname()] = tracks_per_net.get(t.GetNetname(), 0) + 1

    def unconnected(net):
        return (net.lower().startswith("unconnected")
                or (pads_per_net.get(net, 0) <= 1 and not tracks_per_net.get(net)))

    checked_caps = set()  # each capacitor's ground is checked once
    for fp in board.GetFootprints():
        if _ref_prefix(fp.GetReference()) not in IC_PREFIXES:
            continue
        # Ground nets of this IC (GND, or AGND/DGND on mixed-signal chips)
        ic_grounds = {pd.GetNetname() for pd in fp.Pads() if _is_ref_net(pd.GetNetname(), ref)}
        for pad in fp.Pads():
            net = pad.GetNetname()
            if not net or unconnected(net):
                continue  # pin not connected to anything
            ptype = _pin_type(pad)
            # Ground pin of the IC: only the ground-via check
            if _is_ref_net(net, ref):
                iss = ground_via_issue(pad, _("Pin di massa dell'integrato"))
                if iss:
                    issues.append(iss)
                continue
            # Supply pin: type "power_in" from the schematic, or a net whose
            # name looks like a supply (symbols often mark VDD as passive).
            # A pin declared as input/output/bidirectional... is a signal even
            # if its net name contains a voltage (e.g. "CLK_5V_EN"): the name
            # is trusted only for passive, unspecified or unknown pins
            if ptype.startswith("power_in"):
                pass
            elif ptype in ("", "passive", "unspecified") and is_power_net(net, ref):
                pass
            else:
                continue
            p = pad.GetPosition()
            label = f"{_pad_label(pad)} ({net})"
            all_caps = caps_by_net.get(net, [])
            # Only the capacitors to the IC's own ground (all of them if the
            # IC has no ground pin on the board)
            candidates = [c for c in all_caps if not ic_grounds or c[2].GetNetname() in ic_grounds]
            if not candidates:
                if all_caps:
                    other = ", ".join(sorted({c[2].GetNetname() for c in all_caps}))
                    detail = _("I condensatori fra {0} e massa vanno verso {1}, non verso la massa "
                               "dell'integrato ({2})").format(net, other, ", ".join(sorted(ic_grounds)))
                else:
                    detail = _("Nessun condensatore fra {0} e massa: pin di alimentazione senza "
                               "disaccoppiamento").format(net)
                issues.append(LayoutIssue(SEV_ERROR, CHECK_DECAP, label, detail,
                                          None, s.decap_warn_mm, p.x, p.y, [pad]))
                continue
            # Nearest capacitor, measured edge to edge between the IC pin and
            # the capacitor pad on the supply net. The 6 closest by center are
            # measured exactly (a bigger pad can be closer by its edge).
            by_center = sorted(candidates, key=lambda c: _dist(p.x, p.y, c[1].GetPosition().x,
                                                               c[1].GetPosition().y))[:6]
            measured_caps = []
            for c, cp, cg in by_center:
                g = _gap_pad_pad(pad, cp, pcbnew.FromMM(200))
                if g is None:
                    g = _dist(p.x, p.y, cp.GetPosition().x, cp.GetPosition().y)
                measured_caps.append((g, c, cp, cg))
            d, cap, cpwr, cgnd = min(measured_caps, key=lambda t: t[0])
            d_mm = _mm(d)
            cap_ref = cap.GetReference()
            # Capacitor on the other side of the board: noted in the text
            side = ""
            if set(_pad_copper_layers(cpwr, cu_stack)).isdisjoint(_pad_copper_layers(pad, cu_stack)):
                side = _(" (sul lato opposto)")
            if d_mm > s.decap_warn_mm:
                sev = SEV_ERROR if d_mm > s.decap_err_mm else SEV_WARNING
                issues.append(LayoutIssue(
                    sev, CHECK_DECAP, label,
                    _("Condensatore piu' vicino {0}{1} a {2:.1f} mm dal pin").format(cap_ref, side, d_mm),
                    d_mm, s.decap_warn_mm, p.x, p.y, [pad, cap]))
            # Ground connection of the nearest capacitor
            if cap_ref not in checked_caps:
                checked_caps.add(cap_ref)
                iss = ground_via_issue(cgnd, _("Condensatore {0}").format(cap_ref))
                if iss:
                    iss.items.append(cap)
                    issues.append(iss)
    return issues


# ---------------------------------------------- 2. layer change without return

def _via_signal_layers(board, via, tracks_by_net, pads_by_net, cu_stack):
    """
    Copper layers where the signal actually arrives at the via: tracks of the
    same net with an end on the via, and pads of the same net touching it
    (via in pad).
    """
    net = via.GetNetname()
    vp = via.GetPosition()
    r = _via_radius(via)
    layers = set()
    for t in tracks_by_net.get(net, ()):
        for end in (t.GetStart(), t.GetEnd()):
            if _dist(end.x, end.y, vp.x, vp.y) <= r + t.GetWidth() / 2.0:
                layers.add(t.GetLayer())
    for pad in pads_by_net.get(net, ()):
        if pad.GetBoundingBox().Contains(vp):
            layers.update(_pad_copper_layers(pad, cu_stack))
    return {l for l in layers if via.IsOnLayer(l)}


def _adjacent(cu_stack, layer):
    """Copper layers physically next to 'layer' (above and below)."""
    try:
        i = cu_stack.index(layer)
    except ValueError:
        return []
    return [cu_stack[k] for k in (i - 1, i + 1) if 0 <= k < len(cu_stack)]


def check_layer_changes(board, s, cu_stack, islands, stitch_idx, progress=None, cancel=None):
    """
    Signal vias where the reference plane changes.

    For every layer where the signal arrives at the via, the reference is
    the ground copper of the adjacent layers around the via: (layer, net,
    island). If the layers of the signal have DIFFERENT references (e.g. top
    over L2, bottom over L3, or on two layers: top over the bottom pour and
    bottom over the top pour) the return must move from one to the other:
    - same ground net: a ground via touching ALL the reference islands should
      be within 'return_via_mm' (error beyond twice as much);
    - different ground nets (GND and AGND): no via can join them, the return
      can only pass through a capacitor or a link between the grounds (error).
    """
    issues = []
    ref = s.ref_filter
    tracks_by_net, pads_by_net = {}, {}
    vias = []
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            vias.append(t)
        elif t.Type() == pcbnew.PCB_TRACE_T:
            tracks_by_net.setdefault(t.GetNetname(), []).append(t)
    for pad in board.GetPads():
        pads_by_net.setdefault(pad.GetNetname(), []).append(pad)

    limit = pcbnew.FromMM(s.return_via_mm)
    total = len(vias)
    for i, via in enumerate(vias):
        if progress and i % 20 == 0:
            progress(i, total)
        if cancel and cancel():
            break
        net = via.GetNetname()
        if not net or _is_ref_net(net, ref):
            continue
        if s.skip_power_nets and is_power_net(net, ref):
            continue
        sig_layers = _via_signal_layers(board, via, tracks_by_net, pads_by_net, cu_stack)
        if len(sig_layers) < 2:
            continue  # the signal does not change layer here
        vp = via.GetPosition()
        # Ring just outside the clearance hole of the via
        ring = _via_radius(via) + pcbnew.FromMM(0.8)
        refs = {}
        for l in sig_layers:
            found = set()
            for a in _adjacent(cu_stack, l):
                f = islands.find_ring(a, vp.x, vp.y, ring)
                if f is not None:
                    found.add((a, f[0], f[1]))  # (layer, ground net, island)
            refs[l] = frozenset(found)
        all_refs = frozenset().union(*refs.values())
        # Same reference on every layer (or no reference at all, which is the
        # business of the plane-gap check): nothing to do
        if len(all_refs) < 2 or len(set(refs.values())) == 1:
            continue

        layers_txt = " / ".join(board.GetLayerName(l) for l in sorted(sig_layers, key=cu_stack.index))
        planes_txt = " / ".join(f"{board.GetLayerName(a)} {n}"
                                for a, n, _k in sorted(all_refs, key=lambda r: cu_stack.index(r[0])))
        nets = {n for _a, n, _k in all_refs}
        if len(nets) > 1:
            # Planes of different grounds: no via can join them
            issues.append(LayoutIssue(
                SEV_ERROR, CHECK_LAYER_CHANGE, net,
                _("Cambio layer {0}: il riferimento passa fra masse diverse ({1}); nessuna via puo' "
                  "collegarle, serve un condensatore o un collegamento fra le masse vicino alla via").format(
                    layers_txt, planes_txt),
                None, s.return_via_mm, vp.x, vp.y, [via]))
            continue

        # A ground via (or through-hole ground pad) that touches every
        # reference island involved
        def reaches(st):
            return all(st.joins(a, n, k) for a, n, k in all_refs)

        # Distance via edge -> ground via edge
        reach = _via_radius(via) + pcbnew.FromMM(1.5)

        def gap(st):
            return _gap_item_via(st.obj, via, pcbnew.FromMM(50))

        hit = _nearest_by_gap(stitch_idx, vp.x, vp.y, 2 * limit, reach, gap, reaches)
        d_mm = _mm(hit[0]) if hit else None
        if d_mm is not None and d_mm <= s.return_via_mm:
            continue
        sev = SEV_WARNING if d_mm is not None else SEV_ERROR
        if d_mm is None:
            far = _nearest_by_gap(stitch_idx, vp.x, vp.y, pcbnew.FromMM(50), reach, gap, reaches)
            d_mm = _mm(far[0]) if far else None
            detail = _("Cambio layer {0}: il riferimento passa fra i piani {1}, nessuna via di massa entro {2:g} mm").format(
                layers_txt, planes_txt, 2 * s.return_via_mm)
        else:
            detail = _("Cambio layer {0}: il riferimento passa fra i piani {1}, via di massa a {2:.1f} mm").format(
                layers_txt, planes_txt, d_mm)
        items = [via] + ([hit[1].obj] if hit else [])
        issues.append(LayoutIssue(sev, CHECK_LAYER_CHANGE, net, detail,
                                  d_mm, s.return_via_mm, vp.x, vp.y, items))
    return issues


# ------------------------------------------------------- 3. stitching vias

def cells_outline(cells):
    """
    Outline of a set of grid cells (i, j) as polygons with holes, in grid
    units (cell (i, j) is the square from (i, j) to (i + 1, j + 1)).

    Every side of a cell that does not touch another cell of the set is a
    boundary edge; the edges are oriented with the area on their left and
    chained into closed loops. Loops with positive area are outlines, the
    others are holes, assigned to the outline that contains them. Returns
    [(outer points, [hole points, ...]), ...] with the collinear points
    removed.
    """
    cells = set(cells)
    edges = {}  # start vertex -> list of end vertices
    for i, j in cells:
        if (i, j - 1) not in cells:
            edges.setdefault((i, j), []).append((i + 1, j))
        if (i + 1, j) not in cells:
            edges.setdefault((i + 1, j), []).append((i + 1, j + 1))
        if (i, j + 1) not in cells:
            edges.setdefault((i + 1, j + 1), []).append((i, j + 1))
        if (i - 1, j) not in cells:
            edges.setdefault((i, j + 1), []).append((i, j))

    def turn_rank(d_in, d_out):
        # Preference at a vertex shared by two loops (cells touching only at
        # a corner): left turn first, then straight, then right. This keeps
        # each loop hugging its own cells.
        cross = d_in[0] * d_out[1] - d_in[1] * d_out[0]
        dot = d_in[0] * d_out[0] + d_in[1] * d_out[1]
        return 0 if cross > 0 else (1 if dot > 0 else 2)

    loops = []
    while edges:
        start = next(iter(edges))
        loop = [start]
        cur = start
        prev_dir = None
        while True:
            outs = edges[cur]
            if prev_dir is None or len(outs) == 1:
                nxt = outs[0]
            else:
                nxt = min(outs, key=lambda e: turn_rank(prev_dir, (e[0] - cur[0], e[1] - cur[1])))
            outs.remove(nxt)
            if not outs:
                del edges[cur]
            prev_dir = (nxt[0] - cur[0], nxt[1] - cur[1])
            cur = nxt
            if cur == start:
                break
            loop.append(cur)
        # Remove the collinear points (keep only the corners)
        n = len(loop)
        corners = []
        for k in range(n):
            a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
            if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
                corners.append(b)
        loops.append(corners)

    def area(pts):
        return sum(pts[k - 1][0] * pts[k][1] - pts[k][0] * pts[k - 1][1] for k in range(len(pts))) / 2.0

    def inside(pt, poly):
        # Ray casting; the test point is moved by a quarter cell so it never
        # lies on an edge
        x, y = pt[0] + 0.25, pt[1] + 0.25
        res = False
        for k in range(len(poly)):
            (x1, y1), (x2, y2) = poly[k - 1], poly[k]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                res = not res
        return res

    outers = [lp for lp in loops if area(lp) > 0]
    holes = [lp for lp in loops if area(lp) < 0]
    result = [(o, []) for o in outers]
    for hl in holes:
        # The smallest outline containing the hole
        owners = [r for r in result if inside(hl[0], r[0])]
        if owners:
            min(owners, key=lambda r: area(r[0]))[1].append(hl)
    return result




def check_stitching(board, s, cu_stack, gnd_zones, islands, stitch_idx, progress=None, cancel=None):
    """
    Distance between stitching vias.

    Applies only when ground is poured on at least two layers. The board is
    scanned with a grid; on every layer, each point of ground copper must be
    within spacing / sqrt(2) of a via of the SAME ground net touching the
    SAME copper island (that is the farthest point of a square grid of vias
    with the given spacing). A via just across a slot, on another piece of
    copper, does not count. The points beyond are grouped into areas (per
    island): one row per area, with the largest distance found (error beyond
    twice the limit). An island with no via at all is always an error.
    """
    issues = []
    # Ground nets poured on two or more layers: only they need stitching (an
    # AGND pour on a single layer has nothing to be stitched to)
    net_layers = {}
    for l in cu_stack:
        for z in gnd_zones.get(l, ()):
            net_layers.setdefault(z.GetNetname(), set()).add(l)
    multi = {n for n, ls in net_layers.items() if len(ls) >= 2}
    if not multi:
        return issues, _("Ogni massa e' su un solo layer: controllo delle via di stitching non necessario.")
    layers = [l for l in cu_stack if any(z.GetNetname() in multi for z in gnd_zones.get(l, ()))]

    box = board.GetBoardEdgesBoundingBox()
    if box.GetWidth() <= 0 or box.GetHeight() <= 0:
        box = board.ComputeBoundingBox(True)
    x0, y0 = box.GetX(), box.GetY()
    w, h = box.GetWidth(), box.GetHeight()

    limit = pcbnew.FromMM(s.stitch_spacing_mm) / math.sqrt(2)
    # Grid step: a quarter of the limit (at most 2 mm), larger on big boards
    # so the points stay below MAX_GRID_POINTS per layer
    step = min(limit / 4.0, pcbnew.FromMM(2.0))
    step = max(step, math.sqrt(w * h / MAX_GRID_POINTS), pcbnew.FromMM(0.25))
    nx, ny = int(w // step) + 1, int(h // step) + 1

    def grid_xy(c):
        """Board coordinates (nm) of grid cell c = (i, j)."""
        return int(x0 + (c[0] + 0.5) * step), int(y0 + (c[1] + 0.5) * step)

    areas = []  # areas far from the vias, per layer (merged across layers below)
    for li, layer in enumerate(layers):
        if cancel and cancel():
            break

        def same_island(net, key, layer=layer):
            # Filter for the via index: same net, same island on this layer
            return lambda st: st.joins(layer, net, key)

        # (i, j) -> [distance to the nearest via (None = none within 3x), net, island]
        bad = {}
        for i in range(nx):
            if progress and i % 10 == 0:
                progress(li * nx + i, len(layers) * nx)
                if cancel and cancel():
                    break
            for j in range(ny):
                x, y = grid_xy((i, j))
                f = islands.find(layer, x, y)
                if f is None or f[0] not in multi:
                    continue  # no ground copper here, or a single-layer ground
                accept = same_island(*f)
                if stitch_idx.nearest(x, y, limit, accept=accept) is not None:
                    continue
                far = stitch_idx.nearest(x, y, 3 * limit, accept=accept)
                bad[(i, j)] = [far[0] if far else None, f[0], f[1]]

        # Areas: groups of adjacent bad points (8-connectivity) of the same
        # island, so two pieces of copper side by side stay separate rows
        seen = set()
        for start in bad:
            if start in seen:
                continue
            tag = (bad[start][1], bad[start][2])
            group, stack = [], [start]
            seen.add(start)
            while stack:
                c = stack.pop()
                group.append(c)
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        n = (c[0] + di, c[1] + dj)
                        if n in bad and n not in seen and (bad[n][1], bad[n][2]) == tag:
                            seen.add(n)
                            stack.append(n)
            if len(group) < 3:
                continue  # a lone point (thin copper finger): not reported
            net, key = tag
            accept = same_island(net, key)
            # Points with no via within 3x the limit get their real distance
            # with a search on the whole board, on at most ~200 of them
            far_pts = [c for c in group if bad[c][0] is None]
            stride = max(1, len(far_pts) // 200)
            for c in far_pts[::stride]:
                hit = stitch_idx.nearest(*grid_xy(c), w + h, accept=accept)
                bad[c][0] = hit[0] if hit else float("inf")
            # Worst point: the one farthest from a via
            worst = max(group, key=lambda c: -1 if bad[c][0] is None else bad[c][0])
            wd = bad[worst][0]
            if wd is not None and wd == float("inf"):
                wd = None  # no via at all on this island
            # Nearest via to the worst point: selected in Pcbnew when the
            # row is clicked (a real board object, the view centres there)
            near = stitch_idx.nearest(*grid_xy(worst), w + h, accept=accept)
            areas.append({"layer": layer, "net": net, "cells": set(group), "worst": worst,
                          "wd": wd, "via": near[1].obj if near else None})

    # The same region far from the vias usually shows up on every layer with
    # ground (the vias go through all of them). Areas of the same net on
    # different layers that are the SAME problem (they overlap, their worst
    # points coincide and the nearest via is the same one) become ONE row,
    # with all their layers. Areas that only touch stay separate rows.
    def via_key(ar):
        v = ar["via"]
        if v is None:
            return None
        pos = v.GetPosition()
        return (pos.x, pos.y)

    def same_problem(ai, aj):
        if ai["net"] != aj["net"] or ai["layer"] == aj["layer"]:
            return False
        if not (ai["cells"] & aj["cells"]):
            return False
        (i1, j1), (i2, j2) = ai["worst"], aj["worst"]
        return max(abs(i1 - i2), abs(j1 - j2)) <= 2 and via_key(ai) == via_key(aj)

    parent = list(range(len(areas)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(areas)):
        for j in range(i + 1, len(areas)):
            ai, aj = areas[i], areas[j]
            if same_problem(ai, aj):
                parent[root(i)] = root(j)
    clusters = {}
    for i, ar in enumerate(areas):
        clusters.setdefault(root(i), []).append(ar)

    for members in clusters.values():
        layers_in = sorted({m["layer"] for m in members}, key=cu_stack.index)
        lnames = ", ".join(board.GetLayerName(l) for l in layers_in)
        cells = set().union(*(m["cells"] for m in members))
        area_mm2 = len(cells) * _mm(step) ** 2
        net = members[0]["net"]
        # Worst member: an island without any via first, then the largest distance
        worst_m = max(members, key=lambda m: float("inf") if m["wd"] is None else m["wd"])
        wd = worst_m["wd"]
        wx, wy = grid_xy(worst_m["worst"])
        if wd is None:
            sev, measured = SEV_ERROR, None
            detail = _("Area di massa di circa {0:.0f} mm2 su {1} senza alcuna via di stitching").format(
                area_mm2, lnames)
        else:
            # Measured value: distance of the farthest point of the area from
            # its nearest via, compared with the maximum allowed distance
            # (spacing / sqrt(2), the farthest point of a square via grid)
            measured = _mm(wd)
            sev = SEV_ERROR if wd > 2 * limit else SEV_WARNING
            detail = _("Area di massa di circa {0:.0f} mm2 su {1}: il punto piu' lontano e' a {2:.1f} mm "
                       "dalla via di massa piu' vicina (massimo {3:.1f} mm con passo {4:g} mm)").format(
                area_mm2, lnames, _mm(wd), _mm(limit), s.stitch_spacing_mm)
        # Outline of the area in board coordinates: the corner (g_i, g_j) of
        # the grid is at x0 + g_i * step, y0 + g_j * step
        polys = [([(int(x0 + gi * step), int(y0 + gj * step)) for gi, gj in outer],
                  [[(int(x0 + gi * step), int(y0 + gj * step)) for gi, gj in hole] for hole in holes])
                 for outer, holes in cells_outline(cells)]
        # No object to select: clicking the row highlights the area shape
        obj = " + ".join(board.GetLayerName(l) for l in layers_in) + f" ({net})"
        ref_xy = None
        if wd is not None and worst_m["via"] is not None:
            vp = worst_m["via"].GetPosition()
            ref_xy = (vp.x, vp.y)
        issues.append(LayoutIssue(sev, CHECK_STITCHING, obj, detail, measured,
                                  round(_mm(limit), 1), wx, wy, [], polys, ref_xy))
    return issues, ""


# ------------------------------------------------------- 4. plane gaps

def check_plane_gaps(board, s, progress=None, cancel=None):
    """
    Tracks crossing a gap of the reference plane: the Return Path check on
    all the tracks of the board, converted to rows of this table.
    """
    issues = []
    found = return_path.analyze_board(board, reference_net_filter=s.ref_filter,
                                      min_gap_mm=s.min_gap_mm,
                                      progress_callback=progress, should_cancel=cancel)
    for it in found:
        p = it.uncovered_points[len(it.uncovered_points) // 2] if it.uncovered_points else it.track.GetStart()
        via_txt = _("via di stitching vicina") if it.has_nearby_stitching_via else _("nessuna via di stitching vicina")
        detail = _("{0} interrotto su {1} sotto la traccia su {2} ({3})").format(
            it.ref_net, it.ref_layer_name, it.track_layer_name, via_txt)
        sev = SEV_WARNING if it.has_nearby_stitching_via else SEV_ERROR
        issues.append(LayoutIssue(sev, CHECK_PLANE_GAP, it.net_name, detail,
                                  it.max_gap_mm, s.min_gap_mm, p.x, p.y, [it.track]))
    return issues


# ------------------------------------------------------- shared helpers 5-8

def parse_net_values(text):
    """
    Parses the net data typed by the user: entries "pattern = value"
    separated by ';' or by new lines, e.g. "+5V = 2; VIN=3,5; HV* = 400".

    - the pattern is a net name, with the wildcards * and ? (case-insensitive);
    - ':' is accepted in place of '=';
    - the value accepts the decimal comma, the prefixes m and k and a unit
      letter: "500mA" -> 0.5, "1,5A" -> 1.5, "1k" -> 1000, "-12" -> -12.

    Returns (list of (pattern, value), list of the entries not understood).
    """
    out, bad = [], []
    for raw in re.split(r"[;\n]", text or ""):
        entry = raw.strip()
        if not entry:
            continue
        m = re.match(r"^(.+?)\s*[=:]\s*([-+]?\d+(?:[.,]\d+)?)\s*([mkK]?)\s*[A-Za-z]*\s*$", entry)
        if not m:
            bad.append(entry)
            continue
        value = float(m.group(2).replace(",", "."))
        value *= {"m": 1e-3, "k": 1e3, "K": 1e3}.get(m.group(3), 1.0)
        out.append((m.group(1).strip(), value))
    return out, bad


def _net_matches(net, pattern):
    """
    True if the net name matches the pattern (wildcards * ?, case-insensitive).
    Hierarchical names ("/power/+5V") also match by their last part ("+5V").
    """
    p = pattern.upper()
    n = net.upper()
    return fnmatch.fnmatchcase(n, p) or fnmatch.fnmatchcase(n.rsplit("/", 1)[-1], p)


def _value_for_net(net, entries):
    """Value of the first entry whose pattern matches the net (None if none)."""
    for pattern, value in entries:
        if _net_matches(net, pattern):
            return value
    return None


def _copper_tracks(board):
    """Tracks and arcs of the board (no vias)."""
    kinds = (pcbnew.PCB_TRACE_T, getattr(pcbnew, "PCB_ARC_T", -1))
    return [t for t in board.GetTracks() if t.Type() in kinds]


def _track_points(track, step_nm, max_samples=4000):
    """
    Points along a track every step_nm (also the arcs: their points are
    taken on the arc, not on the chord). Returns a list of (x, y) in nm.
    """
    if track.Type() == getattr(pcbnew, "PCB_ARC_T", -1):
        try:
            c = track.GetCenter()
            r = _dist(c.x, c.y, track.GetStart().x, track.GetStart().y)
            a0 = math.atan2(track.GetStart().y - c.y, track.GetStart().x - c.x)
            a1 = math.atan2(track.GetEnd().y - c.y, track.GetEnd().x - c.x)
            # Angle of the arc with its sign, from the middle point: the arc
            # goes from start to end THROUGH the middle
            mid = track.GetMid()
            am = math.atan2(mid.y - c.y, mid.x - c.x)
            sweep = (a1 - a0) % (2 * math.pi)
            if (am - a0) % (2 * math.pi) > sweep:
                sweep -= 2 * math.pi
            n = min(max_samples, max(2, int(abs(sweep) * r // step_nm) + 1))
            return [(c.x + r * math.cos(a0 + sweep * k / n), c.y + r * math.sin(a0 + sweep * k / n))
                    for k in range(n + 1)]
        except Exception:
            pass  # not a real arc for this KiCad version: sampled as a segment
    return [(p.x, p.y) for p in geometry.sample_points_along_track(track, step_nm, max_samples)]


def _cluster_points(points, radius):
    """
    Groups points (x, y, payload) that are within 'radius' of each other
    (chains of close points end up in the same group). Returns a list of
    groups, each a list of the input tuples.
    """
    idx = _PointIndex(radius)
    for k, (x, y, _pl) in enumerate(points):
        idx.add(x, y, k)
    seen, groups = set(), []
    for k in range(len(points)):
        if k in seen:
            continue
        group, stack = [], [k]
        seen.add(k)
        while stack:
            i = stack.pop()
            group.append(points[i])
            for _d, j in idx.within(points[i][0], points[i][1], radius):
                if j not in seen:
                    seen.add(j)
                    stack.append(j)
        groups.append(group)
    return groups


def _dielectric_to(stackup, cu_stack, layer, ref_layer):
    """
    Dielectric thickness (m) between a copper layer and an adjacent one,
    read from the stackup; None if not known.
    """
    info = stackup.get(layer) or {}
    side = "below" if cu_stack.index(ref_layer) > cu_stack.index(layer) else "above"
    diel = info.get(side)
    return diel[0] if diel else None


# ------------------------------------------------------- 5. plane edge

# Holes of the ground fill smaller than this (mm, largest side) are not a
# plane edge: they are the clearance holes around vias and pads of other
# nets, always present in a plane
EDGE_MIN_HOLE_MM = 2.0

# Narrow cuts in the ground fill are closed before measuring (morphological
# closing: grow the copper by this amount, then shrink it back): a cut up to
# twice this width disappears. Those cuts are the tracks of the plane layer
# itself (track + two clearances, typically 0.6-1.5 mm): on a two-layer
# board they are everywhere, and they are not where the plane "ends". Where
# a track crosses such a cut it is the business of the plane-gap check.
EDGE_CLOSE_MM = 1.0


def _close_narrow_cuts(polys, amount_nm):
    """
    Morphological closing of a SHAPE_POLY_SET in place: Inflate(+amount)
    then Inflate(-amount). The signature of Inflate changed between KiCad
    versions: KiCad 8-10 want (amount, corner strategy, max error), KiCad 7
    (amount, segments per circle). Returns False if neither works (the fill
    is then used as it is).
    """
    max_err = pcbnew.FromMM(0.005)
    variants = []
    strategy = getattr(pcbnew, "CORNER_STRATEGY_ROUND_ALL_CORNERS", None)
    if strategy is not None:
        variants.append(lambda a: polys.Inflate(a, strategy, max_err))      # KiCad 8-10
    variants.append(lambda a: polys.Inflate(a, 32))                          # KiCad 7
    for inflate in variants:
        try:
            inflate(int(amount_nm))
        except (TypeError, AttributeError):
            continue
        inflate(-int(amount_nm))
        return True
    return False


@dataclass
class _FillPiece:
    """One island of a ground fill, ready for the plane-edge check."""

    net: str          # ground net of the island
    outer: object     # SHAPE_LINE_CHAIN of its outer outline
    holes: list       # SHAPE_LINE_CHAINs of its holes larger than EDGE_MIN_HOLE_MM
    bbox: object      # bounding box of the outer outline
    keep: object      # the SHAPE_POLY_SET the chains belong to (kept alive)


def _pad_via_points(board):
    """
    Positions of all pads and vias, by copper layer: {layer: _PointIndex}.
    A hole of the ground fill that contains one of them is the clearance
    around that pad or via, not an edge of the plane.
    """
    out = {}
    cu = list(board.GetEnabledLayers().CuStack())

    def add(item, pos):
        for l in cu:
            if item.IsOnLayer(l):
                if l not in out:
                    out[l] = _PointIndex(pcbnew.FromMM(5))
                out[l].add(pos.x, pos.y, item)

    for pad in board.GetPads():
        add(pad, pad.GetPosition())
    for t in board.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            add(t, t.GetPosition())
    return out


def _hole_around_item(hole, points):
    """True if the hole (SHAPE_LINE_CHAIN) contains a pad or via position."""
    if points is None:
        return False
    bb = hole.BBox()
    cx, cy = bb.GetCenter().x, bb.GetCenter().y
    radius = math.hypot(bb.GetWidth(), bb.GetHeight()) / 2.0
    return any(hole.PointInside(pcbnew.VECTOR2I(int(x), int(y)))
               for x, y in ((pl.GetPosition().x, pl.GetPosition().y)
                            for _d, pl in points.within(cx, cy, radius)))


def _fill_pieces(gnd_zones, cu_stack, pad_points=None):
    """
    Real ground copper of every layer, as islands: {layer: [_FillPiece]}.

    The FILL is used (not the outline drawn by the designer): the copper
    really stops where the fill stops, e.g. at the copper-to-edge clearance
    of the board, around a slot, or where a track of the same layer passes.
    Small holes (antipads around vias and pads) are left out. Returns None
    if the fill cannot be read in this KiCad version.

    The SHAPE_POLY_SET of every zone is kept in the pieces (field 'keep'):
    the chains are references into it, and if Python freed it they would
    point to released memory (Pcbnew crashes).
    """
    min_hole = pcbnew.FromMM(EDGE_MIN_HOLE_MM)
    out = {}
    try:
        for layer in cu_stack:
            for z in gnd_zones.get(layer, ()):
                # KiCad keeps the fill "fractured": every hole is joined to
                # the outer outline by a zero-width slit, so the holes are not
                # separate and the slits would look like plane edges. A copy
                # is "unfractured" to get back real outlines with holes.
                polys = pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(layer))
                try:
                    polys.Unfracture()  # KiCad 9/10
                except TypeError:
                    polys.Unfracture(pcbnew.SHAPE_POLY_SET.PM_FAST)  # KiCad 7/8
                # The narrow cuts made by the tracks of this layer are not
                # plane edges: they are closed (see EDGE_CLOSE_MM)
                _close_narrow_cuts(polys, pcbnew.FromMM(EDGE_CLOSE_MM))
                for i in range(polys.OutlineCount()):
                    outer = polys.Outline(i)
                    holes = []
                    for k in range(polys.HoleCount(i)):
                        hole = polys.Hole(i, k)
                        hb = hole.BBox()
                        # Small holes, and holes around a pad or a via (the
                        # clearance of a connector pin can exceed 2 mm), are
                        # not plane edges
                        if max(hb.GetWidth(), hb.GetHeight()) < min_hole:
                            continue
                        if _hole_around_item(hole, (pad_points or {}).get(layer)):
                            continue
                        holes.append(hole)
                    out.setdefault(layer, []).append(
                        _FillPiece(z.GetNetname(), outer, holes, outer.BBox(), polys))
    except Exception:
        return None
    return out


def _edge_dist2(chain, p):
    """
    Squared distance (nm^2) from a point to the EDGES of a closed outline.
    SquaredDistance(p) alone returns 0 for a point inside the outline: the
    second argument (outline only) asks for the distance to its edges. If
    that variant is missing, the edges are measured one by one.
    """
    try:
        return chain.SquaredDistance(p, True)
    except TypeError:
        n = chain.PointCount()
        best = float("inf")
        for k in range(n):
            a, b = chain.CPoint(k), chain.CPoint((k + 1) % n)
            d = geometry.point_segment_distance(p.x, p.y, a.x, a.y, b.x, b.y)
            best = min(best, d * d)
        return best


def _in_box(bb, x, y):
    """True if the point is inside the bounding box."""
    return bb.GetLeft() <= x <= bb.GetRight() and bb.GetTop() <= y <= bb.GetBottom()


def _plane_under(pieces, p):
    """
    Ground copper under the point p (VECTOR2I) on one layer: (piece, edge
    distance nm, nearest edge point (x, y) or None) or None if there is no
    ground copper there (outside every island, or inside a large hole).
    """
    for pc in pieces:
        if not _in_box(pc.bbox, p.x, p.y) or not pc.outer.PointInside(p):
            continue
        if any(h.PointInside(p) for h in pc.holes):
            return None  # over a large hole: no plane here
        # Nearest edge: the outer outline or one of the large holes
        best_d2, best_chain = _edge_dist2(pc.outer, p), pc.outer
        for h in pc.holes:
            d2 = _edge_dist2(h, p)
            if d2 < best_d2:
                best_d2, best_chain = d2, h
        try:
            q = best_chain.NearestPoint(p)
            edge_xy = (q.x, q.y)
        except Exception:
            edge_xy = None  # no marker segment in this KiCad version
        return pc, math.sqrt(best_d2), edge_xy
    return None


def check_plane_edges(board, s, cu_stack, gnd_zones, stackup, progress=None, cancel=None):
    """
    Tracks running close to the edge of their reference plane.

    For every point of a signal track (sampled along it) the reference is
    the ground copper of an adjacent layer that lies under the point (the
    nearer layer if both). The MEASURE is the distance, seen from above,
    from the edge of the track to the point where that ground copper ends
    (the edge of the real fill: board edge clearance, slot, track of the
    plane layer...). The LIMIT is edge_h_factor x h, with h the dielectric
    between the track and that plane: closer than that a part of the field,
    and of the return current, has no plane under it (more emissions and
    crosstalk). Below 1 h it is an error.

    Not reported: stretches shorter than the limit (a track that only
    approaches the edge, e.g. towards a connector at the board edge), and
    the stretch near a point where the track leaves the plane (that is the
    business of the plane-gap check). The holes around vias and pads are
    not a plane edge.
    """
    issues = []
    ref = s.ref_filter
    fills = _fill_pieces(gnd_zones, cu_stack, _pad_via_points(board))
    if not fills:
        return issues
    tracks = [t for t in _copper_tracks(board)
              if t.GetNetname() and not _is_ref_net(t.GetNetname(), ref)
              and not (s.skip_power_nets and is_power_net(t.GetNetname(), ref))]

    # (net, layer, ref layer, ref net) -> [(x, y, (track, dist, limit, h, edge xy, half width))]
    flagged = {}
    # Points of the tracks with NO plane under them, by (net, layer): where a
    # track leaves the plane the crossing is the business of the plane-gap
    # check, so the stretch near that point is not reported again here
    off_plane = {}
    total = len(tracks)
    for i, t in enumerate(tracks):
        if progress and i % 50 == 0:
            progress(i, total)
            if cancel and cancel():
                break
        layer = t.GetLayer()
        # Adjacent layers with ground copper, each with its dielectric height
        refs = []
        for a in _adjacent(cu_stack, layer):
            if a not in fills:
                continue
            h = _dielectric_to(stackup, cu_stack, layer, a)
            refs.append((h if h else 0.2e-3, a))
        if not refs:
            continue
        refs.sort(key=lambda r: r[0])  # the nearer plane first
        half_w = t.GetWidth() / 2.0
        # Sampling step: a third of the smallest limit, between 0.1 and 0.5 mm
        step = min(max(refs[0][0] * 1e9 * s.edge_h_factor / 3.0, pcbnew.FromMM(0.1)), pcbnew.FromMM(0.5))
        for x, y in _track_points(t, step):
            p = pcbnew.VECTOR2I(int(x), int(y))
            hit = None
            for h_m, a in refs:
                found = _plane_under(fills[a], p)
                if found is not None:
                    hit = (h_m, a, found)
                    break
            if hit is None:
                key = (t.GetNetname(), layer)
                if key not in off_plane:
                    off_plane[key] = _PointIndex(pcbnew.FromMM(2))
                off_plane[key].add(x, y, None)
                continue
            h_m, a, (piece, d_edge, edge_xy) = hit
            # From the track EDGE, not from its centre
            dist = d_edge - half_w
            limit = s.edge_h_factor * h_m * 1e9
            if dist < limit:
                flagged.setdefault((t.GetNetname(), layer, a, piece.net), []).append(
                    (x, y, (t, max(dist, 0.0), limit, h_m, edge_xy, half_w)))

    for (net, layer, a, gnd), pts in flagged.items():
        # Drop the points close to where the same track leaves the plane
        off = off_plane.get((net, layer))
        if off is not None:
            pts = [q for q in pts if off.nearest(q[0], q[1], q[2][2]) is None]
            if not pts:
                continue
        for group in _cluster_points(pts, pcbnew.FromMM(0.8)):
            limit = group[0][2][2]
            # Length of the stretch: extent of the group of points
            xs = [g[0] for g in group]
            ys = [g[1] for g in group]
            length = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            if length < limit:
                continue
            wx, wy, (wt, wd, wl, wh, edge_xy, half_w) = min(group, key=lambda g: g[2][1])
            sev = SEV_ERROR if wd < wh * 1e9 else SEV_WARNING
            items = []
            for g in group:
                if g[2][0] not in items:
                    items.append(g[2][0])
            # The marker: a segment from the track edge to the plane edge, so
            # the measured distance is visible on the board
            x0, y0, ref_xy = int(wx), int(wy), None
            if edge_xy is not None:
                L = math.hypot(edge_xy[0] - wx, edge_xy[1] - wy)
                if L > 0:
                    x0 = int(wx + (edge_xy[0] - wx) * min(half_w / L, 1.0))
                    y0 = int(wy + (edge_xy[1] - wy) * min(half_w / L, 1.0))
                ref_xy = (int(edge_xy[0]), int(edge_xy[1]))
            detail = _("Traccia su {0}: il rame di {1} su {2} finisce a {3:.2f} mm dal bordo della traccia, "
                       "per circa {4:.0f} mm (limite {5:g} h, h = {6:.2f} mm)").format(
                board.GetLayerName(layer), gnd, board.GetLayerName(a), _mm(wd), _mm(length),
                s.edge_h_factor, wh * 1e3)
            issues.append(LayoutIssue(sev, CHECK_PLANE_EDGE, net, detail, _mm(wd),
                                      round(_mm(wl), 2), x0, y0, items, [], ref_xy))
    return issues


# ------------------------------------------------------- 6. track width

def _ipc_k(external):
    """Constant k of the IPC-2221 formula: 0.048 outer layers, 0.024 inner."""
    return 0.048 if external else 0.024


def ipc2221_rise(current_a, width_mm, copper_um, external):
    """
    Temperature rise (°C) of a track carrying the current, from IPC-2221
    I = k * DT^0.44 * A^0.725 solved for DT (A = cross-section in mil^2).
    """
    area = (width_mm / 0.0254) * (copper_um / 25.4)
    if area <= 0:
        return float("inf")
    return (current_a / (_ipc_k(external) * area ** 0.725)) ** (1 / 0.44)


def ipc2221_width_mm(current_a, copper_um, delta_t, external):
    """Track width (mm) needed by IPC-2221 for the current and rise given."""
    area = (current_a / (_ipc_k(external) * delta_t ** 0.44)) ** (1 / 0.725)  # mil^2
    return area / (copper_um / 25.4) * 0.0254


def check_track_width(board, s, cu_stack):
    """
    Track width against the current.

    The current of a net comes from the 'Currents' field (patterns allowed).
    Every track of the net is compared with the IPC-2221 width for the
    allowed temperature rise, with the copper thickness of its layer (from
    the stackup, 35 um if missing). The WHOLE current is assumed on every
    track of the net: a thin branch towards a small load can be reported
    even if it carries less; the DC Current tab gives the real distribution.

    One row per net, layer and width; error beyond twice the allowed rise.
    Returns (issues, notes).
    """
    issues, notes = [], []
    entries, bad = parse_net_values(s.currents)
    if bad:
        notes.append(_("Correnti non comprese: {0}").format("; ".join(bad)))
    if not entries:
        notes.append(_("Larghezza tracce: nessuna corrente indicata nel campo Correnti."))
        return issues, notes
    thickness, _src = copper_thickness_by_layer(board)
    outer = {cu_stack[0], cu_stack[-1]} if cu_stack else set()

    used = set()       # patterns that matched at least one net
    groups = {}        # (net, layer, width) -> [tracks]
    for t in _copper_tracks(board):
        net = t.GetNetname()
        if not net:
            continue
        current = None
        for pattern, value in entries:
            if _net_matches(net, pattern):
                current, _p = value, used.add(pattern)
                break
        if not current or current <= 0:
            continue
        groups.setdefault((net, t.GetLayer(), t.GetWidth()), []).append((t, current))

    for (net, layer, width), tracks in groups.items():
        current = tracks[0][1]
        copper_um = thickness.get(layer, 35e-6) * 1e6
        external = layer in outer
        w_mm = _mm(width)
        if ipc2221_limit_a(w_mm, copper_um, s.delta_t, external) >= current:
            continue  # wide enough
        rise = ipc2221_rise(current, w_mm, copper_um, external)
        need = ipc2221_width_mm(current, copper_um, s.delta_t, external)
        sev = SEV_ERROR if rise > 2 * s.delta_t else SEV_WARNING
        mx, my = _focus_point([t for t, _c in tracks])  # middle of the longest track
        rise_txt = ">200" if rise > 200 else f"{rise:.0f}"
        detail = _("{0}: larghezza {1:.2f} mm con {2:g} A, riscaldamento stimato {3} C (massimo {4:g} C); "
                   "servono {5:.2f} mm (IPC-2221, rame {6:.0f} um, {7} tratti)").format(
            board.GetLayerName(layer), w_mm, current, rise_txt, s.delta_t, need, copper_um, len(tracks))
        issues.append(LayoutIssue(sev, CHECK_WIDTH, net, detail, w_mm, round(need, 2),
                                  mx, my, [t for t, _c in tracks]))
    unused = [p for p, _v in entries if p not in used]
    if unused:
        notes.append(_("Correnti: nessuna traccia per {0}").format(", ".join(unused)))
    return issues, notes


# ------------------------------------------------------- 7. isolation

# IPC-2221 table 6-1, minimum spacing (mm) between conductors:
# (maximum voltage difference, B1 = inner layers, B2 = outer layers without
# coating, up to 3050 m altitude). Beyond 500 V: mm per volt.
_IPC_CLEARANCE = ((15, 0.05, 0.1), (30, 0.05, 0.1), (50, 0.1, 0.6), (100, 0.1, 0.6),
                  (150, 0.2, 0.6), (170, 0.2, 1.25), (250, 0.2, 1.25), (300, 0.2, 1.25),
                  (500, 0.25, 2.5))
_IPC_PER_VOLT = (0.0025, 0.005)


def ipc2221_clearance_mm(dv, external):
    """Minimum IPC-2221 distance (mm) for a voltage difference dv (V)."""
    dv = abs(dv)
    col = 2 if external else 1
    for row in _IPC_CLEARANCE:
        if dv <= row[0]:
            return row[col]
    return dv * _IPC_PER_VOLT[col - 1]


def net_voltage(name, entries, ref_filter):
    """
    Voltage of a net: the 'Voltages' field first, then 0 V for the grounds,
    then the voltage written in the name (+5V, 3V3, 24V_IN, -12V...).
    None if not known.
    """
    v = _value_for_net(name, entries)
    if v is not None:
        return v
    if _is_ref_net(name, ref_filter):
        return 0.0
    if name.upper().startswith("UNCONNECTED") or name.upper().startswith("NET-("):
        return None  # automatic names: no voltage written by the designer
    v = voltage_from_net(name.rsplit("/", 1)[-1])
    if v is None:
        return None
    # Negative supplies: "-12V", "/-15V", "VEE_-5V", "NEG12V"
    base = name.rsplit("/", 1)[-1].upper()
    if re.search(r"(^|[^A-Z0-9])-\s*\d", base) or "NEG" in base:
        v = -abs(v)
    return v


def _layer_items(board, layer):
    """
    Copper objects on a layer, by net: {net: [(item, shape, bbox)]}. Tracks,
    arcs, vias, pads and filled zones; the shape is the effective copper
    shape on that layer.
    """
    out = {}

    def add(item):
        net = item.GetNetname()
        if not net:
            return
        try:
            shape = item.GetEffectiveShape(layer)
        except Exception:
            return
        out.setdefault(net, []).append((item, shape, item.GetBoundingBox()))

    for t in board.GetTracks():
        if t.IsOnLayer(layer):
            add(t)
    for p in board.GetPads():
        if p.IsOnLayer(layer):
            add(p)
    for z in board.Zones():
        if z.IsOnLayer(layer) and z.IsFilled():
            add(z)
    return out


def _boxes_near(ba, bb, margin):
    """True if two bounding boxes are closer than 'margin' (nm)."""
    return not (ba.GetRight() + margin < bb.GetLeft() or bb.GetRight() + margin < ba.GetLeft()
                or ba.GetBottom() + margin < bb.GetTop() or bb.GetBottom() + margin < ba.GetTop())


def _item_probe_points(item):
    """Points of an object used to place the marker of an isolation issue."""
    if item.Type() in (pcbnew.PCB_TRACE_T, getattr(pcbnew, "PCB_ARC_T", -1)):
        return _track_points(item, pcbnew.FromMM(0.2), 200)
    if item.Type() == getattr(pcbnew, "PCB_ZONE_T", -1):
        return []  # a zone has no meaningful single point: the other object is used
    p = item.GetPosition()
    return [(p.x, p.y)]


def _closest_point(ia, sa, ib, sb, max_nm):
    """
    Point of one of the two objects closest to the other one (for the
    marker): the probe points of each object are measured against the shape
    of the other. Falls back to the middle of the two bounding boxes.
    """
    best = None
    for pts, other in ((_item_probe_points(ia), sb), (_item_probe_points(ib), sa)):
        for x, y in pts[:: max(1, len(pts) // 60)]:
            p = pcbnew.VECTOR2I(int(x), int(y))
            g = _bisect_gap(lambda c, p=p, o=other: o.Collide(p, int(c)), max_nm * 4)
            if g is not None and (best is None or g < best[0]):
                best = (g, x, y)
    if best:
        return int(best[1]), int(best[2])
    ba, bb = ia.GetBoundingBox(), ib.GetBoundingBox()
    return ((ba.GetCenter().x + bb.GetCenter().x) // 2, (ba.GetCenter().y + bb.GetCenter().y) // 2)


def check_isolation(board, s, cu_stack, progress=None, cancel=None):
    """
    Isolation distance between nets at different voltages.

    Voltages: the 'Voltages' field, 0 V for the grounds, otherwise the
    voltage in the net name. For every pair of nets with a known voltage
    and a difference above 30 V, on every copper layer the smallest copper
    distance between them (edge to edge) is compared with IPC-2221 table
    6-1: B2 on the outer layers (no coating), B1 on the inner ones. Nets
    with an unknown voltage are not checked; the ones close to a net above
    30 V are listed in a note, so their voltage can be typed in.

    The IPC-2221 distances are a design minimum for the PCB itself; safety
    standards for mains equipment (IEC 62368-1, IEC 60664) ask for larger
    creepage and clearance distances.
    Returns (issues, notes).
    """
    issues, notes = [], []
    entries, bad = parse_net_values(s.voltages)
    if bad:
        notes.append(_("Tensioni non comprese: {0}").format("; ".join(bad)))
    names = [str(n) for n in board.GetNetsByName().keys() if str(n)]
    volts = {n: net_voltage(n, entries, s.ref_filter) for n in names}
    known = {n: v for n, v in volts.items() if v is not None}
    # Pairs to check: voltage difference above the threshold
    pairs = [(a, b) for i, a in enumerate(sorted(known)) for b in sorted(known)[i + 1:]
             if abs(known[a] - known[b]) > ISOLATION_MIN_DV]
    hv = {n for n, v in known.items() if abs(v) > ISOLATION_MIN_DV}
    if not pairs and not hv:
        notes.append(_("Isolamento: nessuna net oltre {0:g} V (tensioni dai nomi delle net o dal campo "
                       "Tensioni).").format(ISOLATION_MIN_DV))
        return issues, notes
    outer = {cu_stack[0], cu_stack[-1]} if cu_stack else set()
    unknown_near = set()   # nets with unknown voltage close to a net above 30 V

    for li, layer in enumerate(cu_stack):
        if progress:
            progress(li, len(cu_stack))
        if cancel and cancel():
            break
        items = _layer_items(board, layer)
        external = layer in outer
        cls = "B2" if external else "B1"
        for a, b in pairs:
            if a not in items or b not in items:
                continue
            dv = abs(known[a] - known[b])
            need = pcbnew.FromMM(ipc2221_clearance_mm(dv, external))
            best = None
            for ia, sa, ba in items[a]:
                for ib, sb, bb in items[b]:
                    if not _boxes_near(ba, bb, need):
                        continue
                    if not sa.Collide(sb, int(need)):
                        continue
                    g = _bisect_gap(lambda c, sa=sa, sb=sb: sa.Collide(sb, int(c)), need)
                    if g is not None and (best is None or g < best[0]):
                        best = (g, ia, sa, ib, sb)
            if best is None or best[0] >= need:
                continue
            g, ia, sa, ib, sb = best
            x, y = _closest_point(ia, sa, ib, sb, need)
            detail = _("{0} ({1:g} V) e {2} ({3:g} V) su {4}: distanza {5:.2f} mm, IPC-2221 {6} chiede "
                       "{7:g} mm per {8:g} V").format(a, known[a], b, known[b], board.GetLayerName(layer),
                                                       _mm(g), cls, _mm(need), dv)
            issues.append(LayoutIssue(SEV_ERROR, CHECK_ISOLATION, f"{a} / {b}", detail, _mm(g),
                                      _mm(need), x, y, [ia, ib]))
        # Unknown nets close to a high-voltage net (as if they were at 0 V)
        for a in hv:
            if a not in items:
                continue
            need = pcbnew.FromMM(ipc2221_clearance_mm(known[a], external))
            for n, lst in items.items():
                if n in known or n in unknown_near:
                    continue
                if any(_boxes_near(ba, bb, need) and sa.Collide(sb, int(need))
                       for ia, sa, ba in items[a] for ib, sb, bb in lst):
                    unknown_near.add(n)
    if unknown_near:
        shown = sorted(unknown_near)
        more = f" (+{len(shown) - 6})" if len(shown) > 6 else ""
        notes.append(_("Isolamento: tensione non nota per {0}{1}, vicine a net oltre {2:g} V: indicala nel "
                       "campo Tensioni per controllarle.").format(", ".join(shown[:6]), more, ISOLATION_MIN_DV))
    return issues, notes


# ------------------------------------------------------- 8. lengths

def _layer_z(board, cu_stack, stackup):
    """Height (m) of every copper layer from the top, from the stackup."""
    z, heights = 0.0, {}
    for layer in cu_stack:
        heights[layer] = z
        info = stackup.get(layer) or {}
        below = info.get("below")
        z += (info.get("t") or 35e-6) + (below[0] if below else 0.2e-3)
    return heights


def net_lengths(board, cu_stack, stackup):
    """
    Routed length (mm) of every net: sum of its tracks and arcs, plus the
    height crossed in every via (between the outermost layers where the
    signal arrives at the via). Branches are included: on a net with a
    stub, the length is the total copper length, as in KiCad's Net Inspector.
    Returns ({net: length mm}, {net: [tracks]}).
    """
    lengths, tracks_by_net, pads_by_net = {}, {}, {}
    for t in _copper_tracks(board):
        n = t.GetNetname()
        lengths[n] = lengths.get(n, 0.0) + _mm(t.GetLength())
        tracks_by_net.setdefault(n, []).append(t)
    for pad in board.GetPads():
        pads_by_net.setdefault(pad.GetNetname(), []).append(pad)
    z = _layer_z(board, cu_stack, stackup)
    for v in board.GetTracks():
        if v.Type() != pcbnew.PCB_VIA_T:
            continue
        n = v.GetNetname()
        if n not in lengths:
            continue
        used = _via_signal_layers(board, v, tracks_by_net, pads_by_net, cu_stack)
        if len(used) >= 2:
            hs = [z[l] for l in used if l in z]
            lengths[n] += (max(hs) - min(hs)) * 1e3
    return lengths, tracks_by_net


def _focus_point(tracks):
    """Middle of the longest track of a list (where the marker goes)."""
    t = max(tracks, key=lambda t: t.GetLength())
    a, b = t.GetStart(), t.GetEnd()
    return (a.x + b.x) // 2, (a.y + b.y) // 2


def check_lengths(board, s, cu_stack, stackup):
    """
    Lengths.

    - Differential pairs (recognized from the names: _P/_N, DP/DM, +/-):
      the length difference must be within the maximum skew (error beyond
      twice as much).
    - Groups of nets from the 'Groups' field: every net of a group is
      compared with the longest one of the group; difference within the
      group tolerance (error beyond twice as much).
    Returns (issues, notes).
    """
    from .impedance import detect_pairs

    issues, notes = [], []
    lengths, tracks_by_net = net_lengths(board, cu_stack, stackup)
    routed = sorted(n for n in lengths if n)

    # --- Differential pairs ---
    for name, pos, neg in detect_pairs(routed):
        lp, ln = lengths[pos], lengths[neg]
        skew = abs(lp - ln)
        if skew <= s.skew_mm:
            continue
        sev = SEV_ERROR if skew > 2 * s.skew_mm else SEV_WARNING
        short = neg if ln < lp else pos
        x, y = _focus_point(tracks_by_net[short])
        detail = _("Coppia differenziale: {0} {1:.2f} mm, {2} {3:.2f} mm, differenza {4:.2f} mm "
                   "(allunga {5})").format(pos, lp, neg, ln, skew, short)
        issues.append(LayoutIssue(sev, CHECK_LENGTH, name, detail, skew, s.skew_mm, x, y,
                                  tracks_by_net[pos] + tracks_by_net[neg]))

    # --- Groups typed by the user ---
    for gi, raw in enumerate(g for g in re.split(r"[;\n]", s.groups or "") if g.strip()):
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        members = [n for n in routed if any(_net_matches(n, p) for p in patterns)]
        label = raw.strip()
        if len(members) < 2:
            notes.append(_("Gruppo \"{0}\": meno di due net con tracce.").format(label))
            continue
        longest = max(members, key=lambda n: lengths[n])
        for n in members:
            diff = lengths[longest] - lengths[n]
            if diff <= s.group_tol_mm:
                continue
            sev = SEV_ERROR if diff > 2 * s.group_tol_mm else SEV_WARNING
            x, y = _focus_point(tracks_by_net[n])
            detail = _("Gruppo \"{0}\": {1} {2:.2f} mm, {3:.2f} mm piu' corta di {4} ({5:.2f} mm)").format(
                label, n, lengths[n], diff, longest, lengths[longest])
            issues.append(LayoutIssue(sev, CHECK_LENGTH, n, detail, diff, s.group_tol_mm, x, y,
                                      list(tracks_by_net[n])))
    return issues, notes


# ------------------------------------------------------- shared helpers 9-16

def _is_arc(t):
    """True for an arc track."""
    return t.Type() == getattr(pcbnew, "PCB_ARC_T", -1)


def _end_direction(t, at_start):
    """
    Unit vector leaving the track from one of its ends (the start if
    at_start, else the end), pointing INTO the track. For an arc it is the
    tangent at that end (taken from a point a little along the arc).
    """
    a = t.GetStart() if at_start else t.GetEnd()
    if _is_arc(t):
        pts = _track_points(t, pcbnew.FromMM(0.05), 4000)
        q = pts[1] if at_start else pts[-2]
    else:
        b = t.GetEnd() if at_start else t.GetStart()
        q = (b.x, b.y)
    dx, dy = q[0] - a.x, q[1] - a.y
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def _angle_deg(u, v):
    """Angle (0-180 degrees) between two unit vectors."""
    c = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    return math.degrees(math.acos(c))


class _NetCopper:
    """
    Copper of the board grouped by net, to answer "what touches this point":
    track ends, track bodies, pads, vias and zone fills of the same net on a
    layer. Used by the stub and acute-angle checks.
    """

    def __init__(self, board):
        self.tracks = {}   # net -> [tracks and arcs]
        self.vias = {}     # net -> [vias]
        self.pads = {}     # net -> [pads]
        self.zones = {}    # net -> [filled zones]
        for t in _copper_tracks(board):
            self.tracks.setdefault(t.GetNetname(), []).append(t)
        for t in board.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                self.vias.setdefault(t.GetNetname(), []).append(t)
        for p in board.GetPads():
            self.pads.setdefault(p.GetNetname(), []).append(p)
        for z in board.Zones():
            if z.IsFilled():
                self.zones.setdefault(z.GetNetname(), []).append(z)

    def ends_at(self, net, layer, x, y, tol, skip=None):
        """Tracks of the net on the layer with an END within tol of (x, y)."""
        out = []
        for t in self.tracks.get(net, ()):
            if t is skip or t.GetLayer() != layer:
                continue
            for at_start, e in ((True, t.GetStart()), (False, t.GetEnd())):
                if _dist(e.x, e.y, x, y) <= tol:
                    out.append((t, at_start))
        return out

    def body_at(self, net, layer, x, y, skip=None):
        """A track of the net whose BODY (not an end) passes on (x, y)."""
        for t in self.tracks.get(net, ()):
            if t is skip or t.GetLayer() != layer:
                continue
            a, b = t.GetStart(), t.GetEnd()
            if min(_dist(a.x, a.y, x, y), _dist(b.x, b.y, x, y)) <= t.GetWidth():
                continue  # that is (next to) an end, not the body
            try:
                if t.HitTest(pcbnew.VECTOR2I(int(x), int(y)), 0):
                    return t
            except Exception:
                if geometry.point_segment_distance(x, y, a.x, a.y, b.x, b.y) <= t.GetWidth() / 2.0:
                    return t
        return None

    def touching(self, net, layer, x, y, skip=(), reach=0):
        """
        Tracks of the net on the layer whose COPPER contains (x, y), ends
        included: two tracks are connected when their copper touches, as for
        KiCad, even if their ends do not coincide exactly (a few hundredths
        of mm apart, or one segment lying over the other).
        """
        out = []
        p = pcbnew.VECTOR2I(int(x), int(y))
        for t in self.tracks.get(net, ()):
            if t in skip or t.GetLayer() != layer:
                continue
            try:
                hit = t.HitTest(p, int(reach))
            except Exception:
                a, b = t.GetStart(), t.GetEnd()
                hit = geometry.point_segment_distance(x, y, a.x, a.y, b.x, b.y) <= t.GetWidth() / 2.0 + reach
            if hit:
                out.append(t)
        return out

    def other_copper(self, net, layer, x, y, reach=0):
        """
        True if a pad, a via or a zone fill of the net is within 'reach' of
        (x, y) on the layer. With reach = half the width of a track, it
        tells whether the round end of that track touches them.
        """
        p = pcbnew.VECTOR2I(int(x), int(y))
        r = int(reach)
        for pad in self.pads.get(net, ()):
            if not pad.IsOnLayer(layer):
                continue
            bb = pad.GetBoundingBox()
            if not (bb.GetLeft() - r <= x <= bb.GetRight() + r and bb.GetTop() - r <= y <= bb.GetBottom() + r):
                continue
            try:
                if _pad_shape(pad, layer).Collide(p, r):
                    return True
            except Exception:
                return True
        for v in self.vias.get(net, ()):
            if v.IsOnLayer(layer):
                c = v.GetPosition()
                if _dist(c.x, c.y, x, y) <= _via_radius(v) + r:
                    return True
        for z in self.zones.get(net, ()):
            if z.IsOnLayer(layer) and z.HitTestFilledArea(layer, p, r):
                return True
        return False

    def inside_pad(self, net, layer, x, y):
        """True if (x, y) is inside a pad of the net on the layer."""
        p = pcbnew.VECTOR2I(int(x), int(y))
        for pad in self.pads.get(net, ()):
            if pad.IsOnLayer(layer) and pad.GetBoundingBox().Contains(p):
                return True
        return False


def _signal_net(net, s):
    """True for a net checked by the signal checks (not ground, not unconnected)."""
    if not net or _is_ref_net(net, s.ref_filter) or net.upper().startswith("UNCONNECTED"):
        return False
    return not (s.skip_power_nets and is_power_net(net, s.ref_filter))


# ------------------------------------------------------- 9. stubs

def check_stubs(board, s, copper):
    """
    Dead copper: track ends that touch nothing (no other track, pad, via or
    zone of the same net). The dead branch is followed back from the open
    end along the tracks, as long as there is no junction, and its length is
    the measure. Dead copper is an antenna and, on a fast line, a stub that
    reflects. Warning from stub_mm, error beyond 5 times.
    """
    issues = []
    # id() of the tracks already part of a reported dead branch: in KiCad 10
    # the pcbnew objects cannot go in a set (they are not hashable); the
    # objects come from copper.tracks, so their id() stays the same here
    reported = set()
    for net, tracks in copper.tracks.items():
        if not net:
            continue
        for t in tracks:
            for at_start in (True, False):
                if id(t) in reported:
                    break
                e = t.GetStart() if at_start else t.GetEnd()
                layer = t.GetLayer()
                # Connected if the copper of another track, a pad, a via or a
                # zone of the same net touches this end
                half = t.GetWidth() / 2.0
                if copper.touching(net, layer, e.x, e.y, skip=(t,), reach=half):
                    continue
                if copper.other_copper(net, layer, e.x, e.y, reach=half):
                    continue
                # Open end: walk back along the chain of tracks, as long as
                # exactly one other track continues it and nothing else is
                # there (pad, via, zone)
                length, chain = 0.0, []
                cur, cur_start = t, at_start
                for _guard in range(500):
                    chain.append(cur)
                    length += _mm(cur.GetLength())
                    far = cur.GetEnd() if cur_start else cur.GetStart()
                    half = cur.GetWidth() / 2.0
                    nxt = copper.touching(net, layer, far.x, far.y, skip=chain, reach=half)
                    if len(nxt) != 1 or copper.other_copper(net, layer, far.x, far.y, reach=half):
                        break  # junction, pad, via or zone: the dead branch ends here
                    o = nxt[0]
                    # Continue from the end of the next track nearer to the joint
                    ds = _dist(o.GetStart().x, o.GetStart().y, far.x, far.y)
                    de = _dist(o.GetEnd().x, o.GetEnd().y, far.x, far.y)
                    if min(ds, de) > o.GetWidth():
                        break  # it touches the side of a longer track: a junction
                    cur, cur_start = o, ds <= de
                if length < s.stub_mm:
                    continue
                reported.update(id(c) for c in chain)
                sev = SEV_ERROR if length > 5 * s.stub_mm else SEV_WARNING
                detail = _("Traccia su {0} che finisce senza collegarsi a niente: ramo morto di {1:.1f} mm "
                           "(antenna, e uno stub sulle linee veloci)").format(board.GetLayerName(layer), length)
                issues.append(LayoutIssue(sev, CHECK_STUB, net, detail, length, s.stub_mm, e.x, e.y, chain))
    return issues


# ------------------------------------------------------- 10. acute angles

def check_acute_angles(board, s, copper):
    """
    Acute angles (acid traps): two tracks of the same net on the same layer
    meeting at a point with an angle smaller than acute_deg between them
    (also a track ending on the side of another one, T junction). In the
    narrow corner the etching liquid stays longer and can eat the copper.
    Corners inside a pad are not reported (the pad fills them).
    """
    issues = []
    grid = pcbnew.FromMM(0.1)
    seen = set()   # corner points already reported, per (net, layer), on a 0.1 mm grid
    for net, tracks in copper.tracks.items():
        if not net:
            continue
        for t in tracks:
            # A micro segment (shorter than its width, often a few um left by
            # editing) is part of the joint: its direction means nothing
            if t.GetLength() < t.GetWidth():
                continue
            for at_start in (True, False):
                e = t.GetStart() if at_start else t.GetEnd()
                layer = t.GetLayer()
                key = (net, layer, int(e.x // grid), int(e.y // grid))
                # Ends closer than the width of the track are the same joint
                # (after editing two ends often stay a few tenths apart, with
                # the copper overlapping)
                tol = max(t.GetWidth(), pcbnew.FromMM(0.005))
                if key in seen or copper.inside_pad(net, layer, e.x, e.y):
                    continue
                u = _end_direction(t, at_start)
                worst = None
                # Other tracks ending at the same point
                for o, o_start in copper.ends_at(net, layer, e.x, e.y, tol, skip=t):
                    if o.GetLength() < o.GetWidth():
                        continue  # micro segment: no direction
                    ang = _angle_deg(u, _end_direction(o, o_start))
                    if ang < 2.0:
                        continue  # two segments lying one over the other: not a corner
                    if worst is None or ang < worst[0]:
                        worst = (ang, o)
                # T junction: this track ends on the body of another one; the
                # angle on the narrower side of the crossing
                body = copper.body_at(net, layer, e.x, e.y, skip=t)
                if body is not None and not _is_arc(body):
                    a, b = body.GetStart(), body.GetEnd()
                    L = math.hypot(b.x - a.x, b.y - a.y) or 1.0
                    v = ((b.x - a.x) / L, (b.y - a.y) / L)
                    # Where the joint falls along the body: the body goes on
                    # for 'to_b' towards b and 'to_a' towards a
                    pos = (e.x - a.x) * v[0] + (e.y - a.y) * v[1]
                    to_a, to_b = pos, L - pos
                    ang = _angle_deg(u, v)       # angle on the b side
                    # The narrow corner is on the side of the smaller angle;
                    # it exists only if the body goes on beyond the joint for
                    # more than its width there (otherwise the corner is
                    # filled by the copper of the two tracks)
                    side_len = to_b if ang < 90.0 else to_a
                    ang = min(ang, 180.0 - ang)
                    if side_len > body.GetWidth() and ang >= 2.0 and (worst is None or ang < worst[0]):
                        worst = (ang, body)
                if worst is None or worst[0] >= s.acute_deg - 0.01:
                    continue
                seen.add(key)
                detail = _("Due tratti su {0} si incontrano a {1:.0f} gradi: angolo acuto (acid trap), "
                           "meglio 90 gradi o piu' (due tratti a 45 gradi)").format(board.GetLayerName(layer), worst[0])
                issues.append(LayoutIssue(SEV_WARNING, CHECK_ACUTE, net, detail, worst[0], s.acute_deg,
                                          e.x, e.y, [t, worst[1]], unit="°"))
    return issues


# ------------------------------------------------------- 11. width steps

def check_width_steps(board, s, copper):
    """
    Width changes along a signal net, on the same layer: every width is an
    impedance, so a step is a small reflection. The short neck-downs at the
    pads (a segment up to 1 mm that ends on a pad) are not counted. The
    measure is the difference between the widest and the narrowest track,
    in % of the narrowest; warning from width_step_pct, error beyond twice.
    """
    issues = []
    neck = pcbnew.FromMM(1.0)
    for net, tracks in copper.tracks.items():
        if not _signal_net(net, s):
            continue
        by_layer = {}
        for t in tracks:
            if t.GetLength() <= neck:
                ends = (t.GetStart(), t.GetEnd())
                if any(copper.inside_pad(net, t.GetLayer(), e.x, e.y) for e in ends):
                    continue  # neck-down at a pad
            by_layer.setdefault(t.GetLayer(), {}).setdefault(t.GetWidth(), []).append(t)
        for layer, widths in by_layer.items():
            if len(widths) < 2:
                continue
            w_min, w_max = min(widths), max(widths)
            step = (w_max - w_min) / float(w_min) * 100.0
            if step <= s.width_step_pct:
                continue
            sev = SEV_ERROR if step > 2 * s.width_step_pct else SEV_WARNING
            parts = ", ".join("{0:.2f} mm ({1:.0f} mm)".format(_mm(w), sum(_mm(t.GetLength()) for t in ts))
                              for w, ts in sorted(widths.items()))
            detail = _("Larghezze diverse su {0}: {1} (larghezza e lunghezza): ogni cambio e' un salto "
                       "di impedenza").format(board.GetLayerName(layer), parts)
            narrow = widths[w_min]
            x, y = _focus_point(narrow)
            issues.append(LayoutIssue(sev, CHECK_WIDTH_STEP, net, detail, step, s.width_step_pct,
                                      x, y, list(narrow), unit="%"))
    return issues


# ------------------------------------------------------- 12. vias in SMD pads

# SMD pads larger than this on both sides are thermal / exposed pads, where
# vias are put on purpose
VIA_IN_PAD_MAX_MM = 1.5


def check_vias_in_pads(board, s):
    """
    Vias whose drill falls inside an SMD pad: during reflow the solder flows
    into the hole and the joint is left without it, unless the via is filled
    and capped (via-in-pad, a special process). Large pads (exposed pads of
    QFN, power pads) are skipped: vias there are thermal vias on purpose.
    """
    issues = []
    limit = pcbnew.FromMM(VIA_IN_PAD_MAX_MM)
    idx = _PointIndex(pcbnew.FromMM(3))
    for pad in board.GetPads():
        try:
            if pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
        except Exception:
            continue
        bb = pad.GetBoundingBox()
        if min(bb.GetWidth(), bb.GetHeight()) > limit:
            continue  # thermal / exposed pad
        p = pad.GetPosition()
        idx.add(p.x, p.y, pad)
    for v in board.GetTracks():
        if v.Type() != pcbnew.PCB_VIA_T:
            continue
        c = v.GetPosition()
        r_drill = v.GetDrillValue() / 2.0 if hasattr(v, "GetDrillValue") else _via_radius(v) / 2.0
        for _d, pad in idx.within(c.x, c.y, pcbnew.FromMM(3)):
            layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            if not v.IsOnLayer(layer):
                continue
            try:
                hit = _pad_shape(pad, layer).Collide(pcbnew.VECTOR2I(c.x, c.y), int(r_drill))
            except Exception:
                hit = pad.GetBoundingBox().Contains(c)
            if not hit:
                continue
            detail = _("Foro della via ({0:.2f} mm) dentro il pad {1} (SMD): in saldatura lo stagno scende nel "
                       "foro; spostala fuori dal pad o chiedi via-in-pad riempite e chiuse").format(
                _mm(2 * r_drill), _pad_label(pad))
            issues.append(LayoutIssue(SEV_WARNING, CHECK_VIA_IN_PAD, f"{_pad_label(pad)} ({v.GetNetname()})",
                                      detail, None, None, c.x, c.y, [v, pad], unit=""))
            break
    return issues


# ------------------------------------------------------- 13. tombstoning

# Two-pad parts whose pads are all smaller than this (mm) are checked: from
# 0201 to 0805 and the small diodes (SOD-323/523)
TOMBSTONE_MAX_PAD_MM = 1.6


# Reference prefixes of the parts checked for tombstoning: two-pad passives
TOMBSTONE_PREFIXES = ("R", "C", "L", "D", "FB", "F")


def _local_connection(obj):
    """
    Zone connection set on a pad or a footprint (ZONE_CONNECTION_...), or
    INHERITED. KiCad 8-10 call it GetLocalZoneConnection, KiCad 7
    GetZoneConnection.
    """
    for name in ("GetLocalZoneConnection", "GetZoneConnection"):
        fn = getattr(obj, name, None)
        if fn is not None:
            try:
                return fn()
            except Exception:
                continue
    return pcbnew.ZONE_CONNECTION_INHERITED


def _zone_touches_pad(zone, pad, layer):
    """True if the fill of the zone reaches the ring just around the pad."""
    bb = pad.GetBoundingBox()
    off = pcbnew.FromMM(0.15)
    x0, y0 = bb.GetLeft() - off, bb.GetTop() - off
    x1, y1 = bb.GetRight() + off, bb.GetBottom() + off
    pts = [(x0, y0), (x1, y0), (x0, y1), (x1, y1),
           ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
    return any(zone.HitTestFilledArea(layer, pcbnew.VECTOR2I(int(x), int(y))) for x, y in pts)


def _pad_flooded(pad, zones_by_net, layer):
    """
    True if the pad sits in a zone of its own net with a SOLID connection
    (not a thermal relief). The connection is the one set on the pad, else
    on its footprint, else on the zone (KiCad's order). Reading the copper
    around the pad is not enough: on small pads the thermal spokes are
    almost as wide as the pad.
    """
    conn = _local_connection(pad)
    if conn == pcbnew.ZONE_CONNECTION_INHERITED:
        try:
            parent = pad.GetParentFootprint() or pad.GetParent()
            conn = _local_connection(parent)
        except Exception:
            conn = pcbnew.ZONE_CONNECTION_INHERITED
    for z in zones_by_net.get(pad.GetNetname(), ()):
        # A teardrop (the copper drop where a track enters the pad) is a small
        # zone with a solid connection: it is not a pour that floods the pad
        if geometry.is_teardrop(z):
            continue
        if not z.IsOnLayer(layer) or not _zone_touches_pad(z, pad, layer):
            continue
        c = conn if conn != pcbnew.ZONE_CONNECTION_INHERITED else z.GetPadConnection()
        if c == pcbnew.ZONE_CONNECTION_FULL:
            return True
    return False


def check_tombstoning(board, s, copper):
    """
    Tombstoning risk: a small two-pad passive (resistor, capacitor,
    inductor, diode, ferrite, fuse, up to 0805) with one pad flooded in a
    zone with a SOLID connection and the other pad not (tracks only, or a
    thermal relief). In reflow the flooded pad heats up later, the other
    side melts first and pulls the part up. A thermal relief on the flooded
    pad fixes it.
    """
    issues = []
    max_pad = pcbnew.FromMM(TOMBSTONE_MAX_PAD_MM)
    for fp in board.GetFootprints():
        if _ref_prefix(fp.GetReference()) not in TOMBSTONE_PREFIXES:
            continue
        pads = list(fp.Pads())
        if len(pads) != 2:
            continue
        try:
            if any(p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD for p in pads):
                continue
        except Exception:
            continue
        if any(max(p.GetBoundingBox().GetWidth(), p.GetBoundingBox().GetHeight()) > max_pad for p in pads):
            continue
        layer = pcbnew.F_Cu if pads[0].IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        flooded = [_pad_flooded(p, copper.zones, layer) for p in pads]
        if flooded[0] == flooded[1]:
            continue  # both solid, or neither: they heat up alike
        full, other = (pads[0], pads[1]) if flooded[0] else (pads[1], pads[0])
        detail = _("{0}: il pad {1} e' annegato nella zona {2} (collegamento pieno), il pad {3} no: in "
                   "saldatura si scaldano in modo diverso (tombstoning). Usa lo scarico termico sul pad {1}").format(
            fp.GetReference(), full.GetNumber(), full.GetNetname(), other.GetNumber())
        p = full.GetPosition()
        issues.append(LayoutIssue(SEV_WARNING, CHECK_TOMBSTONE, fp.GetReference(), detail, None, None,
                                  p.x, p.y, [fp], unit=""))
    return issues


# ------------------------------------------------------- 14. current in the vias

def via_limit_a(drill_mm, plating_um, delta_t):
    """
    Maximum current (A) of one via, as in the DC Current tab: the barrel is a
    copper tube (cross-section pi x plating x (drill + plating)), treated with
    IPC-2221 as an outer conductor.
    """
    t_mm = plating_um * 1e-3
    area_mm2 = math.pi * t_mm * (drill_mm + t_mm)
    return ipc2221_limit_a(area_mm2 / t_mm, plating_um, delta_t, True)


def check_via_current(board, s):
    """
    Current in the vias, for the nets of the 'Currents' field. The vias of a
    net that are close to each other (within 3 mm, chained) are one layer
    change: the whole current of the net is assumed to cross it, shared
    among its vias. The measure is the number of vias, the limit the number
    IPC-2221 needs for the allowed temperature rise; error when each via
    would heat more than twice the allowed rise.
    Returns (issues, notes).
    """
    issues, notes = [], []
    entries, _bad = parse_net_values(s.currents)
    if not entries:
        return issues, notes
    by_net = {}
    for v in board.GetTracks():
        if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname():
            cur = _value_for_net(v.GetNetname(), entries)
            if cur and cur > 0:
                by_net.setdefault(v.GetNetname(), []).append(v)
    for net, vias in by_net.items():
        current = _value_for_net(net, entries)
        pts = [(v.GetPosition().x, v.GetPosition().y, v) for v in vias]
        for group in _cluster_points(pts, pcbnew.FromMM(3)):
            vs = [g[2] for g in group]
            drill = min(_mm(v.GetDrillValue()) for v in vs)
            one = via_limit_a(drill, s.via_plating_um, s.delta_t)
            need = max(1, math.ceil(current / one - 1e-9))
            if len(vs) >= need:
                continue
            per_via = current / len(vs)
            t_mm = s.via_plating_um * 1e-3
            eq_w = math.pi * t_mm * (drill + t_mm) / t_mm
            rise = ipc2221_rise(per_via, eq_w, s.via_plating_um, True)
            sev = SEV_ERROR if rise > 2 * s.delta_t else SEV_WARNING
            rise_txt = ">200" if rise > 200 else f"{rise:.0f}"
            detail = _("{0} via da {1:.2f} mm portano {2:g} A: {3:.2f} A ciascuna, riscaldamento stimato {4} C; "
                       "ne servono {5} per {6:g} C (IPC-2221, placcatura {7:g} um)").format(
                len(vs), drill, current, per_via, rise_txt, need, s.delta_t, s.via_plating_um)
            x = int(sum(g[0] for g in group) / len(group))
            y = int(sum(g[1] for g in group) / len(group))
            issues.append(LayoutIssue(sev, CHECK_VIA_CURRENT, net, detail, len(vs), need, x, y, vs, unit="via"))
    return issues, notes


# ------------------------------------------------------- 15. crystal

def _is_crystal(fp):
    """True for a crystal: reference Y..., or 'Crystal' in the footprint name."""
    if _ref_prefix(fp.GetReference()) == "Y":
        return True
    try:
        return "CRYSTAL" in str(fp.GetFPID().GetLibItemName()).upper()
    except Exception:
        return False


def check_crystal(board, s, cu_stack):
    """
    Crystals.
    - Tracks of other nets (not the crystal's own nets, not ground) passing
      under the crystal, on any layer: they couple noise into a very
      sensitive, high-impedance circuit (error).
    - The routed length of every crystal net (crystal - IC, load capacitors
      included) must be within crystal_mm: long tracks pick up noise and add
      capacitance (warning, error beyond twice).
    Returns (issues, notes).
    """
    issues, notes = [], []
    crystals = [fp for fp in board.GetFootprints() if _is_crystal(fp)]
    if not crystals:
        return issues, notes
    lengths, tracks_by_net = None, None
    margin = pcbnew.FromMM(0.5)
    for fp in crystals:
        pads = list(fp.Pads())
        if not pads:
            continue
        nets = {p.GetNetname() for p in pads if p.GetNetname()}
        sig = {n for n in nets if not _is_ref_net(n, s.ref_filter)}
        # Area of the crystal: its pads, enlarged by a margin
        bb = pads[0].GetBoundingBox()
        for p in pads[1:]:
            bb.Merge(p.GetBoundingBox())
        x0, y0 = bb.GetLeft() - margin, bb.GetTop() - margin
        x1, y1 = bb.GetRight() + margin, bb.GetBottom() + margin
        rect = pcbnew.BOX2I(pcbnew.VECTOR2I(int(x0), int(y0)), pcbnew.VECTOR2I(int(x1 - x0), int(y1 - y0)))
        under = {}
        for t in _copper_tracks(board):
            n = t.GetNetname()
            if not n or n in nets or _is_ref_net(n, s.ref_filter):
                continue
            try:
                hit = t.HitTest(rect, False, 0)  # touches the area (not only fully inside)
            except Exception:
                hit = rect.Intersects(t.GetBoundingBox())
            if hit:
                under.setdefault(n, []).append(t)
        for n, ts in under.items():
            layers = ", ".join(sorted({board.GetLayerName(t.GetLayer()) for t in ts}))
            detail = _("La traccia di {0} passa sotto il quarzo {1} ({2}): porta disturbi nell'oscillatore, "
                       "spostala").format(n, fp.GetReference(), layers)
            # Marker in the middle of the crystal (centre of its pads)
            cx, cy = int((x0 + x1) / 2), int((y0 + y1) / 2)
            issues.append(LayoutIssue(SEV_ERROR, CHECK_CRYSTAL, f"{fp.GetReference()} / {n}", detail,
                                      None, None, cx, cy, [fp] + ts, unit=""))
        # Length of the crystal nets
        if lengths is None:
            from .impedance import read_stackup

            try:
                stackup, _note = read_stackup(board)
            except Exception:
                stackup = {}
            lengths, tracks_by_net = net_lengths(board, cu_stack, stackup)
        for n in sorted(sig):
            L = lengths.get(n, 0.0)
            if L <= s.crystal_mm:
                continue
            sev = SEV_ERROR if L > 2 * s.crystal_mm else SEV_WARNING
            detail = _("{0}: {1:.1f} mm di tracce fra il quarzo {2} e l'integrato (condensatori di carico "
                       "compresi): avvicina il quarzo al chip").format(n, L, fp.GetReference())
            x, y = (_focus_point(tracks_by_net[n]) if tracks_by_net.get(n)
                    else (int((x0 + x1) / 2), int((y0 + y1) / 2)))
            issues.append(LayoutIssue(sev, CHECK_CRYSTAL, n, detail, L, s.crystal_mm, x, y,
                                      list(tracks_by_net.get(n, [])), unit="mm"))
    return issues, notes


# ------------------------------------------------------- 16. broadside coupling

def _overlap(a, b):
    """
    Overlap of two straight tracks seen from above, when they run parallel
    (within 15 degrees) and their copper overlaps: returns (length nm, mid
    point) of the common stretch, or None.
    """
    ax, ay, bx, by = a.GetStart().x, a.GetStart().y, a.GetEnd().x, a.GetEnd().y
    La = math.hypot(bx - ax, by - ay)
    cx, cy, dx, dy = b.GetStart().x, b.GetStart().y, b.GetEnd().x, b.GetEnd().y
    Lb = math.hypot(dx - cx, dy - cy)
    if La == 0 or Lb == 0:
        return None
    u = ((bx - ax) / La, (by - ay) / La)
    v = ((dx - cx) / Lb, (dy - cy) / Lb)
    if abs(u[0] * v[0] + u[1] * v[1]) < math.cos(math.radians(15)):
        return None  # not parallel
    # Positions of b's ends along a, and the common interval
    t0 = (cx - ax) * u[0] + (cy - ay) * u[1]
    t1 = (dx - ax) * u[0] + (dy - ay) * u[1]
    lo, hi = max(0.0, min(t0, t1)), min(La, max(t0, t1))
    if hi <= lo:
        return None
    # Lateral distance between the centre lines, in the middle of the stretch
    tm = (lo + hi) / 2.0
    mx, my = ax + u[0] * tm, ay + u[1] * tm
    lateral = geometry.point_segment_distance(mx, my, cx, cy, dx, dy)
    if lateral > (a.GetWidth() + b.GetWidth()) / 2.0:
        return None  # side by side, the copper does not overlap
    return hi - lo, (mx, my)


def check_broadside(board, s, cu_stack, progress=None, cancel=None):
    """
    Broadside coupling: tracks of two different signal nets running one
    over the other (their copper overlaps seen from above) on ADJACENT
    copper layers. With no plane between them they couple strongly
    (crosstalk). The overlap length of every pair of nets is the measure;
    warning from broadside_mm, error beyond 4 times.
    """
    issues = []
    by_layer = {}
    for t in _copper_tracks(board):
        if _is_arc(t) or not _signal_net(t.GetNetname(), s):
            continue
        by_layer.setdefault(t.GetLayer(), []).append(t)
    pairs = [(cu_stack[i], cu_stack[i + 1]) for i in range(len(cu_stack) - 1)]
    for k, (la, lb) in enumerate(pairs):
        if progress:
            progress(k, len(pairs))
        if cancel and cancel():
            break
        idx = _PointIndex(pcbnew.FromMM(5))
        for t in by_layer.get(lb, ()):
            p = t.GetStart()
            idx.add(p.x, p.y, t)
        total = {}   # (net a, net b) -> [length nm, best point, tracks]
        for a in by_layer.get(la, ()):
            m = a.GetStart()
            reach = a.GetLength() + pcbnew.FromMM(30)
            seen = set()
            for _d, b in idx.within(m.x, m.y, reach):
                if id(b) in seen or b.GetNetname() == a.GetNetname():
                    continue
                seen.add(id(b))
                ov = _overlap(a, b)
                if ov is None:
                    continue
                key = (a.GetNetname(), b.GetNetname())
                rec = total.setdefault(key, [0.0, ov[1], []])
                rec[0] += ov[0]
                for tt in (a, b):
                    if tt not in rec[2]:
                        rec[2].append(tt)
        for (na, nb), (L, (x, y), ts) in total.items():
            L_mm = _mm(L)
            if L_mm < s.broadside_mm:
                continue
            sev = SEV_ERROR if L_mm > 4 * s.broadside_mm else SEV_WARNING
            detail = _("{0} su {1} corre sopra {2} su {3} per {4:.1f} mm: senza un piano in mezzo si accoppiano "
                       "(crosstalk)").format(na, board.GetLayerName(la), nb, board.GetLayerName(lb), L_mm)
            issues.append(LayoutIssue(sev, CHECK_BROADSIDE, f"{na} / {nb}", detail, L_mm, s.broadside_mm,
                                      int(x), int(y), ts))
    return issues


# ------------------------------------------------------- all together

def check_names():
    """Readable names of the checks (for the 'Check' column)."""
    return {
        CHECK_DECAP: _("Disaccoppiamento"),
        CHECK_LAYER_CHANGE: _("Cambio layer"),
        CHECK_STITCHING: _("Via di stitching"),
        CHECK_PLANE_GAP: _("Piano interrotto"),
        CHECK_PLANE_EDGE: _("Bordo del piano"),
        CHECK_WIDTH: _("Larghezza tracce"),
        CHECK_ISOLATION: _("Isolamento"),
        CHECK_LENGTH: _("Lunghezze"),
        CHECK_STUB: _("Rami morti"),
        CHECK_ACUTE: _("Angoli acuti"),
        CHECK_WIDTH_STEP: _("Cambi di larghezza"),
        CHECK_VIA_IN_PAD: _("Via nei pad"),
        CHECK_TOMBSTONE: _("Tombstoning"),
        CHECK_VIA_CURRENT: _("Corrente via"),
        CHECK_CRYSTAL: _("Quarzo"),
        CHECK_BROADSIDE: _("Tracce sovrapposte"),
    }


def run_checks(board, s, progress=None, cancel=None):
    """
    Runs the enabled checks on the whole board.

    progress(fraction 0..1, text): called often, the GUI also uses it to keep
    the window responsive (wx.Yield) and show the current check.
    cancel(): True to stop; what was found so far is returned.

    Returns (issues sorted by severity and check, list of notes for the user).
    """
    cu_stack = list(board.GetEnabledLayers().CuStack())
    gnd_zones = _ground_zones_by_layer(board, s.ref_filter, cu_stack)
    # Copper islands of the ground fill (fallback: plain coverage test)
    islands = _Islands(gnd_zones, s.use_islands)
    # Bucket size of the via index: about the largest search radius used
    cell = pcbnew.FromMM(max(s.gnd_via_mm, s.return_via_mm, s.stitch_spacing_mm / 2, 1.0))
    stitch_idx = _ground_stitch_index(board, s.ref_filter, cu_stack, islands, cell)

    # The enabled checks with their weight on the progress bar
    plan = []
    if s.do_decap:
        plan.append((CHECK_DECAP, 1))
    if s.do_layer_change:
        plan.append((CHECK_LAYER_CHANGE, 2))
    if s.do_stitching:
        plan.append((CHECK_STITCHING, 4))
    if s.do_plane_gap:
        plan.append((CHECK_PLANE_GAP, 4))
    if s.do_plane_edge:
        plan.append((CHECK_PLANE_EDGE, 3))
    if s.do_width:
        plan.append((CHECK_WIDTH, 1))
    if s.do_isolation:
        plan.append((CHECK_ISOLATION, 2))
    if s.do_length:
        plan.append((CHECK_LENGTH, 1))
    # Checks 9-16, with their weight on the progress bar
    for flag, key, weight in ((s.do_stub, CHECK_STUB, 1), (s.do_acute, CHECK_ACUTE, 1),
                              (s.do_width_step, CHECK_WIDTH_STEP, 1), (s.do_via_in_pad, CHECK_VIA_IN_PAD, 1),
                              (s.do_tombstone, CHECK_TOMBSTONE, 1), (s.do_via_current, CHECK_VIA_CURRENT, 1),
                              (s.do_crystal, CHECK_CRYSTAL, 1), (s.do_broadside, CHECK_BROADSIDE, 2)):
        if flag:
            plan.append((key, weight))
    # Copper of the board by net, shared by the stub, angle, width-step and
    # tombstone checks (built only if one of them runs)
    copper = None
    if s.do_stub or s.do_acute or s.do_width_step or s.do_tombstone:
        copper = _NetCopper(board)
    # Stackup (dielectric heights, copper): read once, only if a check needs it
    stackup = {}
    if s.do_plane_edge or s.do_length:
        try:
            from .impedance import read_stackup

            stackup, _note = read_stackup(board)
        except Exception:
            stackup = {}  # the checks use their fallback values
    total_w = sum(w for _k, w in plan) or 1
    names = check_names()

    issues, notes = [], []
    done_w = 0
    for key, weight in plan:
        if cancel and cancel():
            break

        def sub(i, n, key=key, weight=weight, base=done_w):
            # Progress of one check, mapped onto its share of the total
            if progress:
                frac = (base + weight * (i / n if n else 1)) / total_w
                progress(frac, names[key])

        sub(0, 1)
        if key == CHECK_DECAP:
            issues += check_decoupling(board, s, cu_stack, gnd_zones, stitch_idx)
        elif key == CHECK_LAYER_CHANGE:
            issues += check_layer_changes(board, s, cu_stack, islands, stitch_idx, sub, cancel)
        elif key == CHECK_STITCHING:
            found, note = check_stitching(board, s, cu_stack, gnd_zones, islands, stitch_idx, sub, cancel)
            issues += found
            if note:
                notes.append(note)
        elif key == CHECK_PLANE_GAP:
            issues += check_plane_gaps(board, s, sub, cancel)
        elif key == CHECK_PLANE_EDGE:
            issues += check_plane_edges(board, s, cu_stack, gnd_zones, stackup, sub, cancel)
        elif key == CHECK_STUB:
            issues += check_stubs(board, s, copper)
        elif key == CHECK_ACUTE:
            issues += check_acute_angles(board, s, copper)
        elif key == CHECK_WIDTH_STEP:
            issues += check_width_steps(board, s, copper)
        elif key == CHECK_VIA_IN_PAD:
            issues += check_vias_in_pads(board, s)
        elif key == CHECK_TOMBSTONE:
            issues += check_tombstoning(board, s, copper)
        elif key == CHECK_BROADSIDE:
            issues += check_broadside(board, s, cu_stack, sub, cancel)
        else:
            # Checks returning (issues, notes)
            if key == CHECK_WIDTH:
                found, more = check_track_width(board, s, cu_stack)
            elif key == CHECK_ISOLATION:
                found, more = check_isolation(board, s, cu_stack, sub, cancel)
            elif key == CHECK_VIA_CURRENT:
                found, more = check_via_current(board, s)
            elif key == CHECK_CRYSTAL:
                found, more = check_crystal(board, s, cu_stack)
            else:
                found, more = check_lengths(board, s, cu_stack, stackup)
            issues += found
            notes += more
        done_w += weight

    if s.use_islands and not islands.enabled and any(gnd_zones.values()):
        notes.append(_("Isole di rame non leggibili in questa versione di KiCad: controlli fatti "
                       "senza distinguere le isole."))
    if not any(gnd_zones.values()):
        notes.append(_("Nessuna zona di massa ({0}) riempita sulla scheda: riempi le zone (tasto B) "
                       "prima dei controlli.").format(s.ref_filter))

    issues.sort(key=lambda it: (-it.severity, CHECK_ORDER.index(it.check), it.obj))
    return issues, notes


# ------------------------------------------------------- markers on the board

def _circle(board, layer, x, y, radius_nm, filled, width_nm=0):
    """Graphic circle (PCB_SHAPE) added to the board; returns it."""
    c = pcbnew.PCB_SHAPE(board)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetFilled(filled)
    c.SetLayer(layer)
    c.SetCenter(pcbnew.VECTOR2I(int(x), int(y)))
    c.SetEnd(pcbnew.VECTOR2I(int(x + radius_nm), int(y)))
    c.SetWidth(int(width_nm))
    board.Add(c)
    return_path.register_marker(c)  # removed later by its UUID, see clear_highlight
    return c


def _area_shape(board, layer, outer, holes, width_nm):
    """Filled polygon (PCB_SHAPE) with holes added to the board; returns it."""
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in outer:
        ps.Append(int(x), int(y))
    for hole in holes:
        h = ps.NewHole(0)
        for x, y in hole:
            ps.Append(int(x), int(y), 0, h)
    sh = pcbnew.PCB_SHAPE(board)
    sh.SetShape(pcbnew.SHAPE_T_POLY)
    sh.SetPolyShape(ps)
    sh.SetFilled(True)
    sh.SetWidth(int(width_nm))
    sh.SetLayer(layer)
    board.Add(sh)
    return_path.register_marker(sh)  # removed later by its UUID
    return sh


def _measure(board, layer, x0, y0, x1, y1, text, marks=True):
    """
    Measure drawn on the board: a segment from the start point to the end
    point and the value written next to its middle. With marks=True (the
    stitching areas) also a cross on the start point (the farthest point of
    the area) and a circle on the end point (the via used); with
    marks=False (plane edge) only the segment and the value. Returns the
    shapes.
    """
    out = []
    w = pcbnew.FromMM(0.15)
    arm = pcbnew.FromMM(0.8)

    def seg(ax, ay, bx, by):
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sh.SetStart(pcbnew.VECTOR2I(int(ax), int(ay)))
        sh.SetEnd(pcbnew.VECTOR2I(int(bx), int(by)))
        sh.SetWidth(int(w))
        sh.SetLayer(layer)
        board.Add(sh)
        return_path.register_marker(sh)
        out.append(sh)

    if marks:
        seg(x0 - arm, y0 - arm, x0 + arm, y0 + arm)   # cross on the farthest point
        seg(x0 - arm, y0 + arm, x0 + arm, y0 - arm)
    seg(x0, y0, x1, y1)                               # the measured distance
    if marks:
        out.append(_circle(board, layer, x1, y1, pcbnew.FromMM(0.6), False, w))  # the via used
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(layer)
    # Smaller text for the short plane-edge measures
    size = pcbnew.FromMM(1.2 if marks else 0.6)
    t.SetTextSize(pcbnew.VECTOR2I(size, size))
    t.SetTextThickness(pcbnew.FromMM(0.18))
    # A bit off the middle of the segment, on its side, so it does not cover it
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    L = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / L, (x1 - x0) / L
    t.SetPosition(pcbnew.VECTOR2I(int(mx + nx * size), int(my + ny * size)))
    board.Add(t)
    return_path.register_marker(t)
    out.append(t)
    return out


def issue_key(it):
    """
    Stable identity of a row, used to remember that the user excluded it:
    the check, the object text and the UUIDs of the board objects involved
    (they do not change between runs unless those objects are edited). Rows
    without objects (stitching areas) use their position on a 1 mm grid.
    """
    uuids = sorted(u for u in (return_path._uuid(o) for o in it.items) if u)
    if uuids:
        where = ",".join(uuids)
    else:
        where = "@{0:.0f},{1:.0f}".format(it.x_nm / 1e6, it.y_nm / 1e6)
    return f"{it.check}|{it.obj}|{where}"


def highlight(board, issues, error_layer=pcbnew.User_1, warning_layer=pcbnew.User_2, skip=()):
    """
    Draws the issues on two graphic layers (same convention as the Return
    Path tab): User.1 = errors, User.2 = warnings.
    - stitching areas: a filled shape covering the whole area farther than
      the limit from a via; placing a ground via inside it removes the part
      of the area around the via. On top of it the measure: a cross on the
      farthest point, a segment to the via used and the distance;
    - all the other issues: a ring centred on the problem (pin, via, track).
    'skip': indexes of the issues NOT to draw (the rows excluded by the user).
    Returns (markers created, {issue index: marker}).
    """
    markers, rings = [], {}
    ring_r, ring_w = pcbnew.FromMM(1.2), pcbnew.FromMM(0.2)
    for k, it in enumerate(issues):
        if k in skip:
            continue  # excluded row: nothing on the board
        layer = error_layer if it.severity == SEV_ERROR else warning_layer
        if it.polys:
            shapes = [_area_shape(board, layer, outer, holes, pcbnew.FromMM(0.1))
                      for outer, holes in it.polys]
            markers.extend(shapes)
            rings[k] = shapes[0]
            # The measure: farthest point of the area -> via used, with value
            if it.ref_xy is not None and it.measured_mm is not None:
                markers.extend(_measure(board, layer, it.x_nm, it.y_nm, it.ref_xy[0], it.ref_xy[1],
                                        f"{it.measured_mm:.1f} mm"))
        else:
            ring = _circle(board, layer, it.x_nm, it.y_nm, ring_r, False, ring_w)
            markers.append(ring)
            rings[k] = ring
            # Plane edge: the measured segment (track edge -> end of the
            # ground copper) with its value, so the measure can be checked
            if it.check == CHECK_PLANE_EDGE and it.ref_xy is not None and it.measured_mm is not None:
                markers.extend(_measure(board, layer, it.x_nm, it.y_nm, it.ref_xy[0], it.ref_xy[1],
                                        f"{it.measured_mm:.2f} mm", marks=False))
    _refresh()
    return markers, rings


def _refresh():
    """Redraws Pcbnew (UpdateUserInterface is not available in every build)."""
    pcbnew.Refresh()
    try:
        pcbnew.UpdateUserInterface()
    except Exception:
        pass
