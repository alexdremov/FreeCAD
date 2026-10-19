# SPDX-License-Identifier: LGPL-2.1-or-later

"""GUI regression tests for Sketcher_ReplaceExternal: re-selecting the
reference of a sketch's external geometry by picking the new element in the
3D view while the replacement handler is armed.

The App-level counterpart is SketcherTests/TestSketchExternalReplace.py,
which covers SketchObject.attachExternal() itself. This file exercises the
command-level flow: selecting an ExternalEdge subelement, the replacement
handler consuming a scripted 3D-view pick, and the constraint referencing
the external geometry surviving the replacement.
"""

import unittest

import FreeCAD as App
import Part
import Sketcher
from SketcherTests.GuiTestCase import FreeCADGui as Gui, SketcherGuiTestCase

try:
    import FreeCADGui

    GUI_AVAILABLE = FreeCADGui.getMainWindow() is not None
except (ImportError, AttributeError):
    GUI_AVAILABLE = False


class TestExternalReplace(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()

        Gui.activateWorkbench("SketcherWorkbench")
        self.doc = App.newDocument("ExternalReplace")

        box1 = self.doc.addObject("Part::Box", "Box1")
        box1.Length, box1.Width, box1.Height = 10, 20, 30
        box2 = self.doc.addObject("Part::Box", "Box2")
        box2.Length, box2.Width, box2.Height = 15, 25, 35
        box2.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.doc.recompute()

        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")

        # Look for the first edge of Box1 that comes back as a line segment,
        # like TestSketchExternalReplace.buildSketchOnBoxEdge does
        self.external_sub = None
        for number in range(1, 13):
            sketch.addExternal("Box1", "Edge%d" % number)
            self.doc.recompute()
            if isinstance(sketch.ExternalGeo[-1], Part.LineSegment):
                self.external_sub = "Edge%d" % number
                break
            sketch.delExternal(len(sketch.ExternalGeometry) - 1)
            self.doc.recompute()
        self.assertIsNotNone(
            self.external_sub, "no box edge projected to a line segment"
        )

        self.external_geo_id = -len(sketch.ExternalGeo)

        line = sketch.addGeometry(
            Part.LineSegment(App.Vector(0, 0, 0), App.Vector(5, 0, 0)), False
        )
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", line, 1, self.external_geo_id, 1)
        )
        self.doc.recompute()

        self.sketch = sketch
        self.box2 = box2

        Gui.activeDocument().setEdit(sketch.Name)
        self.flush_gui(50)
        self.view = Gui.activeDocument().activeView()
        self.view.viewTop()
        self.flush_gui(50)
        self.view.fitAll()
        self.flush_gui(150)
        self.viewport = self.view.graphicsView().viewport()

    def tearDown(self):
        super().tearDown()

    def constraint_signature(self):
        """Type and geometry references of every constraint in the sketch."""
        return [
            (
                constr.Type,
                constr.First,
                constr.FirstPos,
                constr.Second,
                constr.SecondPos,
            )
            for constr in self.sketch.Constraints
        ]

    def arm_replace_command(self):
        """Select the sketch's only external geometry and start the replace tool."""
        # the subname numbering starts at "ExternalEdge1" for GeoId -3
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.sketch, "ExternalEdge1")
        Gui.runCommand("Sketcher_ReplaceExternal", 0)
        self.flush_gui(150)

    def box_edge_pick_point(self, box, sub):
        """Sketch-plane point projecting onto the given edge in the top view."""
        edge = box.Shape.Edges[int(sub[4:]) - 1]
        center = edge.CenterOfMass
        return App.Vector(center.x, center.y, 0)

    def pick_box2_reference(self):
        point = self.box_edge_pick_point(self.box2, self.external_sub)
        pos = self.viewport_to_qpoint(
            self.view, self.viewport, self.view.getPointOnScreen(point)
        )
        self.move(self.viewport, pos)
        self.flush_gui(50)
        self.click(self.viewport, pos)
        self.flush_gui(150)

    def assert_external_replaced(self, signature):
        """The reference points to Box2 and the constraints survived."""
        # the point of the feature: same constraints, same external GeoIds
        self.assertEqual(self.constraint_signature(), signature)
        self.assertEqual(self.sketch.solve(), 0)

        facade = Sketcher.ExternalGeometryFacade(self.sketch.ExternalGeo[-1])
        self.assertFalse(facade.testFlag("Missing"))

        # the scripted click resolves to whatever element the viewer picks at
        # the projected edge position (an edge, or the box face covering it);
        # the exact element identity is covered by the App-level tests
        links = self.sketch.ExternalGeometry
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][0].Name, "Box2")
        self.assertTrue(facade.Ref.startswith("Box2."), facade.Ref)
        self.assertEqual(facade.Ref, "Box2." + links[0][1][0])

    @unittest.skipIf(not GUI_AVAILABLE, "GUI not available")
    def testReplaceBrokenExternalReference(self):
        """A missing-reference external geometry is re-linked by picking the
        new element, keeping the constraints that reference it."""
        self.assertEqual(self.sketch.solve(), 0)
        signature = self.constraint_signature()

        # Break the reference: the cached external geometry survives, flagged
        # as missing, and still carries the constraints that reference it.
        self.doc.removeObject("Box1")
        try:
            self.doc.recompute()
        except Exception:
            pass  # the recompute may reject the missing external reference

        facade = Sketcher.ExternalGeometryFacade(self.sketch.ExternalGeo[-1])
        self.assertEqual(facade.Ref, "Box1." + self.external_sub)
        self.assertTrue(facade.testFlag("Missing"))

        self.arm_replace_command()
        self.pick_box2_reference()

        self.assert_external_replaced(signature)

    @unittest.skipIf(not GUI_AVAILABLE, "GUI not available")
    def testReplaceHealthyExternalReference(self):
        """A healthy external geometry is re-pointed by picking the new
        element, keeping the constraints that reference it."""
        self.assertEqual(self.sketch.solve(), 0)
        signature = self.constraint_signature()

        self.arm_replace_command()
        self.pick_box2_reference()

        self.assert_external_replaced(signature)
