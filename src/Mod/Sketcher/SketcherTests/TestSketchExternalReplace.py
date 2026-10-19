# SPDX-License-Identifier: LGPL-2.1-or-later

"""
App-level regression tests for SketchObject.attachExternal(): re-pointing the
reference of an existing external geometry to another object/subelement while
the constraints referencing the external GeoIds survive.
"""

import unittest

import FreeCAD
import Part
import Sketcher

App = FreeCAD


class TestSketchExternalReplace(unittest.TestCase):
    """Re-selecting the reference of a sketch's external geometry."""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("SketchExternalReplaceTest")

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("SketchExternalReplaceTest")

    def buildSketchOnBoxEdge(self):
        """Build two boxes and a sketch holding one external edge of Box1.

        The sketch carries a single internal line whose start point is
        coincident with the external edge's start point. Returns the sketch,
        the external GeoId and the linked subelement name, following the
        convention of TestSketcherSolver: the position of the added external
        geometry in the cached ExternalGeo list translates to the GeoId
        -index-1, so the first external geometry is -3.
        """
        box1 = self.Doc.addObject("Part::Box", "Box1")
        box1.Length = 10
        box1.Width = 20
        box1.Height = 30
        box2 = self.Doc.addObject("Part::Box", "Box2")
        box2.Length = 15
        box2.Width = 25
        box2.Height = 35
        box2.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.Doc.recompute()

        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")

        # Edges perpendicular to the sketch plane project to points, so look
        # for the first edge of Box1 that comes back as a line segment, like
        # TestSketcherSolver.buildSketchOnProjectedEdge does.
        external_sub = None
        for number in range(1, 13):
            sketch.addExternal("Box1", "Edge%d" % number)
            self.Doc.recompute()
            if isinstance(sketch.ExternalGeo[-1], Part.LineSegment):
                external_sub = "Edge%d" % number
                break
            sketch.delExternal(len(sketch.ExternalGeometry) - 1)
            self.Doc.recompute()
        self.assertIsNotNone(external_sub, "no box edge projected to a line segment")

        external_index = len(sketch.ExternalGeo) - 1
        external_geo_id = -external_index - 1

        line = sketch.addGeometry(
            Part.LineSegment(App.Vector(0, 0, 0), App.Vector(5, 0, 0)), False
        )
        sketch.addConstraint(Sketcher.Constraint("Coincident", line, 1, external_geo_id, 1))
        self.Doc.recompute()

        return sketch, external_geo_id, external_sub

    @staticmethod
    def constraintSignature(sketch):
        """Type and geometry references of every constraint in the sketch."""
        return [
            (constr.Type, constr.First, constr.FirstPos, constr.Second, constr.SecondPos)
            for constr in sketch.Constraints
        ]

    def assertExternalReplaced(self, sketch, external_sub, signature):
        """The reference points to Box2 and the constraints survived."""
        facade = Sketcher.ExternalGeometryFacade(sketch.ExternalGeo[-1])
        self.assertEqual(facade.Ref, "Box2." + external_sub)
        self.assertFalse(facade.testFlag("Missing"))

        links = sketch.ExternalGeometry
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][0].Name, "Box2")
        self.assertEqual(list(links[0][1]), [external_sub])

        # the point of the feature: same constraints, same external GeoIds
        self.assertEqual(self.constraintSignature(sketch), signature)
        self.assertEqual(sketch.solve(), 0)

    def testReplaceBrokenExternal(self):
        sketch, external_geo_id, external_sub = self.buildSketchOnBoxEdge()
        self.assertEqual(sketch.solve(), 0)
        signature = self.constraintSignature(sketch)
        external_geo_count = len(sketch.ExternalGeo)

        # Break the reference: the cached external geometry survives, flagged
        # as missing, and still carries the constraints that reference it.
        self.Doc.removeObject("Box1")
        try:
            self.Doc.recompute()
        except Exception:
            pass  # the recompute may reject the missing external reference

        facade = Sketcher.ExternalGeometryFacade(sketch.ExternalGeo[-1])
        self.assertEqual(facade.Ref, "Box1." + external_sub)
        self.assertTrue(facade.testFlag("Missing"))
        self.assertEqual(len(sketch.ExternalGeo), external_geo_count)
        self.assertEqual(self.constraintSignature(sketch), signature)

        # Heal it: re-point the surviving external geometry to the
        # corresponding edge of Box2, by name
        result = sketch.attachExternal(external_geo_id, "Box2", external_sub)
        self.assertGreaterEqual(result, 0)
        try:
            self.Doc.recompute()
        except Exception:
            pass  # tolerated for symmetry, must not be needed once healed

        self.assertExternalReplaced(sketch, external_sub, signature)

    def testReplaceHealthyExternal(self):
        sketch, external_geo_id, external_sub = self.buildSketchOnBoxEdge()
        self.assertEqual(sketch.solve(), 0)
        signature = self.constraintSignature(sketch)

        # Re-point the healthy reference directly to the corresponding edge of
        # Box2, passing the object itself and the GeoId as a list
        box2 = self.Doc.getObject("Box2")
        result = sketch.attachExternal([external_geo_id], box2, external_sub)
        self.assertGreaterEqual(result, 0)
        self.Doc.recompute()

        self.assertExternalReplaced(sketch, external_sub, signature)
