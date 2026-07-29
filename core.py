# -*- coding: utf-8 -*-
"""Kernlogik der Bohrungs-Deduplizierung.

Sammelt saemtliche Bohrungen eines Boards (Via-Bohrungen und Pad-Bohrungen),
findet Gruppen, die auf derselben Stelle liegen, und schlaegt vor, welche
Objekte entfernt werden koennen. Dieses Modul ist bewusst frei von wxPython,
damit es sich auch headless testen laesst.
"""

from __future__ import annotations

import math
from collections import defaultdict

import pcbnew

VIA = "via"
PAD = "pad"

CAT_VIA_STACK = "via_stack"
CAT_VIA_IN_PAD = "via_in_pad"
CAT_PAD_STACK = "pad_stack"
CAT_NET_CONFLICT = "net_conflict"
CAT_OVERLAP = "overlap"

CATEGORY_LABELS = {
    CAT_VIA_STACK: "Vias gestapelt",
    CAT_VIA_IN_PAD: "Via in Pad-Bohrung",
    CAT_PAD_STACK: "Bohrungs-Footprints deckungsgleich",
    CAT_NET_CONFLICT: "Netz-Konflikt",
    CAT_OVERLAP: "Bohrungen überlappen",
}

CATEGORY_ORDER = [
    CAT_VIA_STACK,
    CAT_VIA_IN_PAD,
    CAT_PAD_STACK,
    CAT_NET_CONFLICT,
    CAT_OVERLAP,
]

# Zwei Bohrungen, die sich nur um weniger als diesen Betrag beruehren, gelten
# nicht als ueberlappend (Rundungsreste aus dem Router).
TANGENT_SLACK_NM = 1000


def to_mm(value):
    """Interne Einheiten (nm) als Millimeter-Zahl."""
    return value / float(pcbnew.PCB_IU_PER_MM)


def format_mm(value, digits=3):
    return ("%.*f" % (digits, to_mm(value))).rstrip("0").rstrip(".") or "0"


class Hole(object):
    """Eine physikalische Bohrung auf dem Board."""

    __slots__ = (
        "kind", "item", "x", "y", "dx", "dy", "angle",
        "netcode", "netname", "label", "span", "footprint", "npth",
    )

    def __init__(self, kind, item, x, y, dx, dy, angle,
                 netcode, netname, label, span, footprint, npth):
        self.kind = kind
        self.item = item
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.angle = angle
        self.netcode = netcode
        self.netname = netname
        self.label = label
        self.span = span            # (oberster, unterster Kupferlagen-Index) oder None
        self.footprint = footprint  # nur bei Pads gesetzt
        self.npth = npth

    @property
    def outer_radius(self):
        return max(self.dx, self.dy) / 2.0

    @property
    def round(self):
        return self.dx == self.dy

    def drill_text(self):
        if self.round:
            return "Ø%s mm" % format_mm(self.dx)
        return "%s × %s mm" % (format_mm(self.dx), format_mm(self.dy))

    def position_text(self):
        return "%s / %s" % (format_mm(self.x), format_mm(self.y))

    def describe(self):
        return "%s (%s)" % (self.label, self.drill_text())


class Finding(object):
    """Ein Befund: `target` koennte zugunsten von `keeper` entfallen."""

    __slots__ = ("category", "target", "keeper", "removable", "safe", "detail")

    def __init__(self, category, target, keeper, removable, safe, detail):
        self.category = category
        self.target = target
        self.keeper = keeper
        self.removable = removable
        self.safe = safe
        self.detail = detail

    @property
    def category_label(self):
        return CATEGORY_LABELS.get(self.category, self.category)

    def swap(self):
        """Richtung umdrehen: behalten und entfernen tauschen."""
        self.target, self.keeper = self.keeper, self.target
        if self.category == CAT_PAD_STACK:
            self.detail = pad_stack_detail(self.target, self.keeper)


# --- Sammeln ---------------------------------------------------------------

