# -*- coding: utf-8 -*-
"""ActionPlugin-Einbindung: Werkzeugleisten-Knopf im PCB-Editor."""

from __future__ import annotations

import os

import pcbnew
import wx

from .dialog import DedupDialog


class DedupPlugin(pcbnew.ActionPlugin):

    def defaults(self):
        self.name = "Deduplizieren"
        self.category = "Modify PCB"
        self.description = (
            "Findet deckungsgleiche Bohrungen (gestapelte Vias, Vias in "
            "Pad-Bohrungen, doppelte Bohrungs-Footprints) sowie doppelte und "
            "überlappende Leiterbahnsegmente und entfernt die überzähligen."
        )
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        board = pcbnew.GetBoard()
        parent = wx.GetActiveWindow()

        dialog = DedupDialog(parent, board)
        try:
            if not dialog.findings:
                wx.MessageBox(
                    "Keine deckungsgleichen Bohrungen und keine doppelten "
                    "Leiterbahnen gefunden.\n\n"
                    "%d Bohrungen und %d Leiterbahnsegmente geprüft."
                    % (dialog.hole_count, dialog.segment_count),
                    self.name, wx.OK | wx.ICON_INFORMATION, parent)
                return

            if dialog.ShowModal() != wx.ID_OK:
                return

            pcbnew.Refresh()

            parts = []
            if dialog.removed_vias:
                parts.append("%d Vias" % dialog.removed_vias)
            if dialog.removed_footprints:
                parts.append("%d Footprints" % dialog.removed_footprints)
            if dialog.removed_tracks:
                parts.append("%d Leiterbahnsegmente" % dialog.removed_tracks)
            summary = ", ".join(parts) if parts else "nichts"

            message = (summary[0].upper() + summary[1:] + " entfernt.") if parts else "Nichts entfernt."
            if dialog.merged_tracks:
                message += ("\n%d Leiterbahnen auf die Gesamtlänge ihrer "
                            "Segmente verlängert." % dialog.merged_tracks)
            if getattr(dialog, "skipped", None):
                message += ("\n\n%d Zeilen übersprungen, weil das Objekt "
                            "anderswo als »behalten« markiert war."
                            % len(dialog.skipped))
            message += "\n\nRückgängig mit Strg+Z."

            wx.MessageBox(message, self.name, wx.OK | wx.ICON_INFORMATION, parent)
        finally:
            dialog.Destroy()
