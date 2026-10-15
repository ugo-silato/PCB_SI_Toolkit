"""
"Return Path Checker" module.

Basic idea: the high-frequency return current of a signal track flows in
the immediately adjacent reference plane (above or below), following the
path of the track itself to minimize the loop area. If along part of the
path the plane is missing (split, hole, isolated area) the return has to
"jump" sideways, increasing loop area, EMI and the impedance seen by the
signal.

This module does NOT run a real electromagnetic field solve: it is a
geometric continuity check. For each track it measures the longest
CONTINUOUS GAP (in mm) where the reference plane is missing below (or
above) the track, and reports only the gaps above a threshold.

Why the gap and not the number of uncovered points:
- on a 2-layer board the pour on the opposite side is interrupted by every
  track crossing it; a perpendicular crossing creates a gap of half a
  millimeter, practically harmless, while a 10-20 mm gap under a fast
  track is a real problem;
- the clearance holes around pads and vias of the same net are not
  discontinuities of the return (the current goes through the via
  itself), so the points near those elements are ignored.
"""
from dataclasses import dataclass, field

import pcbnew

from ..common import geometry
from ..common.i18n import _

# Sampling distance along the track (0.5 mm) and maximum number of samples per
# track (very long tracks are sampled more sparsely, with a fixed cap on the
# computing cost)
SAMPLE_STEP_NM = pcbnew.FromMM(0.5)
MAX_SAMPLES_PER_TRACK = 200

# Search radius for a stitching via near an uncovered stretch: if there is a
# via on the reference net within this radius, the return can still pass
# nearby, so the problem is "minor"
STITCHING_SEARCH_RADIUS_NM = pcbnew.FromMM(3.0)

# Radius around pads and vias of the SAME net as the track within which an
# uncovered point is ignored (clearance hole in the plane)
HOLE_EXCLUSION_RADIUS_NM = pcbnew.FromMM(1.0)

# Minimum gap (mm) to report a track, if not given by the GUI
DEFAULT_MIN_GAP_MM = 5.0


@dataclass
class ReturnPathIssue:
    """A continuity problem found on a track."""

    track: object  # reference to the pcbnew PCB_TRACK object
    uncovered_points: list = field(default_factory=list)  # only gaps above the threshold
    max_gap_mm: float = 0.0
    has_nearby_stitching_via: bool = False
    # Actual net of the reference plane and name of the layer where the plane
    # is interrupted (shown in the "Reference" column of the GUI)
    ref_net: str = ""
    ref_layer_name: str = ""

    @property
    def track_layer_name(self):
        # Name of the layer the track is on (e.g. "B.Cu")
        return self.track.GetLayerName()

    @property
    def net_name(self):
        return self.track.GetNetname()

    @property
    def length_mm(self):
        return pcbnew.ToMM(self.track.GetLength())


def _copper_layer_stack(board):
    """
    List of the enabled copper layers, from the outermost (top) to the
    innermost (bottom), in the physical order of the stackup.
    """
    return list(board.GetEnabledLayers().CuStack())


def _adjacent_layers(board, layer_id):
    """Copper layers physically adjacent to 'layer_id' (above and/or below)."""
    stack = _copper_layer_stack(board)
    try:
        idx = stack.index(layer_id)
    except ValueError:
        return []

    adjacent = []
    if idx - 1 >= 0:
        adjacent.append(stack[idx - 1])
    if idx + 1 < len(stack):
        adjacent.append(stack[idx + 1])
    return adjacent


def _build_indexes(board):
    """
    Precomputes ONCE two indexes, so the board is not scanned for every
    point:
    - via_index: vias only, tuples (position, net), for the stitching check;
    - hole_index: vias + pads, tuples (position, net), to ignore the clearance
      holes around elements of the same net as the track.

    NOTE: Type() == ... is used instead of IsType([...]) because IsType with a
    list fails with a SWIG error in this KiCad 10 build.
    """
    via_index = []
    hole_index = []
    for track in board.GetTracks():
        if track.Type() != pcbnew.PCB_VIA_T:
            continue
        entry = (track.GetPosition(), track.GetNetname())
        via_index.append(entry)
        hole_index.append(entry)
    for pad in board.GetPads():
        hole_index.append((pad.GetPosition(), pad.GetNetname()))
    return via_index, hole_index


def _near_item_on_net(index, point, net_name, radius_nm):
    """True if the index has an element of the given net within the radius."""
    r2 = radius_nm * radius_nm
    for pos, net in index:
        if net != net_name:
            continue
        dx = pos.x - point.x
        dy = pos.y - point.y
        if dx * dx + dy * dy <= r2:
            return True
    return False


