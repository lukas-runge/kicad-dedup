# -*- coding: utf-8 -*-
"""Erkennung doppelter und ueberlappender Leiterbahnsegmente.

Sucht gerade Segmente desselben Netzes auf derselben Lage, die auf einer
Linie liegen und sich ueberdecken. Drei Faelle:

* exakt doppelt            – gleiche Endpunkte, gleiche Breite
* enthalten                – ein Segment liegt komplett in einem anderen
* teilweise ueberlappend   – gleiche Breite: zu einem Segment verschmelzen;
                             verschiedene Breite: nur melden

Wie `core.py` ohne wxPython, damit es sich headless testen laesst.
"""

from __future__ import annotations

import math
from collections import defaultdict

import pcbnew

TRACK = "track"

CAT_TRACK_DUP = "track_dup"
CAT_TRACK_INSIDE = "track_inside"
CAT_TRACK_MERGE = "track_merge"
CAT_TRACK_REPORT = "track_report"

CATEGORY_LABELS = {
    CAT_TRACK_DUP: "Leiterbahn exakt doppelt",
    CAT_TRACK_INSIDE: "Leiterbahn in Leiterbahn enthalten",
    CAT_TRACK_MERGE: "Leiterbahnen überlappen – verschmelzen",
    CAT_TRACK_REPORT: "Leiterbahnen überlappen – verschiedene Breite",
}

CATEGORY_ORDER = [
    CAT_TRACK_DUP,
    CAT_TRACK_INSIDE,
    CAT_TRACK_MERGE,
    CAT_TRACK_REPORT,
]

# Senkrechter Abstand, bis zu dem zwei Segmente als "auf einer Linie" gelten.
# Rundungsreste des Routers liegen im Nanometerbereich, 2 µm ist grosszuegig
# und trotzdem weit unter jeder realen Leiterbahnbreite.
LINE_TOL_NM = 2000

# Ueberdeckung entlang der Linie, ab der ein Paar als ueberlappend zaehlt.
# Segmente, die sich nur an einem Punkt beruehren, sind normale Ketten.
OVERLAP_MIN_NM = 1000

# Endpunkte naeher als das gelten als identisch ("exakt doppelt").
EXACT_TOL_NM = 10000


def to_mm(value):
    return value / float(pcbnew.PCB_IU_PER_MM)


def format_mm(value, digits=3):
    return ("%.*f" % (digits, to_mm(value))).rstrip("0").rstrip(".") or "0"


class Segment(object):
    """Ein gerades Leiterbahnsegment. Gleiche Schnittstelle wie `core.Hole`,
    damit Dialog und `apply_findings` beide Arten gleich behandeln koennen."""

    __slots__ = (
        "kind", "item", "sx", "sy", "ex", "ey", "width", "layer", "layer_name",
        "netcode", "netname", "label", "footprint", "span", "npth",
    )

    def __init__(self, item, layer_name):
        self.kind = TRACK
        self.item = item
        start, end = item.GetStart(), item.GetEnd()
        self.sx, self.sy = start.x, start.y
        self.ex, self.ey = end.x, end.y
        self.width = item.GetWidth()
        self.layer = item.GetLayer()
        self.layer_name = layer_name
        self.netcode = item.GetNetCode()
        self.netname = item.GetNetname()
        self.label = "Leiterbahn %s" % (self.netname or "<kein Netz>")
        self.footprint = None
        self.span = None
        self.npth = False

    # Schnittstelle wie core.Hole
    @property
    def x(self):
        return (self.sx + self.ex) // 2

    @property
    def y(self):
        return (self.sy + self.ey) // 2

    @property
    def length(self):
        return math.hypot(self.ex - self.sx, self.ey - self.sy)

    def position_text(self):
        return "%s / %s" % (format_mm(self.x), format_mm(self.y))

    def describe(self):
        return "%s %s, %s mm lang, %s mm breit" % (
            self.label, self.layer_name, format_mm(self.length, 2),
            format_mm(self.width, 2))


# --- Sammeln ---------------------------------------------------------------

def collect_segments(board):
    segments = []
    for track in board.GetTracks():
        if track.GetClass() != "PCB_TRACK":
            continue  # Vias und Boegen bleiben aussen vor
        seg = Segment(track, board.GetLayerName(track.GetLayer()))
        if seg.length < OVERLAP_MIN_NM:
            continue  # Null-Segmente raeumt KiCads eigener Cleanup
        segments.append(seg)
    return segments


# --- Geometrie -------------------------------------------------------------

def _project(base, px, py):
    """Punkt auf die Linie von `base` projizieren.
    Liefert (Position entlang der Linie in nm, senkrechter Abstand in nm)."""
    dx, dy = base.ex - base.sx, base.ey - base.sy
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    rx, ry = px - base.sx, py - base.sy
    return rx * ux + ry * uy, abs(rx * uy - ry * ux)


def _overlap(base, other):
    """Ueberdeckung von `other` entlang `base`, falls beide auf einer Linie
    liegen. Liefert (u_min, u_max, ueberdeckung) oder None."""
    u1, d1 = _project(base, other.sx, other.sy)
    u2, d2 = _project(base, other.ex, other.ey)
    if d1 > LINE_TOL_NM or d2 > LINE_TOL_NM:
        return None
    lo, hi = min(u1, u2), max(u1, u2)
    overlap = min(hi, base.length) - max(lo, 0.0)
    if overlap < OVERLAP_MIN_NM:
        return None
    return lo, hi, overlap


