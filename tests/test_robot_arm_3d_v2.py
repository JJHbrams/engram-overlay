import unittest
from pathlib import Path

from PIL import Image

from engram_overlay.overlays.robot_arm_3d_v2 import (
    RobotArm3DV2View,
    joint_point_texture_face,
    pod_axis,
    pod_attachment_point,
    pod_faces_and_expression_plane,
    render_expression_layers,
    render_expression_texture,
    render_eye_emission,
    v2_surface_faces,
    visual_link_joints,
)
from engram_overlay.registry import OVERLAYS, overlay_ids
from engram_overlay.scene3d import Camera, ProjectedPoint, Vec3
from engram_overlay.software_uv import (
    TexturedFace3D,
    UVTextureAtlas,
    atlas_cell_uv,
    rasterize_textured_face,
    textured_prism_faces,
)


class RobotArm3DV2Tests(unittest.TestCase):
    def test_registry_exposes_textured_v2_independently(self) -> None:
        self.assertIn("robot-arm-3d-v2", overlay_ids())
        self.assertEqual(OVERLAYS["robot-arm-3d-v2"].backend, "tk-textured-software-3d")
        self.assertEqual(OVERLAYS["robot-arm-3d"].backend, "tk-software-3d")

    def test_uv_cells_are_padded_and_prism_faces_keep_complete_uvs(self) -> None:
        uvs = atlas_cell_uv(2, 1)
        self.assertTrue(all(0.5 < u < 0.75 and 0.25 < v < 0.5 for u, v in uvs))
        faces = textured_prism_faces(
            Vec3(0.0, 0.0, 0.0),
            Vec3(0.0, 20.0, 0.0),
            start_radius=4.0,
            end_radius=3.0,
            side_cells=((0, 0), (1, 0), (2, 0), (3, 0)),
            cap_cells=((0, 3), (1, 3)),
        )
        self.assertEqual(len(faces), 6)
        self.assertTrue(all(len(face.vertices) == len(face.uvs) for face in faces))

    def test_pod_is_octagonal_depth_mesh_with_open_expression_plane(self) -> None:
        camera = Camera(180.0, 190.0)
        eye = Vec3(20.0, 105.0, 8.0)
        wrist = Vec3(-30.0, 25.0, -12.0)
        faces, plane = pod_faces_and_expression_plane(camera, eye, wrist)
        self.assertEqual(len(faces), 17)
        self.assertEqual(len(plane.ordered()), 4)
        self.assertGreater((faces[-1].vertices[0] - eye).length, 80.0)
        projected = tuple(camera.project(vertex) for vertex in plane.eyelid)
        self.assertGreater(abs((projected[1].x - projected[0].x) * (projected[3].y - projected[0].y)), 400.0)
        self.assertLess((plane.sclera[0] - plane.eyelid[0]).length, 1e-9)
        self.assertGreater((plane.iris[0] - plane.sclera[0]).length, 2.3)
        self.assertGreater((plane.pupil[0] - plane.sclera[0]).length, 2.1)
        base_width = abs(camera.project(plane.sclera[1]).x - camera.project(plane.sclera[0]).x)
        iris_width = abs(camera.project(plane.iris[1]).x - camera.project(plane.iris[0]).x)
        pupil_width = abs(camera.project(plane.pupil[1]).x - camera.project(plane.pupil[0]).x)
        self.assertLess(iris_width, base_width)
        self.assertGreater(pupil_width, base_width)

    def test_pod_aperture_prefers_forward_camera_gaze(self) -> None:
        camera = Camera(180.0, 190.0)
        eye = Vec3(20.0, 105.0, 8.0)
        wrist = Vec3(-30.0, 25.0, -12.0)
        camera_depth = camera.world_space(Vec3(0.0, 0.0, 1.0)).normalized()
        self.assertGreater(pod_axis(camera, eye, wrist).dot(camera_depth), 0.85)

    def test_terminal_link_attaches_to_rear_of_pod_not_aperture(self) -> None:
        camera = Camera(180.0, 190.0)
        wrist = Vec3(-30.0, 25.0, -12.0)
        eye = Vec3(20.0, 105.0, 8.0)
        joints = [Vec3(0.0, -138.0, 0.0), Vec3(45.0, -65.0, 20.0), wrist, eye]
        attachment = pod_attachment_point(camera, eye, wrist)
        rendered = visual_link_joints(joints, camera)
        self.assertEqual(rendered[-1], attachment)
        self.assertGreater((attachment - eye).length, 90.0)
        self.assertEqual(joints[-1], eye)

    def test_v2_mesh_contains_stable_uv_faces_for_links_and_pod(self) -> None:
        camera = Camera(180.0, 190.0)
        base = Vec3(0.0, -138.0, 0.0)
        joints = [base, Vec3(45.0, -65.0, 20.0), Vec3(-30.0, 25.0, -12.0), Vec3(20.0, 105.0, 8.0)]
        faces, plane = v2_surface_faces(base, joints, camera)
        textured = [face for face in faces if isinstance(face, TexturedFace3D)]
        self.assertGreater(len(textured), 63)
        self.assertEqual(len(plane.ordered()), 4)
        self.assertTrue(all(len(face.vertices) == len(face.uvs) for face in textured))

    def test_joint_point_textures_reuse_pod_atlas_style(self) -> None:
        camera = Camera(180.0, 190.0)
        end = Vec3(45.0, -65.0, 20.0)
        joint_cap = joint_point_texture_face(end, camera, index=1)
        self.assertEqual(joint_cap.uvs, atlas_cell_uv(1, 1))
        self.assertEqual(len(joint_cap.vertices), 4)

    def test_perspective_rasterizer_paints_texture_pixels(self) -> None:
        source = Image.new("RGB", (16, 16), "#ff0000")
        source.paste("#00ff00", (8, 0, 16, 16))
        atlas = UVTextureAtlas(source, max_size=16)
        face = TexturedFace3D(
            vertices=(Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(1, 1, 0), Vec3(0, 1, 0)),
            color="#ffffff",
            uvs=((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        )
        projected = (
            ProjectedPoint(2.0, 2.0, 0.0, 1.0),
            ProjectedPoint(13.0, 3.0, 10.0, 0.8),
            ProjectedPoint(12.0, 13.0, 10.0, 0.8),
            ProjectedPoint(3.0, 12.0, 0.0, 1.0),
        )
        target = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        rasterize_textured_face(target, atlas, face, projected)
        colors = {pixel[:3] for pixel in target.get_flattened_data() if pixel[3]}
        self.assertGreater(len(colors), 1)

    def test_expression_is_rendered_to_rgba_texture(self) -> None:
        view = RobotArm3DV2View()
        layers = render_expression_layers(view)
        self.assertEqual(len(layers), 4)
        self.assertTrue(all(layer.mode == "RGBA" for layer in layers))
        self.assertTrue(all(layer.getbbox() is not None for layer in layers))
        iris, sclera, pupil, _ = layers
        self.assertEqual(sclera.getpixel((36, 36))[3], 0)
        self.assertGreater(iris.getpixel((36, 36))[3], 0)
        self.assertGreater(iris.getpixel((59, 36))[3], 0)
        self.assertGreater(len(iris.getcolors(maxcolors=4096) or ()), 5)
        self.assertGreater(len(pupil.getcolors(maxcolors=4096) or ()), 3)
        texture = render_expression_texture(view)
        self.assertEqual(texture.mode, "RGBA")
        self.assertGreater(texture.getpixel((36, 36))[3], 0)
        self.assertEqual(texture.getpixel((0, 0))[3], 0)

    def test_eye_emission_uses_mood_color_outside_aperture(self) -> None:
        view = RobotArm3DV2View()
        camera = Camera(180.0, 190.0)
        eye = Vec3(20.0, 105.0, 8.0)
        wrist = Vec3(-30.0, 25.0, -12.0)
        _, planes = pod_faces_and_expression_plane(camera, eye, wrist)
        target = Image.new("RGBA", (360, 420), (0, 0, 0, 0))
        render_eye_emission(target, view, planes, camera)
        colored = [pixel for pixel in target.get_flattened_data() if pixel[3] > 0]
        self.assertGreater(len(colored), 150)
        self.assertTrue(all(alpha == 255 for _red, _green, _blue, alpha in colored))
        self.assertTrue(any(red > blue for red, _green, blue, _alpha in colored))

    def test_generated_uv_atlas_is_packaged(self) -> None:
        asset = (
            Path(__file__).parents[1]
            / "src"
            / "engram_overlay"
            / "overlays"
            / "assets"
            / "robot_arm_3d_v2"
            / "robot-uv-atlas-v2.png"
        )
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 100_000)


if __name__ == "__main__":
    unittest.main()