def _uncovered_runs(flags):
    """
    Given a list of booleans (True = uncovered point) returns the list of
    consecutive uncovered stretches as tuples (start_index, end_index), end
    included.
    """
    runs = []
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def analyze_board(
    board,
    reference_net_filter="GND",
    min_gap_mm=DEFAULT_MIN_GAP_MM,
    progress_callback=None,
    should_cancel=None,
    tracks=None,
):
    """
    Analyzes the signal tracks and returns the list of ReturnPathIssue
    (sorted from the longest gap to the shortest).

    reference_net_filter: substring identifying the reference plane zones
    (default "GND").

    min_gap_mm: minimum length (mm) of a continuous stretch without plane for
    the track to be reported.

    progress_callback(index, total): called after each track; the GUI also
    uses it to process events (wx.Yield()).

    should_cancel(): if it returns True the analysis stops and returns what
    was found so far.

    tracks: if given, only these tracks are analyzed (e.g. the selection in
    Pcbnew); otherwise all the tracks of the board.
    """
    issues = []
    # Type() == ... instead of IsType([...]) (see _build_indexes)
    source = board.GetTracks() if tracks is None else tracks
    tracks = [t for t in source if t.Type() == pcbnew.PCB_TRACE_T]
    total = len(tracks)

    via_index, hole_index = _build_indexes(board)

    # Cache of the reference zones per layer
    zones_cache = {}

    def get_reference_zones(layer_id):
        if layer_id not in zones_cache:
            zones_cache[layer_id] = geometry.find_reference_zones(
                board, layer_id, reference_net_filter
            )
        return zones_cache[layer_id]

    for i, track in enumerate(tracks):
        if progress_callback:
            progress_callback(i, total)
        if should_cancel and should_cancel():
            break

        # The tracks on the reference net are not "signal"
        if reference_net_filter.upper() in track.GetNetname().upper():
            continue

        layer_id = track.GetLayer()

        # Adjacent layers that have at least one reference zone. Each is
        # checked SEPARATELY: on 4+ layers an inner track has a plane above and
        # one below, and the interruption may concern only one of them. Each
        # (track, layer) pair is a separate potential problem.
        ref_candidates = []
        for candidate_layer in _adjacent_layers(board, layer_id):
            candidate_zones = get_reference_zones(candidate_layer)
            if candidate_zones:
                ref_candidates.append((candidate_layer, candidate_zones))

        if not ref_candidates:
            continue  # no reference plane for this track

        points = geometry.sample_points_along_track(
            track, SAMPLE_STEP_NM, MAX_SAMPLES_PER_TRACK
        )
        if len(points) < 2:
            continue

        # Distance between two consecutive samples (mm): used to convert the
        # number of consecutive uncovered samples into a gap length
        track_len_mm = pcbnew.ToMM(track.GetLength())
        step_mm = track_len_mm / (len(points) - 1)
        net_name = track.GetNetname()

        # The points near pads/vias of the same net (clearance holes) do not
        # depend on the layer: computed once per track
        near_hole = [
            _near_item_on_net(hole_index, p, net_name, HOLE_EXCLUSION_RADIUS_NM)
            for p in points
        ]

        for ref_layer, ref_zones in ref_candidates:
            flags = []
            for p, is_hole in zip(points, near_hole):
                if is_hole:
                    flags.append(False)  # clearance hole: not a real gap
                else:
                    flags.append(
                        not geometry.point_covered_by_any_zone(ref_zones, ref_layer, p)
                    )

            # Continuous uncovered stretches; only those above the threshold
            # are kept
            bad_points = []
            max_gap = 0.0
            for start, end in _uncovered_runs(flags):
                # Each sample "represents" one track step, so a stretch of k
                # consecutive samples is worth about k * step. With all points
                # uncovered it would give length + 1 step, so the gap is capped
                # at the actual track length.
                gap_mm = min((end - start + 1) * step_mm, track_len_mm)
                if gap_mm >= min_gap_mm:
                    bad_points.extend(points[start : end + 1])
                    max_gap = max(max_gap, gap_mm)

            if bad_points:
                ref_net = ref_zones[0].GetNetname()
                has_via = any(
                    _near_item_on_net(via_index, p, ref_net, STITCHING_SEARCH_RADIUS_NM)
                    for p in bad_points
                )
                issues.append(
                    ReturnPathIssue(
                        track=track,
                        uncovered_points=bad_points,
                        max_gap_mm=max_gap,
                        has_nearby_stitching_via=has_via,
                        ref_net=ref_net,
                        ref_layer_name=board.GetLayerName(ref_layer),
                    )
                )

    issues.sort(key=lambda issue: issue.max_gap_mm, reverse=True)
    return issues