def _layer_order(board):
    """Kupferlagen in Stapelreihenfolge auf laufende Indizes abbilden."""
    stack = []
    try:
        stack = [layer for layer in board.GetEnabledLayers().CuStack()]
    except Exception:
        stack = []
    if not stack:
        stack = [pcbnew.F_Cu, pcbnew.B_Cu]
    return dict((layer, index) for index, layer in enumerate(stack))


def _pad_angle(pad):
    try:
        return math.radians(pad.GetOrientation().AsDegrees())
    except Exception:
        return 0.0


def _via_width(via):
    """Via-Breite versionsunabhaengig ermitteln (KiCad 10 will eine Lage)."""
    try:
        return via.GetWidth(via.TopLayer())
    except Exception:
        try:
            return via.GetWidth()
        except Exception:
            return 0


def collect_holes(board):
    order = _layer_order(board)
    last = max(order.values()) if order else 1
    holes = []

    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        for pad in footprint.Pads():
            drill = pad.GetDrillSize()
            if drill.x <= 0 or drill.y <= 0:
                continue
            position = pad.GetPosition()
            npth = pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
            number = pad.GetNumber()
            holes.append(Hole(
                kind=PAD,
                item=pad,
                x=position.x,
                y=position.y,
                dx=drill.x,
                dy=drill.y,
                angle=_pad_angle(pad),
                netcode=pad.GetNetCode(),
                netname=pad.GetNetname(),
                label="%s.%s" % (reference, number) if number else reference,
                span=None if npth else (0, last),
                footprint=footprint,
                npth=npth,
            ))

    for track in board.GetTracks():
        if track.Type() != pcbnew.PCB_VIA_T:
            continue
        via = track.Cast()
        position = via.GetPosition()
        drill = via.GetDrillValue()
        if drill <= 0:
            continue
        top = order.get(via.TopLayer(), 0)
        bottom = order.get(via.BottomLayer(), last)
        netname = via.GetNetname()
        holes.append(Hole(
            kind=VIA,
            item=via,
            x=position.x,
            y=position.y,
            dx=drill,
            dy=drill,
            angle=0.0,
            netcode=via.GetNetCode(),
            netname=netname,
            label="Via %s" % (netname or "<kein Netz>"),
            span=(min(top, bottom), max(top, bottom)),
            footprint=None,
            npth=False,
        ))

    return holes


# --- Geometrie -------------------------------------------------------------

def _distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _contains(outer, inner, tolerance):
    """Liegt die Bohrung `inner` vollstaendig in der Bohrung `outer`?"""
    inner_radius = inner.outer_radius
    dx = inner.x - outer.x
    dy = inner.y - outer.y
    if outer.round:
        return math.hypot(dx, dy) + inner_radius <= outer.dx / 2.0 + tolerance

    # Langloch: Versatz in das Pad-Koordinatensystem drehen. Da das Vorzeichen
    # der Drehung von der Lage abhaengt, wird konservativ beides geprueft.
    for sign in (1.0, -1.0):
        cos_a = math.cos(sign * outer.angle)
        sin_a = math.sin(sign * outer.angle)
        local_x = dx * cos_a - dy * sin_a
        local_y = dx * sin_a + dy * cos_a
        if not (abs(local_x) + inner_radius <= outer.dx / 2.0 + tolerance and
                abs(local_y) + inner_radius <= outer.dy / 2.0 + tolerance):
            return False
    return True


def _span_contains(outer, inner):
    """Deckt der Lagenbereich `outer` den Bereich `inner` vollstaendig ab?"""
    if outer is None:
        return inner is None
    if inner is None:
        return True
    return outer[0] <= inner[0] and outer[1] >= inner[1]


def _span_size(span):
    return -1 if span is None else span[1] - span[0]


