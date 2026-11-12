"""Build the model/dependency fixture used for end-to-end verification.

Run from a FabricPy checkout:
    python examples/integration_check.py --loader all
    python examples/integration_check.py --loader neoforge --minecraft-version 1.21.1

All generated files and JARs stay under .fabricpy_build/integration-check/.
Requires javac and the normal FabricPy build prerequisites.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader', default='all')
    parser.add_argument('--minecraft-version', default='1.20.1')
    args = parser.parse_args()
    folder = ROOT / '.fabricpy_build/integration-check'
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'Widget.java'
    source.write_text('''package sample;
public final class Widget {
    private final String text;
    public Widget(String text) { this.text = text; }
    public String message() { return text; }
}
''', encoding='utf-8')
    subprocess.run(['javac', '--release', '17', '-d', str(folder / 'classes'), str(source)], check=True)
    with zipfile.ZipFile(folder / 'helper.jar', 'w') as jar:
        for file in (folder / 'classes').rglob('*.class'):
            jar.write(file, file.relative_to(folder / 'classes'))
    png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='
    blockbench = {
        'meta': {'format_version': '5.0', 'model_format': 'java_block'},
        'resolution': {'width': 16, 'height': 16},
        'textures': [{'id': '0', 'name': 'table.png', 'source': 'data:image/png;base64,' + png}],
        'elements': [{'uuid': 'cube', 'from': [0, 0, 0], 'to': [16, 8, 16],
                      'faces': {face: {'uv': [0, 0, 16, 8], 'texture': 0}
                                for face in ('north', 'south', 'east', 'west', 'up', 'down')}}],
        'outliner': ['cube'],
    }
    (folder / 'table.bbmodel').write_text(json.dumps(blockbench), encoding='utf-8')
    (folder / 'mod.py').write_text('''import fabricpy as mc
mod = mc.Mod('integration', 'Integration Check')
mod.dependency(path='helper.jar', mod_id='helper')
@mod.register
class Table(mc.Block):
    block_id = 'table'
    model = 'table.bbmodel'
    model_collision = True
    @mc.on_use
    def on_use(self, ctx: mc.BlockUseContext):
        widget = dep.helper.sample.Widget("Hello from Python")
        ctx.player.send_message(widget.message())
    @mc.on_place
    def placed(self, ctx: mc.BlockPlaceContext):
        if ctx.player is not None:
            ctx.player.send_message("Placed once on the server")
    @mc.on_break
    def broken(self, ctx: mc.BlockBreakContext):
        ctx.player.send_message("Broken once on the server")
@mod.register
class Token(mc.Item):
    item_id = 'token'
    model = 'table.bbmodel'
    @mc.on_right_click
    def use(self, ctx: mc.ItemUseContext):
        ctx.player.send_message("Used once on the server")
@mod.event('player_use_block')
def use_block(ctx):
    if ctx.hand.is_main_hand():
        ctx.player.send_message("Main-hand block interaction")
@mod.event('player_interact_entity')
def interact_entity(ctx):
    ctx.player.send_message("Entity interaction")
''', encoding='utf-8')
    from fabricpy.__main__ import main as build
    result = build(['build', str(folder / 'mod.py'), '--loader', args.loader,
                    '--minecraft-version', args.minecraft_version])
    if result:
        return result
    for jar in (folder / 'dist').glob('*.jar'):
        with zipfile.ZipFile(jar) as archive:
            model = json.loads(archive.read('assets/integration/models/block/table.json'))
            assert model['elements'][0]['to'] == [16, 8, 16], jar
            assert archive.read('assets/integration/textures/block/table/table.png') == base64.b64decode(png), jar
            assert 'com/generated/integration/block/Table.class' in archive.namelist(), jar
        print('Verified model, texture and compiled block:', jar.name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
