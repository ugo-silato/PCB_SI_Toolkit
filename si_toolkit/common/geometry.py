"""
Geometric functions shared by the analysis modules.

The style follows the one already used in PnPImporter to rebuild the
netlist from the physical copper (collision detection with
GetEffectiveShape + Collide), adapted here to find out whether a point or
a track is covered by a reference plane.
"""
import pcbnew


def sample_points_along_track(track, step_nm, max_samples=30):
    """
    Returns a list of points (VECTOR2I) sampled along the track every
    'step_nm' nanometers (KiCad's internal unit).

    It is used to check the presence of the reference plane not only at the
    track ends but also at intermediate points: a plane split can cut the path
    in the middle, not only at the start/end pads.

    'max_samples' limits the number of points even on very long tracks (e.g. a
    60-80 mm track to an antenna): without this limit, with a 1 mm step there
    would be dozens of points per track, and every point costs a call to
    HitTestFilledArea (see point_covered_by_zone) plus, in return_path.py, a
    stitching-via check. On a board with many long tracks the total cost grows
    quickly and can freeze the interface for tens of seconds: better a sparser
    sampling with a fixed cap than an exact but potentially blocking analysis.
    """
    start = track.GetStart()
    end = track.GetEnd()
    length = track.GetLength()  # length in nm (KiCad internal unit)

    if length == 0:
        return [start]

    n_steps = min(max_samples, max(1, int(length // step_nm)))
    points = []
    for i in range(n_steps + 1):
        t = i / n_steps
        x = int(start.x + (end.x - start.x) * t)
        y = int(start.y + (end.y - start.y) * t)
        points.append(pcbnew.VECTOR2I(x, y))
    return points


def is_teardrop(zone):
    """
    True if the zone is a teardrop added by KiCad where a track enters a pad
    or a via. For KiCad a teardrop is a small zone of the pad's net with a
    solid connection: it is copper, but not a plane or a pour.
    """
    fn = getattr(zone, "IsTeardropArea", None)  # KiCad 7-10 API
    if fn is not None:
        try:
            if fn():
                return True
        except Exception:
            pass
    # Fallback: KiCad names the teardrops "$teardrop_..."
    try:
        return "teardrop" in zone.GetZoneName().lower()
    except Exception:
        return False


def find_reference_zone(board, layer_id, net_name_filter=None):
    """
    Looks for the first filled ZONE on layer 'layer_id' that corresponds to a
    reference plane (typically GND or a supply), filtering by a substring of
    the net name if given.

    Returns the ZONE object or None if not found.

    NOTE: this is a simplified choice meant for the common case (a single
    reference plane per layer). If the board has several separate planes on
    the same layer (e.g. digital GND and analog GND side by side) it must be
    extended to return a list and let the user choose which one to use as
    reference for that group of tracks.
    """
    for zone in board.Zones():
        # IsOnLayer (not GetLayer) because multilayer zones have GetLayer() ==
        # undefined but belong to several layers
        if not zone.IsOnLayer(layer_id):
            continue
        if not zone.IsFilled() or is_teardrop(zone):
            continue
        net_name = zone.GetNetname()
        if net_name_filter is None:
            return zone
        if net_name_filter.upper() in net_name.upper():
            return zone
    return None


def find_reference_zones(board, layer_id, net_name_filter=None):
    """
    Like find_reference_zone, but returns ALL the filled zones of the layer
    that match the filter (a list, possibly empty).

    Needed because the reference layer can hold several separate pours with
    the same net (e.g. a ground island near a connector): taking only the
    first one made the points covered by the other pours look "uncovered".
    """
    zones = []
    for zone in board.Zones():
        # IsOnLayer: see the note in find_reference_zone (multilayer zones)
        if not zone.IsOnLayer(layer_id):
            continue
        if not zone.IsFilled() or is_teardrop(zone):
            continue  # teardrops are not a plane
        if net_name_filter is None or net_name_filter.upper() in zone.GetNetname().upper():
            zones.append(zone)
    return zones


def point_covered_by_any_zone(zones, layer_id, point, accuracy_nm=0):
    """True if the point is covered by the fill of at least one of the zones."""
    for zone in zones:
        if zone.HitTestFilledArea(layer_id, point, accuracy_nm):
            return True
    return False


def point_covered_by_zone(zone, layer_id, point, accuracy_nm=0):
    """
    True if 'point' is covered by the zone fill on the given layer. Uses
    HitTestFilledArea, which works on the copper polygon actually poured
    (already reduced by clearance and thermal relief), not on the outline
    drawn by the user while designing.
    """
    if zone is None:
        return False
    return zone.HitTestFilledArea(layer_id, point, accuracy_nm)


def lateral_gaps(zones, layer_id, track, step_nm, max_nm, n_samples, margin_nm, pads=()):
    """
    Measures, from a few points along a straight track, the distance between
    the track edge and the filled copper of 'zones' on the same layer,
    separately on the two sides. It advances in 'step_nm' steps up to 'max_nm'
    from the edge; if no copper is found that side is None.

    Returns a list of (gap_side_1, gap_side_2) in nm, one per test point. The
    points near the ends (within 'margin_nm') are skipped: pads and bends are
    there, and the distance is not representative.

    'pads': ground pads on the same layer; their copper also counts as side
    ground (e.g. the GND pad of a capacitor next to the line).
    """
    start, end = track.GetStart(), track.GetEnd()
    dx, dy = end.x - start.x, end.y - start.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux  # normal to the track
    half_w = track.GetWidth() / 2.0

    # Test positions along the track (distance from the start)
    if length > 2 * margin_nm and n_samples > 1:
        span = length - 2 * margin_nm
        positions = [margin_nm + span * (i + 0.5) / n_samples for i in range(n_samples)]
    else:
        positions = [length / 2.0]

    result = []
    for pos in positions:
        cx, cy = start.x + ux * pos, start.y + uy * pos
        sides = []
        for sign in (1, -1):
            gap = None
            d = half_w + step_nm
            while d <= half_w + max_nm:
                p = pcbnew.VECTOR2I(int(cx + sign * nx * d), int(cy + sign * ny * d))
                if point_covered_by_any_zone(zones, layer_id, p) or any(
                    pad.HitTest(p) for pad in pads
                ):
                    # Copper found between (d - step) and d: the interval is
                    # narrowed with a bisection, so the gap is not rounded to
                    # the search step (about 1 um accuracy)
                    lo, hi = d - step_nm, d
                    for _ in range(6):
                        mid = (lo + hi) / 2.0
                        pm = pcbnew.VECTOR2I(
                            int(cx + sign * nx * mid), int(cy + sign * ny * mid)
                        )
                        if point_covered_by_any_zone(zones, layer_id, pm):
                            hi = mid
                        else:
                            lo = mid
                    gap = hi - half_w
                    break
                d += step_nm
            sides.append(gap)
        result.append(tuple(sides))
    return result


def point_segment_distance(px, py, ax, ay, bx, by):
    """Distance (same units as the arguments) between point P and segment AB."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    cx, cy = ax + u * dx, ay + u * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def pair_spacing(tracks_p, tracks_n, step_nm, max_samples, coupling_limit_nm):
    """
    Edge-to-edge distance between two groups of tracks (the two nets of a
    differential pair) measured from points along the tracks of the first
    group.

    For each point it takes the distance from the closest segment of the
    second group minus half of the two widths (free copper space between the
    edges). Points with spacing above 'coupling_limit_nm' are considered
    uncoupled (the tracks separate there).

    Returns (median spacing in nm or None, coupled fraction, no. of points).
    """
    segs = [(t.GetStart(), t.GetEnd(), t.GetWidth()) for t in tracks_n
            if t.Type() == pcbnew.PCB_TRACE_T]
    if not segs:
        return None, 0.0, 0
    gaps = []
    for t in tracks_p:
        if t.Type() != pcbnew.PCB_TRACE_T:
            continue
        for p in sample_points_along_track(t, step_nm, 10):
            best = min(
                point_segment_distance(p.x, p.y, a.x, a.y, b.x, b.y) - w / 2.0
                for a, b, w in segs
            ) - t.GetWidth() / 2.0
            gaps.append(max(best, 0.0))
    if not gaps:
        return None, 0.0, 0
    if len(gaps) > max_samples:  # uniform subsampling
        stride = len(gaps) / max_samples
        gaps = [gaps[int(i * stride)] for i in range(max_samples)]
    coupled = sorted(g for g in gaps if g <= coupling_limit_nm)
    fraction = len(coupled) / len(gaps)
    median = coupled[len(coupled) // 2] if coupled else None
    return median, fraction, len(gaps)
