import unittest
from pathlib import Path

from engram_overlay.overlays.robot_arm_3d_v2 import (
    ATLAS_REGIONS,
    MATERIAL_BLACK,
    MATERIAL_CABLE,
    MATERIAL_TECH,
    MATERIAL_WHITE,
    atlas_sample_coordinate,
    bilinear_point,
    v2_surface_faces,
)
from engram_overlay.registry import OVERLAYS, overlay_ids
from engram_overlay.scene3d import Vec3


class RobotArm3DV2Tests(unittest.TestCase):
    def test_registry_exposes_textured_v2_independently(self) -> None:
        self.assertIn("robot-arm-3d-v2", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm-3d-v2"].backend, "tk-textured-software-3d")
        self.assertEqual(OVERLAYS["robot-arm-3d"].backend, "tk-software-3d")

    def test_material_quadrants_do_not_cross_atlas_seams(self) -> None:
        self.assertEqual(atlas_sample_coordinate(MATERIAL_BLACK, 0.0, 0.0, 100, 100), (0, 0))
        self.assertEqual(atlas_sample_coordinate(MATERIAL_BLACK, 1.0, 1.0, 100, 100), (49, 49))
        self.assertEqual(atlas_sample_coordinate(MATERIAL_WHITE, 0.0, 0.0, 100, 100), (50, 0))
        self.assertEqual(atlas_sample_coordinate(MATERIAL_CABLE, 1.0, 1.0, 100, 100), (49, 99))
        self.assertEqual(atlas_sample_coordinate(MATERIAL_TECH, 1.0, 1.0, 100, 100), (99, 99))

    def test_bilinear_projection_preserves_quad_corners_and_center(self) -> None:
        corners = ((0.0, 0.0), (10.0, 0.0), (12.0, 8.0), (-2.0, 8.0))
        self.assertEqual(bilinear_point(corners, 0.0, 0.0), corners[0])
        self.assertEqual(bilinear_point(corners, 1.0, 1.0), corners[2])
        self.assertEqual(bilinear_point(corners, 0.5, 0.5), (5.0, 4.0))

    def test_v2_mesh_uses_all_generated_material_regions(self) -> None:
        base = Vec3(0.0, -138.0, 0.0)
        joints = [base, Vec3(45.0, -65.0, 20.0), Vec3(-30.0, 25.0, -12.0), Vec3(20.0, 105.0, 8.0)]
        faces = v2_surface_faces(base, joints)
        self.assertGreater(len(faces), 250)
        self.assertTrue(set(ATLAS_REGIONS).issubset({face.color for face in faces}))

    def test_generated_texture_is_packaged_next_to_renderer(self) -> None:
        asset = (
            Path(__file__).parents[1]
            / "src"
            / "engram_overlay"
            / "overlays"
            / "assets"
            / "robot_arm_3d_v2"
            / "industrial-material-atlas.png"
        )
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