def _neighbour_pairs(holes, position_tolerance):
    """Alle Paare liefern, deren Bohrungen sich beruehren oder ueberlappen."""
    if not holes:
        return
    reach = max(hole.outer_radius for hole in holes) * 2 + position_tolerance
    cell = int(reach) + 1

    buckets = defaultdict(list)
    for index, hole in enumerate(holes):
        buckets[(hole.x // cell, hole.y // cell)].append(index)

    for (cx, cy), own in buckets.items():
        neighbourhood = []
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                neighbourhood.extend(buckets.get((cx + offset_x, cy + offset_y), ()))
        for i in own:
            for j in neighbourhood:
                if i >= j:
                    continue
                distance = _distance(holes[i], holes[j])
                limit = holes[i].outer_radius + holes[j].outer_radius + position_tolerance
                if distance <= limit:
                    yield i, j, distance


# --- Analyse ---------------------------------------------------------------

def _pick_survivor(holes, group):
    """Das Via behalten, das den groessten Lagenbereich und die groesste
    Bohrung abdeckt."""
    def rank(index):
        hole = holes[index]
        return (_span_size(hole.span), hole.dx, _via_width(hole.item), -index)

    return max(group, key=rank)


def _analyse_via_stacks(holes, pairs, scheduled):
    parent = {}

    def find(index):
        parent.setdefault(index, index)
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i, j in pairs:
        union(i, j)

    clusters = defaultdict(list)
    for index in list(parent):
        clusters[find(index)].append(index)

    findings = []
    for members in clusters.values():
        by_net = defaultdict(list)
        for index in members:
            by_net[holes[index].netcode].append(index)

        real_nets = sorted(net for net in by_net if net > 0)
        if len(real_nets) > 1:
            names = ", ".join(sorted(set(
                holes[index].netname or "<kein Netz>" for index in members)))
            first = holes[by_net[real_nets[0]][0]]
            second = holes[by_net[real_nets[1]][0]]
            findings.append(Finding(
                CAT_NET_CONFLICT, second, first, False, False,
                "Gestapelte Vias mit verschiedenen Netzen (%s) – manuell klären" % names))
            groups = [by_net[net] for net in real_nets]
        else:
            # Vias ohne Netz gehören zum einzigen echten Netz der Gruppe.
            groups = [members]

        for group in groups:
            if len(group) < 2:
                continue
            survivor = _pick_survivor(holes, group)
            keeper = holes[survivor]
            for index in group:
                if index == survivor:
                    continue
                hole = holes[index]
                if _span_contains(keeper.span, hole.span):
                    detail = "identische Position, %d-fach gestapelt" % len(group)
                    if hole.netcode == 0 and keeper.netcode > 0:
                        detail = "Via ohne Netz auf Via %s" % keeper.netname
                    findings.append(Finding(
                        CAT_VIA_STACK, hole, keeper, True, True, detail))
                    scheduled.add(index)
                else:
                    findings.append(Finding(
                        CAT_VIA_STACK, hole, keeper, False, False,
                        "unterschiedliche Lagenbereiche – manuell klären"))

    return findings


def pad_stack_detail(target, keeper):
    """Hinweistext fuer zwei deckungsgleiche Bohrungs-Footprints."""
    footprint = target.footprint
    reference = footprint.GetReference() if footprint is not None else target.label
    parts = ["Footprint %s wird komplett entfernt" % reference]

    if footprint is not None:
        pad_count = len(list(footprint.Pads()))
        if pad_count > 1:
            parts[0] += " (%d Pads!)" % pad_count

    if target.netcode > 0 and keeper.netcode != target.netcode:
        parts.append("Netzanschluss %s entfällt" % (target.netname or "?"))

    parts.append("kommt bei »PCB aus Schaltplan aktualisieren« zurück")
    return " – ".join(parts)


def _analyse_mixed(holes, pairs, tolerance, scheduled):
    findings = []

    for i, j, distance in pairs:
        a, b = holes[i], holes[j]

        if a.kind == VIA and b.kind == VIA:
            if i in scheduled or j in scheduled:
                continue
            if distance + TANGENT_SLACK_NM < a.outer_radius + b.outer_radius:
                findings.append(Finding(
                    CAT_OVERLAP, b, a, False, False,
                    "Bohrungen überlappen um %s mm" % format_mm(
                        int(a.outer_radius + b.outer_radius - distance))))
            continue

        if a.kind == PAD and b.kind == PAD:
            larger, smaller = (a, b) if a.outer_radius >= b.outer_radius else (b, a)
            if distance <= tolerance or _contains(larger, smaller, tolerance):
                findings.append(Finding(
                    CAT_PAD_STACK, smaller, larger, smaller.footprint is not None,
                    False, pad_stack_detail(smaller, larger)))
            elif distance + TANGENT_SLACK_NM < a.outer_radius + b.outer_radius:
                findings.append(Finding(
                    CAT_OVERLAP, smaller, larger, False, False,
                    "Bohrungen überlappen um %s mm" % format_mm(
                        int(a.outer_radius + b.outer_radius - distance))))
            continue

        if a.kind == PAD:
            pad, via, via_index = a, b, j
        else:
            pad, via, via_index = b, a, i

        if via_index in scheduled:
            continue

        if _contains(pad, via, tolerance):
            if pad.npth:
                findings.append(Finding(
                    CAT_NET_CONFLICT, via, pad, False, False,
                    "Via liegt in einer NPTH-Bohrung (%s) – manuell klären" % pad.label))
            elif via.netcode not in (0, pad.netcode):
                findings.append(Finding(
                    CAT_NET_CONFLICT, via, pad, False, False,
                    "Via %s in Pad %s – manuell klären" % (
                        via.netname or "<kein Netz>", pad.netname or "<kein Netz>")))
            elif not _span_contains(pad.span, via.span):
                findings.append(Finding(
                    CAT_VIA_IN_PAD, via, pad, False, False,
                    "Lagenbereich des Vias reicht über das Pad hinaus"))
            else:
                findings.append(Finding(
                    CAT_VIA_IN_PAD, via, pad, True, True,
                    "Via liegt vollständig in der Bohrung von %s" % pad.label))
                scheduled.add(via_index)
        elif distance + TANGENT_SLACK_NM < pad.outer_radius + via.outer_radius:
            findings.append(Finding(
                CAT_OVERLAP, via, pad, False, False,
                "Via überlappt die Bohrung von %s" % pad.label))

    return findings


def analyse(board, position_tolerance):
    """Board untersuchen und alle Befunde sortiert zurueckgeben."""
    holes = collect_holes(board)

    stacked_vias = []
    remaining = []
    for i, j, distance in _neighbour_pairs(holes, position_tolerance):
        if (holes[i].kind == VIA and holes[j].kind == VIA
                and distance <= position_tolerance):
            stacked_vias.append((i, j))
        else:
            remaining.append((i, j, distance))

    scheduled = set()
    findings = _analyse_via_stacks(holes, stacked_vias, scheduled)
    findings.extend(_analyse_mixed(holes, remaining, position_tolerance, scheduled))

    findings.sort(key=lambda finding: (
        CATEGORY_ORDER.index(finding.category)
        if finding.category in CATEGORY_ORDER else len(CATEGORY_ORDER),
        finding.target.x,
        finding.target.y,
    ))
    return findings, len(holes)


# --- Anwenden --------------------------------------------------------------

def _uuid_of(item):
    try:
        return str(item.m_Uuid.AsString())
    except Exception:
        return "id:%d" % id(item)


def apply_findings(board, findings):
    """Ausgewaehlte Befunde umsetzen. Gibt (Vias, Footprints, uebersprungen)
    zurueck."""
    protected = set()
    for finding in findings:
        keeper = finding.keeper
        if keeper.kind == PAD and keeper.footprint is not None:
            protected.add(_uuid_of(keeper.footprint))
        else:
            protected.add(_uuid_of(keeper.item))

    vias = {}
    footprints = {}
    skipped = []

    for finding in findings:
        target = finding.target
        if target.kind == VIA:
            key = _uuid_of(target.item)
            if key in protected:
                skipped.append(finding)
                continue
            vias[key] = target.item
        else:
            footprint = target.footprint
            if footprint is None:
                skipped.append(finding)
                continue
            key = _uuid_of(footprint)
            if key in protected:
                skipped.append(finding)
                continue
            footprints[key] = footprint

    for via in vias.values():
        board.Remove(via)
    for footprint in footprints.values():
        board.Remove(footprint)

    board.BuildConnectivity()
    return len(vias), len(footprints), skipped
