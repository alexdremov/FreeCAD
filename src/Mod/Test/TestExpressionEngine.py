# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
#   Copyright (c) 2026 Alex Dremov <dremov.me@gmail.com>
#
#   This file is part of the FreeCAD CAx development system.
#
#   This library is free software; you can redistribute it and/or
#   modify it under the terms of the GNU Lesser General Public License
#   as published by the Free Software Foundation; either version 2.1 of
#   the License, or (at your option) any later version.
#
#   This library is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#   Lesser General Public License for more details.
#
#   You should have received a copy of the GNU Lesser General Public
#   License along with this library; see the file COPYING.LIB. If not,
#   write to the Free Software Foundation, Inc., 59 Temple Place,
#   Suite 330, Boston, MA 02111-1307, USA
# ***************************************************************************

"""Regression tests for expression binding preservation across document restore.

PropertyExpressionEngine used to silently drop bindings that could not be
re-resolved at document load (missing target property, shifted constraint
index, restore-time cyclic check, ...). The dropped binding survived only in
the file and the next save persisted the stripped state, so any broken
intermediate state permanently converted the driven properties into plain
static values, and repeated load/save cycles ratcheted the loss.

Bindings that fail to restore are now quarantined instead: kept verbatim in
memory, written back unchanged on save (so restoration is retried on every
load), superseded by an explicit bind/unbind, and healed automatically once
their target reappears.

The missing-target state is simulated by renaming the target property
declaration inside the saved Document.xml, which is exactly the destructive
case a broken intermediate state produces.
"""

import os
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part


def _expressionPaths(xml):
    """Return the path= attributes of all <Expression> elements in the XML."""
    return re.findall(r'<Expression path="([^"]*)"', xml)


class ExpressionRestoreQuarantineCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freecad-expression-restore-")
        self.path = os.path.join(self.tmpdir, "TestExpressionEngine.FCStd")

    def tearDown(self):
        for name in list(App.listDocuments()):
            App.closeDocument(name)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _buildDocument(self):
        doc = App.newDocument("TestExpressionEngine")
        calc = doc.addObject("App::VarSet", "Calc")
        calc.addProperty("App::PropertyLength", "base", "P", "base parameter")
        calc.base = 5
        driven = doc.addObject("App::VarSet", "Driven")
        driven.addProperty("App::PropertyLength", "len1", "P", "driven parameter")
        driven.setExpression("len1", "Calc.base * 2")
        box = doc.addObject("Part::Box", "Box")
        box.setExpression("Height", "Driven.len1 * 2")
        doc.recompute()
        self.assertAlmostEqual(driven.len1.Value, 10)
        self.assertAlmostEqual(box.Height.Value, 20)
        return doc

    def _save(self, doc):
        doc.saveAs(self.path)

    def _open(self):
        return App.openDocument(self.path)

    def _rewriteDocumentXml(self, transform):
        """Rewrite Document.xml inside the saved file (simulates a broken
        intermediate state produced outside of FreeCAD)."""
        tmp = self.path + ".tmp"
        with zipfile.ZipFile(self.path) as zin, zipfile.ZipFile(
            tmp, "w", zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "Document.xml":
                    data = transform(data.decode()).encode()
                zout.writestr(item, data)
        shutil.move(tmp, self.path)

    def _openWithMissingTarget(self):
        """Save a healthy document, then rename the driven property in the
        saved XML so its binding cannot be resolved at load."""
        doc = self._buildDocument()
        self._save(doc)
        App.closeDocument(doc.Name)
        self._rewriteDocumentXml(lambda xml: xml.replace('name="len1"', 'name="len1x"'))
        return self._open()

    def testHealthyRoundTripKeepsBindingsLive(self):
        doc = self._buildDocument()
        self._save(doc)
        App.closeDocument(doc.Name)

        doc = self._open()
        driven = doc.getObject("Driven")
        box = doc.getObject("Box")
        self.assertEqual(list(driven.ExpressionEngine), [("len1", "Calc.base * 2")])
        self.assertEqual(list(box.ExpressionEngine), [("Height", "Driven.len1 * 2")])
        self.assertAlmostEqual(driven.len1.Value, 10)
        self.assertAlmostEqual(box.Height.Value, 20)

    def testFailedRestoreIsQuarantinedAndPreservedOnSave(self):
        doc = self._openWithMissingTarget()
        driven = doc.getObject("Driven")
        box = doc.getObject("Box")

        # the broken binding is not live (the property is driven no longer),
        # but it must not have been silently discarded either: a later save
        # has to write it back verbatim so nothing is lost
        self.assertEqual(list(driven.ExpressionEngine), [])
        self.assertEqual(list(box.ExpressionEngine), [("Height", "Driven.len1 * 2")])
        self.assertAlmostEqual(getattr(driven, "len1x").Value, 10)

        doc.save()
        App.closeDocument(doc.Name)

        xml = zipfile.ZipFile(self.path).read("Document.xml").decode()
        self.assertEqual(sorted(_expressionPaths(xml)), ["Height", "len1"])
        self.assertIn("Calc.base * 2", xml)

    def testQuarantinedBindingHealsWhenTargetReappears(self):
        doc = self._openWithMissingTarget()
        doc.save()
        App.closeDocument(doc.Name)

        # repair the broken state in the file: the quarantined binding must
        # come back to life on the next load, with no user action
        self._rewriteDocumentXml(lambda xml: xml.replace('name="len1x"', 'name="len1"'))
        doc = self._open()
        driven = doc.getObject("Driven")
        self.assertEqual(list(driven.ExpressionEngine), [("len1", "Calc.base * 2")])
        self.assertAlmostEqual(driven.len1.Value, 10)

    def testExplicitUnbindSupersedesQuarantine(self):
        doc = self._openWithMissingTarget()
        box = doc.getObject("Box")

        # an explicit unbind is user intent: the quarantined copy of the same
        # binding must not resurrect it on the next save. Height is the
        # property that still exists (its expression references the missing
        # len1), so unbinding it is the realistic user action here.
        box.setExpression("Height", None)
        doc.save()
        App.closeDocument(doc.Name)

        xml = zipfile.ZipFile(self.path).read("Document.xml").decode()
        self.assertEqual(sorted(_expressionPaths(xml)), ["len1"])
