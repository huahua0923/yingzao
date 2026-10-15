import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=r'D:\项目\cdut3d\rebuild\05_build\c006_white.glb')
bpy.ops.wm.save_as_mainfile(filepath=r'D:\项目\cdut3d\rebuild\05_build\c006_white.blend')
