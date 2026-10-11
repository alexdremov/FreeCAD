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

"""Regression tests for sub-object shape resolution of cyclic hierarchies.

Part::_getTopoShape() builds shapes by recursing through the sub-object
hierarchy (getSubObjects()/getSubObject(), including group extensions and
binder redirection). That hierarchy is not guaranteed acyclic: a group
containing a link to itself, or a SubShapeBinder bound relative to its own
containing group, makes sub-object resolution loop back onto itself - and
unlike the dependency graph nothing rejects such a cycle, so the recursion
used to consume the whole stack and kill the process.

_getTopoShape() now caps its recursion depth and returns a null shape for
the runaway branch, so these tests pin down both sides of that behavior:
cyclic constructs must degrade instead of crashing, while legitimate
(nested) group resolution must stay completely intact - compound
construction re-enters the parent object once per child entry, which is why
a depth cap is used rather than a cycle check.
"""

import unittest

import FreeCAD as App
import Part


class TestTopoShapeCyclicReference(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestTopoShapeCyclicReference")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _addBox(self, name):
        box = self.doc.addObject("Part::Box", name)
        box.Length = 10
        box.Width = 10
        box.Height = 10
        return box

    def _addCyclicBinder(self):
        """Binder bound relative to its own containing group: resolving the
        binder's shape recurses group -> binder -> group -> ..."""
        group = self.doc.addObject("App::Part", "Group")
        box = self._addBox("Box")
        group.addObject(box)
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Binder")
        group.addObject(binder)
        binder.Support = [(box, ("",))]
        binder.Relative = True
        return group, box, binder

    def testSelfReferentialLinkGroupDegradesInsteadOfCrashing(self):
        # a group containing a link to itself is a pure sub-object-resolution
        # cycle (invisible to the dependency graph): resolving its shape used
        # to recurse until the stack overflowed and killed the process
        group = self.doc.addObject("App::Part", "Group")
        box = self._addBox("Box")
        group.addObject(box)
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = group
        group.addObject(link)

        shape = Part.getShape(group)
        # the runaway branch is cut off; whatever the traversal collected
        # before the cut is returned (or nothing at all), but the process
        # must survive and the result must not be corrupt
        self.assertTrue(shape.isNull() or shape.isValid())

    def testCyclicRelativeBinderRecomputeCompletes(self):
        # used to recurse ~4500 frames deep and die with a stack overflow
        group, box, binder = self._addCyclicBinder()
        self.doc.recompute()

        # the group compound must still resolve; the binder branch stays
        # finite (it folds its bound content once, it does not loop)
        shape = Part.getShape(group)
        self.assertFalse(shape.isNull())
        self.assertAlmostEqual(shape.Volume, 2000.0, places=6)

    def testNonCyclicBinderInGroupResolves(self):
        group = self.doc.addObject("App::Part", "Group")
        box = self._addBox("Box")
        group.addObject(box)
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Binder")
        group.addObject(binder)
        binder.Support = [(box, ("",))]
        binder.Relative = False
        self.doc.recompute()

        shape = Part.getShape(binder)
        self.assertFalse(shape.isNull())
        self.assertAlmostEqual(shape.Volume, 1000.0, places=6)

    def testNestedGroupsResolveCompletely(self):
        # depth-capping must not cut legitimate resolution: compound
        # construction re-enters the parent object per child entry, so the
        # recursion level grows with grouping depth
        doc = self.doc
        innermost = doc.addObject("App::Part", "Level1")
        box = self._addBox("Box")
        innermost.addObject(box)
        parent = innermost
        for i in range(2, 6):
            outer = doc.addObject("App::Part", f"Level{i}")
            outer.addObject(parent)
            parent = outer
        self.doc.recompute()

        shape = Part.getShape(parent)
        self.assertFalse(shape.isNull())
        self.assertAlmostEqual(shape.Volume, 1000.0, places=6)
        self.assertAlmostEqual(shape.BoundBox.XMin, 0.0, places=6)
        self.assertAlmostEqual(shape.BoundBox.XMax, 10.0, places=6)