def _point_on(base, u):
    dx, dy = base.ex - base.sx, base.ey - base.sy
    length = math.hypot(dx, dy)
    return (int(round(base.sx + dx / length * u)),
            int(round(base.sy + dy / length * u)))


# --- Analyse ---------------------------------------------------------------

def _candidate_pairs(segments):
    """Paare gleicher Lage und gleichen Netzes, deren Rechtecke sich beruehren."""
    groups = defaultdict(list)
    for index, seg in enumerate(segments):
        groups[(seg.netcode, seg.layer)].append(index)

    for members in groups.values():
        boxes = []
        for index in members:
            seg = segments[index]
            pad = seg.width + LINE_TOL_NM
            boxes.append((min(seg.sx, seg.ex) - pad, max(seg.sx, seg.ex) + pad,
                          min(seg.sy, seg.ey) - pad, max(seg.sy, seg.ey) + pad))
        for a in range(len(members)):
            ax0, ax1, ay0, ay1 = boxes[a]
            for b in range(a + 1, len(members)):
                bx0, bx1, by0, by1 = boxes[b]
                if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                    continue
                yield members[a], members[b]


def analyse_tracks(segments, position_tolerance, finding_class):
    """Befunde fuer doppelte/ueberlappende Segmente.

    `finding_class` ist `core.Finding`; so bleibt dieses Modul von core.py
    entkoppelt. Liefert (Befunde, Anzahl der Verschmelzungen)."""
    parent = {}

    def find(index):
        parent.setdefault(index, index)
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    findings = []

    for i, j in _candidate_pairs(segments):
        a, b = segments[i], segments[j]
        base, other, bi, oi = (a, b, i, j) if a.length >= b.length else (b, a, j, i)
        ov = _overlap(base, other)
        if ov is None:
            continue
        lo, hi, overlap = ov

        if base.width == other.width:
            union(bi, oi)
            continue

        # Verschiedene Breiten: nur das schmalere darf entfallen, und nur,
        # wenn es komplett im breiteren liegt.
        narrow, wide = (a, b) if a.width < b.width else (b, a)
        ovn = _overlap(wide, narrow)
        if ovn is not None:
            lo_n, hi_n, _ = ovn
            if lo_n >= -position_tolerance and hi_n <= wide.length + position_tolerance:
                findings.append(finding_class(
                    CAT_TRACK_INSIDE, narrow, wide, True, True,
                    "liegt komplett in der breiteren Leiterbahn (%s mm in %s mm)"
                    % (format_mm(narrow.width, 2), format_mm(wide.width, 2))))
                continue
        findings.append(finding_class(
            CAT_TRACK_REPORT, other, base, False, False,
            "überlappen sich auf %s mm, Breiten %s und %s mm – manuell klären"
            % (format_mm(int(overlap), 2), format_mm(a.width, 2), format_mm(b.width, 2))))

    clusters = defaultdict(list)
    for index in list(parent):
        clusters[find(index)].append(index)

    merges = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        keeper = segments[max(members, key=lambda k: (segments[k].length, -k))]
        hull_lo, hull_hi = 0.0, keeper.length
        rows = []
        for index in members:
            seg = segments[index]
            if seg is keeper:
                continue
            u1, _ = _project(keeper, seg.sx, seg.sy)
            u2, _ = _project(keeper, seg.ex, seg.ey)
            lo, hi = min(u1, u2), max(u1, u2)
            hull_lo, hull_hi = min(hull_lo, lo), max(hull_hi, hi)
            exact = (abs(lo) <= EXACT_TOL_NM
                     and abs(hi - keeper.length) <= EXACT_TOL_NM)
            inside = lo >= -position_tolerance and hi <= keeper.length + position_tolerance
            rows.append((seg, exact, inside))

        extend = hull_lo < -position_tolerance or hull_hi > keeper.length + position_tolerance
        merge = None
        if extend:
            merge = (_point_on(keeper, hull_lo), _point_on(keeper, hull_hi))
            merges += 1

        for seg, exact, inside in rows:
            if exact:
                category, detail = CAT_TRACK_DUP, "identische Endpunkte, %d-fach vorhanden" % len(members)
            elif inside and not extend:
                category, detail = CAT_TRACK_INSIDE, "liegt komplett in der längeren Leiterbahn"
            else:
                category = CAT_TRACK_MERGE
                detail = "wird mit %d Segment(en) zu einem Segment %s → %s mm verschmolzen" % (
                    len(members) - 1,
                    "%s/%s" % (format_mm(merge[0][0], 2), format_mm(merge[0][1], 2)),
                    "%s/%s" % (format_mm(merge[1][0], 2), format_mm(merge[1][1], 2)))
            finding = finding_class(category, seg, keeper, True, True, detail)
            finding.merge = merge
            findings.append(finding)

    return findings, merges


# --- Anwenden --------------------------------------------------------------

def apply_track_findings(board, findings, protected, uuid_of):
    """Leiterbahn-Befunde umsetzen. Gibt (entfernt, verschmolzen, uebersprungen)."""
    removals = {}
    merges = {}
    skipped = []

    for finding in findings:
        key = uuid_of(finding.target.item)
        if key in protected:
            skipped.append(finding)
            continue
        removals[key] = finding.target.item
        merge = getattr(finding, "merge", None)
        if merge is not None:
            merges[uuid_of(finding.keeper.item)] = (finding.keeper.item, merge)

    for track, (start, end) in merges.values():
        track.SetStart(pcbnew.VECTOR2I(start[0], start[1]))
        track.SetEnd(pcbnew.VECTOR2I(end[0], end[1]))

    for track in removals.values():
        board.Remove(track)

    return len(removals), len(merges), skipped
