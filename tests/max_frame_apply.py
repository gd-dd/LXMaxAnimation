"""Cover only in an isolated 3dsmaxbatch session with an explicit E-drive output."""
import builtins
import hashlib
import json
import os
from pathlib import Path
import runpy
import time
import traceback

import pymxs
from pymxs import runtime as rt


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ['LX_FRAME_APPLY_TEST_OUTPUT']).resolve()
if OUTPUT.drive.casefold() != 'e:' or not OUTPUT.is_dir():
    raise RuntimeError('Frame test requires an existing isolated E-drive output directory')

ACTION = 'applyAssetFrames'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset(fps, start, end):
    rt.resetMaxFile(rt.Name('noPrompt'))
    rt.frameRate = fps
    rt.animationRange = rt.interval(start, end)


def assert_close(actual, expected):
    assert abs(float(actual) - expected) < 0.015, (actual, expected)


def point(node, frame):
    with pymxs.attime(frame):
        position = node.transform[3]
        return tuple(float(position[i]) for i in range(3))


def move(node, x, y=0.0, z=0.0):
    node.position = rt.point3(x, y, z)


def capture(bridge, name, kind, rig):
    folder = OUTPUT / name
    folder.mkdir()
    asset = bridge['execute_request']('saveWorkspaceAsset', dict(kind=kind, rig=rig, directory=str(folder)))
    assert asset['ok'] and (folder / 'source.max').is_file(), asset
    leaves = {'animation': 'animation-keys.json', 'pose': 'pose.json', 'model': 'tpose.json'}
    sidecar = folder / leaves[kind]
    assert sidecar.is_file(), asset
    return sidecar


def call(bridge, path, kind, rig='Generic', fps=24, expected=None):
    args = dict(path=str(path), kind=kind, rig=rig, sourceFps=fps)
    if expected is not None:
        args['expectedScene'] = expected
    return bridge['execute_request'](ACTION, args)


def call_through_session(bridge, path, kind, expected):
    session = builtins._lx_animation_bridge
    assert session.root.is_relative_to(OUTPUT)
    info = json.loads((session.root / 'info.json').read_text('utf8'))
    assert info['frameApply'] == 1, info
    request = dict(action=ACTION, expires=time.time()+30,
                   args=dict(path=str(path), kind=kind, rig='Generic', sourceFps=24, expectedScene=expected))
    bridge['write_json'](session.root / 'verify-frame.request.json', request)
    session.tick()
    return json.loads((session.root / 'verify-frame.result.json').read_text('utf8'))


def mesh_setup(mesh, output, target):
    filename = str(output / ('target.png' if target else 'source.png'))
    image = rt.bitmap(2, 2, color=rt.color(50, 155, 60) if target else rt.color(230, 60, 25))
    image.filename = filename
    rt.save(image)
    rt.close(image)
    material = rt.StandardMaterial(name='Destination Shader' if target else 'Asset Shader')
    material.diffuseMap = rt.Bitmaptexture(filename=filename)
    mesh.material = material
    deform = rt.Bend()
    rt.addModifier(mesh, deform)
    return filename, material, deform


