# -*- coding: utf-8 -*-
"""wxPython-Dialog zur Auswahl der zu entfernenden Bohrungen."""

from __future__ import annotations

import pcbnew
import wx

from . import core

COLUMNS = [
    ("Art", 210),
    ("Position X / Y", 150),
    ("Entfernen", 190),
    ("Behalten", 190),
    ("Netz", 110),
    ("Hinweis", 420),
]

GREY = wx.Colour(130, 130, 130)


class DedupDialog(wx.Dialog):

    def __init__(self, parent, board):
        wx.Dialog.__init__(
            self, parent, title="Bohrungen und Leiterbahnen deduplizieren",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=wx.Size(1180, 620))

        self.board = board
        self.findings = []
        self.hole_count = 0
        self.segment_count = 0
        self.removed_vias = 0
        self.removed_footprints = 0
        self.removed_tracks = 0
        self.merged_tracks = 0
        self.skipped = []
        # Objekte, die gerade im Editor hervorgehoben sind (Flags gesetzt).
        self.highlighted = []
        # CheckItem() loest EVT_LIST_ITEM_CHECKED sofort aus. Waehrend eines
        # Massen-Updates muss der Handler daher stillgelegt werden.
        self.updating = False

        outer = wx.BoxSizer(wx.VERTICAL)

        self.summary = wx.StaticText(self, label="")
        font = self.summary.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.summary.SetFont(font)
        outer.Add(self.summary, 0, wx.ALL, 10)

        options = wx.BoxSizer(wx.HORIZONTAL)
        options.Add(wx.StaticText(self, label="Positionstoleranz:"),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.tolerance = wx.TextCtrl(self, value="0.05", size=wx.Size(70, -1),
                                     style=wx.TE_PROCESS_ENTER)
        self.tolerance.SetToolTip(
            "Bohrungen, deren Mittelpunkte näher beieinander liegen, gelten "
            "als deckungsgleich. Bei Leiterbahnen: Endpunkte näher als das "
            "gelten als gleich.")
        options.Add(self.tolerance, 0, wx.ALIGN_CENTER_VERTICAL)
        options.Add(wx.StaticText(self, label="mm"),
                    0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 4)
        rescan = wx.Button(self, label="Neu suchen")
        options.Add(rescan, 0, wx.LEFT, 12)
        options.AddStretchSpacer()
        outer.Add(options, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        self.list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
        self.list.EnableCheckBoxes(True)
        for index, (title, width) in enumerate(COLUMNS):
            self.list.InsertColumn(index, title, width=width)
        outer.Add(self.list, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.select_safe = wx.Button(self, label="Nur sichere")
        self.select_all = wx.Button(self, label="Alle möglichen")
        self.select_none = wx.Button(self, label="Keine")
        self.swap = wx.Button(self, label="Richtung tauschen")
        self.swap.SetToolTip(
            "Bei markierter Zeile vertauschen, welches Objekt entfernt "
            "und welches behalten wird.")
        for button in (self.select_safe, self.select_all, self.select_none):
            actions.Add(button, 0, wx.RIGHT, 6)
        actions.Add(self.swap, 0, wx.LEFT, 18)
        actions.AddStretchSpacer()
        self.status = wx.StaticText(self, label="")
        actions.Add(self.status, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(actions, 0, wx.ALL | wx.EXPAND, 10)

        buttons = wx.StdDialogButtonSizer()
        self.ok = wx.Button(self, wx.ID_OK, "Auswahl entfernen")
        cancel = wx.Button(self, wx.ID_CANCEL, "Abbrechen")
        buttons.AddButton(self.ok)
        buttons.AddButton(cancel)
        buttons.Realize()
        outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizer(outer)
        self.ok.SetDefault()

        rescan.Bind(wx.EVT_BUTTON, self.on_rescan)
        self.tolerance.Bind(wx.EVT_TEXT_ENTER, self.on_rescan)
        self.select_safe.Bind(wx.EVT_BUTTON, lambda _: self.set_all("safe"))
        self.select_all.Bind(wx.EVT_BUTTON, lambda _: self.set_all("all"))
        self.select_none.Bind(wx.EVT_BUTTON, lambda _: self.set_all("none"))
        self.swap.Bind(wx.EVT_BUTTON, self.on_swap)
        self.list.Bind(wx.EVT_LIST_ITEM_CHECKED, self.on_check)
        self.list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self.on_check)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_select)
        self.Bind(wx.EVT_BUTTON, self.on_apply, id=wx.ID_OK)

        self.scan()
        self.CentreOnParent()

    # --- Suche -------------------------------------------------------------

    def tolerance_nm(self):
        try:
            value = float(self.tolerance.GetValue().replace(",", "."))
        except ValueError:
            value = 0.05
            self.tolerance.SetValue("0.05")
        return int(max(0.0, value) * pcbnew.PCB_IU_PER_MM)

    def on_rescan(self, _event):
        self.scan()

    def scan(self):
        busy = wx.BusyCursor()
        try:
            self.findings, self.hole_count, self.segment_count = core.analyse(
                self.board, self.tolerance_nm())
        finally:
            del busy
        self.fill_list()

    def fill_list(self):
        self.updating = True
        try:
            self.list.DeleteAllItems()
            for row, finding in enumerate(self.findings):
                self.list.InsertItem(row, finding.category_label)
                self.update_row(row)
                self.list.CheckItem(row, finding.safe)
                if not finding.removable:
                    self.list.SetItemTextColour(row, GREY)
        finally:
            self.updating = False
        self.update_summary()

    def update_row(self, row):
        finding = self.findings[row]
        self.list.SetItem(row, 0, finding.category_label)
        self.list.SetItem(row, 1, finding.target.position_text())
        self.list.SetItem(row, 2, finding.target.describe())
        self.list.SetItem(row, 3, finding.keeper.describe())
        self.list.SetItem(row, 4, finding.target.netname or "—")
        self.list.SetItem(row, 5, finding.detail)

    def checked_findings(self):
        rows = min(len(self.findings), self.list.GetItemCount())
        return [self.findings[row] for row in range(rows)
                if self.list.IsItemChecked(row)]

    def update_summary(self):
        removable = sum(1 for f in self.findings if f.removable)
        reports = len(self.findings) - removable
        self.summary.SetLabel(
            "%d Bohrungen und %d Leiterbahnsegmente geprüft · "
            "%d überzählige Objekte entfernbar · %d Befunde nur zur Kontrolle"
            % (self.hole_count, self.segment_count, removable, reports))
        self.summary.GetContainingSizer().Layout()
        self.update_status()

    def update_status(self):
        selected = len(self.checked_findings())
        self.status.SetLabel("%d von %d Zeilen ausgewählt"
                             % (selected, len(self.findings)))
        self.ok.Enable(selected > 0)
        self.status.GetContainingSizer().Layout()

    # --- Interaktion -------------------------------------------------------

    def on_check(self, event):
        if self.updating:
            return
        row = event.GetIndex()
        if not (0 <= row < len(self.findings)):
            return
        if (self.list.IsItemChecked(row)
                and not self.findings[row].removable):
            self.list.CheckItem(row, False)
            wx.MessageBox(
                "Dieser Befund lässt sich nicht automatisch auflösen und ist "
                "nur als Hinweis gelistet:\n\n%s" % self.findings[row].detail,
                "Nur zur Kontrolle", wx.OK | wx.ICON_INFORMATION, self)
        self.update_status()

    def set_all(self, mode):
        self.updating = True
        try:
            for row, finding in enumerate(self.findings):
                if mode == "none":
                    checked = False
                elif mode == "safe":
                    checked = finding.safe
                else:
                    checked = finding.removable
                self.list.CheckItem(row, checked)
        finally:
            self.updating = False
        self.update_status()

    def on_select(self, event):
        row = event.GetIndex()
        if 0 <= row < len(self.findings):
            self.highlight(self.findings[row])
        event.Skip()

    # --- Hervorhebung im Editor -------------------------------------------

    def highlight(self, finding):
        """Zu entfernendes Objekt selektieren (Auswahlfarbe), das bleibende
        aufhellen, Ansicht darauf zentrieren. Sonst sieht man bei
        deckungsgleichen Objekten nicht, welches gemeint ist."""
        self.clear_highlight()
        target, keeper = finding.target.item, finding.keeper.item
        try:
            target.SetSelected()
            self.highlighted.append(target)
            if keeper is not target:
                keeper.SetBrightened()
                self.highlighted.append(keeper)
        except Exception:
            pass
        try:
            pcbnew.FocusOnItem(target)
        except Exception:
            pass
        self._refresh()

    def clear_highlight(self):
        for item in self.highlighted:
            try:
                item.ClearSelected()
                item.ClearBrightened()
            except Exception:
                pass
        self.highlighted = []

    def _refresh(self):
        try:
            pcbnew.Refresh()
        except Exception:
            pass

    def Destroy(self):
        self.clear_highlight()
        self._refresh()
        return wx.Dialog.Destroy(self)

    def on_swap(self, _event):
        row = self.list.GetFirstSelected()
        if row < 0:
            wx.MessageBox("Bitte zuerst eine Zeile markieren.",
                          "Richtung tauschen", wx.OK | wx.ICON_INFORMATION, self)
            return
        finding = self.findings[row]
        if not finding.removable:
            return
        if finding.keeper.kind == core.PAD and finding.keeper.footprint is None:
            return
        finding.swap()
        self.update_row(row)

    def on_apply(self, _event):
        selection = self.checked_findings()
        if not selection:
            return

        footprints = sorted(set(
            finding.target.footprint.GetReference()
            for finding in selection
            if finding.target.kind == core.PAD
            and finding.target.footprint is not None))

        merged = len(set(
            id(finding.keeper.item) for finding in selection
            if getattr(finding, "merge", None) is not None))

        message = "%d Objekte werden entfernt." % len(selection)
        if merged:
            message += ("\n\n%d Leiterbahnen werden dabei auf die Gesamtlänge "
                        "ihrer überlappenden Segmente verlängert." % merged)
        if footprints:
            message += ("\n\nDarunter %d komplette Footprints: %s"
                        "\nDiese kommen bei »PCB aus Schaltplan aktualisieren« "
                        "zurück, falls sie im Schaltplan stehen."
                        % (len(footprints), ", ".join(footprints)))
        message += "\n\nRückgängig mit Strg+Z im PCB-Editor."

        confirm = wx.MessageBox(message, "Objekte entfernen",
                                wx.OK | wx.CANCEL | wx.ICON_QUESTION, self)
        if confirm != wx.OK:
            return

        self.clear_highlight()
        vias, removed_footprints, removed_tracks, merged_tracks, skipped = \
            core.apply_findings(self.board, selection)
        self.removed_vias = vias
        self.removed_footprints = removed_footprints
        self.removed_tracks = removed_tracks
        self.merged_tracks = merged_tracks
        self.skipped = skipped
        self.EndModal(wx.ID_OK)
