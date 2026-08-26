import unittest

from engram_overlay.scene3d import Camera, Vec3, box_faces, shade_color, sphere_faces, tapered_prism_faces


class Scene3DTests(unittest.TestCase):
    def test_vec3_math_and_cross_product(self) -> None:
        x_axis = Vec3(1.0, 0.0, 0.0)
        y_axis = Vec3(0.0, 1.0, 0.0)
        self.assertEqual(x_axis + y_axis, Vec3(1.0, 1.0, 0.0))
        self.assertEqual(x_axis.cross(y_axis), Vec3(0.0, 0.0, 1.0))
        self.assertAlmostEqual(Vec3(3.0, 4.0, 0.0).normalized().length, 1.0)

    def test_perspective_projection_shrinks_far_points(self) -> None:
        camera = Camera(100.0, 100.0, yaw=0.0, pitch=0.0, focal_length=500.0)
        near = camera.project(Vec3(100.0, 0.0, 0.0))
        far = camera.project(Vec3(100.0, 0.0, 100.0))
        self.assertGreater(near.x - 100.0, far.x - 100.0)
        self.assertGreater(near.scale, far.scale)

    def test_unproject_round_trips_screen_position_and_depth(self) -> None:
        camera = Camera(180.0, 190.0, yaw=-0.38, pitch=-0.10, focal_length=650.0)
        world = camera.unproject(246.0, 318.0, 57.0)
        projected = camera.project(world)
        self.assertAlmostEqual(projected.x, 246.0)
        self.assertAlmostEqual(projected.y, 318.0)
        self.assertAlmostEqual(projected.depth, 57.0)
        self.assertLess((camera.world_space(camera.camera_space(world)) - world).length, 1e-9)

    def test_procedural_meshes_have_expected_faces(self) -> None:
        prism = tapered_prism_faces(
            Vec3(0.0, 0.0, 0.0),
            Vec3(0.0, 100.0, 0.0),
            start_radius=10.0,
            end_radius=6.0,
            color="#ffffff",
        )
        self.assertEqual(len(prism), 6)
        self.assertTrue(all(len(face.vertices) == 4 for face in prism))
        self.assertEqual(len(box_faces(Vec3(0.0, 0.0, 0.0), Vec3(10.0, 20.0, 30.0), color="#ffffff")), 6)
        self.assertEqual(len(sphere_faces(Vec3(0.0, 0.0, 0.0), 10.0, color="#ffffff")), 50)

    def test_shading_clamps_rgb_channels(self) -> None:
        self.assertEqual(shade_color("#808080", 0.5), "#404040")
        self.assertEqual(shade_color("#ffffff", 1.4), "#ffffff")


if __name__ == "__main__":
    unittest.main()