def generic(bridge):
    reset(24, 2, 10)
    control = rt.Dummy(name='RigRoot')
    sub = rt.Circle(name='RigControl')
    sub.parent = control
    definition = rt.execute('attributes LXFrameAmount (parameters main (amount type:#float default:0 animatable:true))')
    rt.custAttributes.add(sub, definition)
    prop = rt.Box(name='AnimatedProp', length=20.0, width=16.0)
    _, _, source_deform = mesh_setup(prop, OUTPUT, False)
    # Source has geometry and hierarchy entries that must not be instantiated.
    rt.Box(name='MissingSourceModel')
    rt.Box(name='RevisedMesh')
    rt.Dummy(name='WrongClass')
    rt.Dummy(name='WrongParent')
    rt.Dummy(name='AmbiguousName')
    source_skin = rt.Box(name='SkinModel')
    rt.addModifier(source_skin, rt.Skin())
    with pymxs.animate(True):
        for frame, xpos, amount in ((2, 10, 1), (6, 20, 2), (10, 30, 3)):
            with pymxs.attime(frame):
                move(control, xpos)
                sub.amount = amount
                move(prop, xpos + 10, -1, 2)
                prop.length = 35.0 + frame
                source_deform.angle = float(frame + 15)
    rt.sliderTime = 2
    tpose = capture(bridge, 'source-tpose', 'model', 'Generic')
    rt.sliderTime = 6
    pose = capture(bridge, 'source-pose', 'pose', 'Generic')
    animation = capture(bridge, 'source-animation', 'animation', 'Generic')
    source_hashes = {leaf: digest(leaf) for path in (tpose, pose, animation)
                     for leaf in (path, path.parent / 'source.max')}

    reset(30, -4, 12)
    control = rt.Dummy(name='RigRoot')
    sub = rt.Circle(name='RigControl')
    sub.parent = control
    rt.custAttributes.add(sub, definition)
    prop = rt.Box(name='AnimatedProp', length=72.0, width=31.0)
    texture, dest_material, dest_deform = mesh_setup(prop, OUTPUT, True)
    replaced_shape = rt.Box(name='WrongClass', length=83)
    move(replaced_shape, 88.0)
    revised_mesh = rt.Box(name='RevisedMesh', length=81)
    rt.addModifier(revised_mesh, rt.Taper())
    new_model = rt.Plane(name='AdditionalModel')
    move(new_model, -100.0)
    unrelated_parent = rt.Dummy(name='LocalOnlyParent')
    moved_parent = rt.Dummy(name='WrongParent')
    moved_parent.parent = unrelated_parent
    move(moved_parent, -33.0)
    alias = rt.Dummy()
    other_alias = rt.Dummy()
    alias.name = other_alias.name = 'AmbiguousName'
    move(alias, 24.0)
    move(other_alias, 25.0)
    dest_skin = rt.Box(name='SkinModel', length=57)
    skin = rt.Skin()
    rt.addModifier(dest_skin, skin)
    move(dest_skin, 77.0)
    with pymxs.animate(True):
        for frame, xpos in ((0, 55.0), (8, 65.0)):
            with pymxs.attime(frame):
                move(control, xpos)
                sub.amount = 8.0 + frame
                move(prop, -20.0 if frame == 0 else -30.0)
                prop.length = 72.0 + frame
                dest_deform.angle = float(frame + 60)
    rt.select(new_model)
    rt.sliderTime = 5
    current_scene = OUTPUT / 'destination.max'
    assert rt.saveMaxFile(str(current_scene), quiet=True)
    initial_destination_file = digest(current_scene)
    names = sorted(str(node.name) for node in rt.objects)
    handles = sorted(int(rt.getHandleByAnim(node)) for node in rt.objects)
    material_handle = int(rt.getHandleByAnim(dest_material))
    deform_handle = int(rt.getHandleByAnim(dest_deform))
    skin_handle = int(rt.getHandleByAnim(skin))
    assert names.count('AmbiguousName') == 2, names
    earlier = (0, 2, 5, 6, 8, 10, 12)
    model_parameters = {}
    for frame in earlier:
        with pymxs.attime(frame):
            model_parameters[frame] = (float(prop.length), float(dest_deform.angle))

    tpose_result = call_through_session(bridge, tpose, 'model', str(current_scene))
    assert tpose_result['ok'], tpose_result
    assert_close(point(control, 5)[0], 10)
    assert_close(sub.amount, 1)
    assert (float(prop.length), float(dest_deform.angle)) == model_parameters[5]
    assert_close(rt.sliderTime, 5)
    assert rt.getKeyIndex(rt.getPropertyController(sub, 'amount'), 5) > 0
    pose_result = call(bridge, pose, 'pose', expected=str(current_scene))
    assert pose_result['ok'], pose_result
    assert_close(point(control, 5)[0], 20)
    assert_close(sub.amount, 2)
    assert (float(prop.length), float(dest_deform.angle)) == model_parameters[5]
    assert_close(rt.sliderTime, 5)
    assert len(list(rt.selection)) == 1 and str(rt.selection[0].name) == 'AdditionalModel'
    assert_close(point(replaced_shape, 5)[0], 88)
    assert_close(point(moved_parent, 5)[0], -33)
    assert_close(point(alias, 5)[0], 24)
    assert_close(point(other_alias, 5)[0], 25)
    assert_close(point(dest_skin, 5)[0], 77)

    old_control = {frame: point(control, frame) for frame in earlier}
    old_prop = {frame: point(prop, frame) for frame in earlier}
    old_amount = {}
    for frame in earlier:
        with pymxs.attime(frame):
            old_amount[frame] = float(sub.amount)
    result = call(bridge, animation, 'animation', expected=str(current_scene))
    assert result['ok'], result
    assert (result['start'], result['end']) == (13, 23), result
    assert (float(rt.animationRange.start), float(rt.animationRange.end), int(rt.frameRate)) == (-4, 23, 30)
    assert_close(rt.sliderTime, 5)
    for frame, expected in ((13, 10), (18, 20), (23, 30)):
        assert_close(point(control, frame)[0], expected)
        assert_close(point(prop, frame)[0], expected + 10)
    for frame in earlier:
        assert_close(point(control, frame)[0], old_control[frame][0])
        assert_close(point(prop, frame)[0], old_prop[frame][0])
        with pymxs.attime(frame):
            assert_close(sub.amount, old_amount[frame])
            assert (float(prop.length), float(dest_deform.angle)) == model_parameters[frame]
    for frame in (13, 18, 23):
        with pymxs.attime(frame):
            assert (float(prop.length), float(dest_deform.angle)) == model_parameters[12]
            assert_close(point(dest_skin, frame)[0], 77)
    assert sorted(str(node.name) for node in rt.objects) == names
    assert sorted(int(rt.getHandleByAnim(node)) for node in rt.objects) == handles
    assert (int(rt.getHandleByAnim(prop.material)), str(prop.material.diffuseMap.filename)) == (material_handle, texture)
    assert int(rt.getHandleByAnim(prop.modifiers[0])) == deform_handle
    assert int(rt.getHandleByAnim(dest_skin.modifiers[0])) == skin_handle
    assert float(revised_mesh.length) == 81 and str(rt.classOf(revised_mesh.modifiers[0])) == 'Taper'
    assert int(rt.getHandleByAnim(rt.selection[0])) == int(rt.getHandleByAnim(new_model))
    assert (Path(str(rt.maxFilePath)) / str(rt.maxFileName)).resolve() == current_scene.resolve()
    assert {leaf: digest(leaf) for leaf in source_hashes} == source_hashes
    assert digest(current_scene) == initial_destination_file
    return dict(tpose=tpose_result, pose=pose_result, animation=result, before={str(n): v[0] for n, v in old_control.items()})