def diagnose_track(board, track, reference_net_filter, log_path):
    """
    Diagnostics of a single track, written to a text file.

    Each step is written to disk (flush + fsync) BEFORE running the next call:
    if an API call crashes KiCad, the last line of the file tells which one it
    was. Each call is also in a try/except, so ordinary Python exceptions end
    up in the log without stopping the rest.
    """
    import os

    f = open(log_path, "w", encoding="utf-8")

    def log(msg):
        f.write(msg + "\n")
        f.flush()
        os.fsync(f.fileno())

    def attempt(label, func):
        # Writes the label, runs, writes the result or the exception
        log(f"-> {label}")
        try:
            result = func()
            log(_("   OK: {0}").format(result))
            return result
        except Exception as exc:
            log(_("   ERRORE: {0}: {1}").format(type(exc).__name__, exc))
            return None

    try:
        layer = track.GetLayer()
        log(_("Traccia net={0} layer={1}").format(track.GetNetname(), board.GetLayerName(layer)))
        log(_("Start={0} End={1} lunghezza_mm={2:.2f}").format(track.GetStart(), track.GetEnd(), pcbnew.ToMM(track.GetLength())))

        adj = _adjacent_layers(board, layer)
        log(_("Layer adiacenti: ") + ", ".join(board.GetLayerName(a) for a in adj))

        # Test points: start, middle, end (a fresh VECTOR2I is used)
        pts = geometry.sample_points_along_track(track, pcbnew.FromMM(5), 4)
        log(_("Punti di prova: {0}").format(len(pts)))

        # List of ALL the zones, with simple calls only
        log(_("--- Zone sulla board ---"))
        zones = list(board.Zones())
        for n, z in enumerate(zones):
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            lname = attempt(_("zona {0} GetLayer").format(n), lambda: board.GetLayerName(z.GetLayer()))
            attempt(_("zona {0} GetNetname").format(n), lambda: z.GetNetname())
            attempt(_("zona {0} IsFilled").format(n), lambda: z.IsFilled())
            attempt(_("zona {0} GetZoneName").format(n), lambda: z.GetZoneName())

        # Coverage test, one method at a time, from the least risky
        log(_("--- Test copertura ---"))
        for n, z in enumerate(zones):
            if not any(z.IsOnLayer(a) for a in adj):
                continue
            # Only the zones of the reference net (240+ on the board)
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            ref_l = [a for a in adj if z.IsOnLayer(a)][0]
            for k, p in enumerate(pts):
                attempt(
                    _("zona {0} HitTestFilledArea punto {1} ({2},{3})").format(n, k, p.x, p.y),
                    lambda: z.HitTestFilledArea(ref_l, p, 0),
                )
        log(_("--- Poligoni riempiti (chiamata piu' rischiosa, per ultima) ---"))
        for n, z in enumerate(zones):
            if not any(z.IsOnLayer(a) for a in adj):
                continue
            if reference_net_filter.upper() not in z.GetNetname().upper():
                continue
            ref_l = [a for a in adj if z.IsOnLayer(a)][0]
            polys = attempt(_("zona {0} GetFilledPolysList").format(n),
                            lambda: z.GetFilledPolysList(ref_l))
            if polys is not None:
                attempt(_("zona {0} OutlineCount").format(n), lambda: polys.OutlineCount())
        log(_("FINE diagnostica senza crash."))
    finally:
        f.close()


def highlight_issues(board, issues, severe_layer=pcbnew.User_1,
                     minor_layer=pcbnew.User_2):
    """
    Draws a small circle (PCB_SHAPE) at every point of the uncovered stretches,
    on two different graphic (non-electrical) layers, so the two cases have
    different colors in Pcbnew:
    - 'severe_layer' (User.1): no stitching via nearby, the return current has
      no alternative path;
    - 'minor_layer' (User.2): there is a stitching via nearby.
    The color is the layer color, which can be set in the Appearance panel.
    """
    marker_radius_nm = pcbnew.FromMM(0.3)

    created_markers = []
    for issue in issues:
        for point in issue.uncovered_points:
            marker = pcbnew.PCB_SHAPE(board)
            marker.SetShape(pcbnew.SHAPE_T_CIRCLE)
            marker.SetFilled(True)
            # Layer (and therefore color) according to severity
            marker.SetLayer(minor_layer if issue.has_nearby_stitching_via else severe_layer)
            marker.SetCenter(point)
            marker.SetEnd(pcbnew.VECTOR2I(point.x + marker_radius_nm, point.y))
            marker.SetWidth(0)
            board.Add(marker)
            created_markers.append(marker)

    pcbnew.Refresh()
    # Also forces the interface to redraw: without it, in some builds the new
    # objects do not show up until the view is moved
    try:
        pcbnew.UpdateUserInterface()
    except Exception:
        pass
    return created_markers


def clear_highlight(board, markers):
    """Removes from the board all the markers created by highlight_issues."""
    for marker in markers:
        board.Remove(marker)
    pcbnew.Refresh()