def animated_past_timeline(bridge):
    reset(24, 0, 7)
    control = rt.Dummy(name='RigRoot')
    with pymxs.animate(True):
        with pymxs.attime(0):
            move(control, 31)
        with pymxs.attime(20):
            move(control, 63)
    rt.animationRange = rt.interval(0, 7)
    sampled = {n: point(control, n)[0] for n in (0, 3, 7, 15, 20)}
    path = OUTPUT / 'source-animation' / 'animation-keys.json'
    result = call(bridge, path, 'animation')
    assert result['ok'], result
    assert (result['start'], result['end']) == (21, 29), result
    for frame, value in sampled.items():
        assert_close(point(control, frame)[0], value)
    assert_close(point(control, 21)[0], 10)
    assert_close(point(control, 29)[0], 30)
    return dict(animation=result, before=sampled)


def built_in_rig(bridge, rig):
    reset(30, 0, 8)
    if rig == 'Biped':
        node = rt.biped.createNew(100, 0, rt.point3(0, 0, 0))
        node.controller.figureMode = False
        def set_pose(x):
            rt.biped.setTransform(node, rt.Name('pos'), rt.point3(x, 0, 50), True)
    else:
        cat = rt.CATParent()
        cat.AddHub()
        cat.AppendLayer('Base', rt.Name('Absolute'))
        cat.CATMode = 1
        node = cat.RootHub.node
        def set_pose(x):
            matrix = node.transform
            matrix.row4 = rt.point3(x, 0, 50)
            node.transform = matrix
    with pymxs.animate(True):
        with pymxs.attime(0):
            set_pose(0)
        with pymxs.attime(8):
            set_pose(20)
    rt.sliderTime = 8
    pose = capture(bridge, rig + '-pose', 'pose', rig)
    animation = capture(bridge, rig + '-animation', 'animation', rig)
    rt.Box(name='LocalProp')
    rt.animationRange = rt.interval(0, 12)
    rt.sliderTime = 10
    learned = call(bridge, pose, 'pose', rig, fps=30)
    assert learned['ok'], learned
    assert_close(point(node, 10)[0], 20)
    extended = call(bridge, animation, 'animation', rig, fps=30)
    assert extended['ok'], extended
    assert (extended['start'], extended['end']) == (13, 21), extended
    assert_close(point(node, 8)[0], 20)
    assert_close(point(node, 12)[0], 20)
    assert_close(point(node, 13)[0], 0)
    assert_close(point(node, 21)[0], 20)
    assert_close(rt.sliderTime, 10)
    assert rt.getNodeByName('LocalProp') is not None
    return dict(pose=learned, animation=extended)


report = {
    'ok': False,
    'pid': os.getpid(),
    'bridge': digest(ROOT / 'max/bridge.py'),
    'hostVersion': str(rt.maxVersion()),
    'cases': {},
}
connection_root = OUTPUT / 'connections' / 'LXMaxTools'
connection_root.mkdir(parents=True)
rt.execute('global LXMaxAutoConnectRoot')
rt.LXMaxAutoConnectRoot = str(connection_root)
bridge = runpy.run_path(str(ROOT / 'max/bridge.py'))
for label, exercise in (('Generic', generic), ('Hidden keys', animated_past_timeline), ('Biped', built_in_rig), ('CAT', built_in_rig)):
    try:
        details = exercise(bridge, label) if label in ('Biped', 'CAT') else exercise(bridge)
        report['cases'][label] = dict(ok=True, **details)
    except Exception:
        report['cases'][label] = dict(ok=False, error=traceback.format_exc())
report['ok'] = all(case['ok'] for case in report['cases'].values())
(OUTPUT / 'frame-apply-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(report, ensure_ascii=False))
