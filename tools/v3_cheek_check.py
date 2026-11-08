"""Reproducible cheek acceptance screenshots and a pull/release demo.

python -m tools.v3_cheek_check
"""
import json
import os
from pathlib import Path
import numpy as np
from PIL import Image
from v3proto.animation import Animator,Pose,Settings,SWAY_PARTS
from v3proto.render import Rig,Renderer,to_pil
from v3proto.__main__ import save_snapshot
from tools.v3_proto_check import contact


def main():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    out=Path('build/v3/cheek');out.mkdir(parents=True,exist_ok=True)
    rig=Rig();renderer=Renderer(rig,.6)
    scenarios=[('rest',(0,0),1,110),('pull',(-120,0),1,110),('maximum',(-200,0),1,60),
               ('up',(-200,-24),1,160),('down',(-200,24),1,60),('inward',(12,0),1,110),
               ('blink',(-120,0),.55,110),('closed',(-120,0),.1,110)]
    for start in (0,4):
        tiles=[]
        for face in rig.faces:
            for label,delta,eyes,radius in scenarios[start:start+4]:
                settings=Settings(expression=face,pinch_maximum=200,pinch_radius=radius)
                pose=Pose(head_y=-1,eye_scale=eyes,pinch_center=(325,610),pinch_delta=delta)
                path=out/f'{face}-{label}.png'
                save_snapshot(renderer,settings,pose,path,'#eee9e5')
                with Image.open(path) as im:
                    tiles.append((face+' / '+label,im.crop(tuple(round(v*.6) for v in (60,410,770,710)))))
        contact(tiles,out/('pull-contact.png' if start==0 else 'release-blink-contact.png'),columns=4)
    tiles=[]
    for face in ('smug','teary'):
        for bg in ('#20202b','white'):
            pose=Pose(head_y=-4,eye_scale=.55,pinch_delta=(-200,-24),angles={n:(12 if n=='ahoge' else -3) for n in SWAY_PARTS})
            path=out/f'{face}-moving-{bg.replace("#","")}.png'
            save_snapshot(renderer,Settings(expression=face,pinch_maximum=200),pose,path,bg)
            with Image.open(path) as im:tiles.append((face+' / moving '+bg,im.copy()))
    contact(tiles,out/'moving-contact.png',columns=4)
    settings=Settings(expression='neutral');animator=Animator(settings);animator.advance(1.2)
    frames=[];small=Renderer(rig,.4)
    for i in range(100):
        if i==10:animator.press((325,610))
        if 10<=i<30:
            u=(i-10)/19;u=u*u*(3-2*u);animator.drag((325-120*u,610))
        if i==38:animator.release()
        pose=animator.advance(1/30)
        rgba=to_pil(small.render(settings,pose))
        canvas=Image.new('RGBA',rgba.size,'#eee9e5');canvas.alpha_composite(rgba);frames.append(canvas.convert('RGB'))
    palette=frames[0].quantize(colors=256)
    gif=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
    gif[0].save(out/'pull-release.gif',save_all=True,append_images=gif[1:],duration=33,loop=0)
    contact([(str(i),frames[i]) for i in (9,20,29,38,43,52,70,99)],out/'demo-contact.png',columns=4)
    report={'expressions':len(rig.faces),'screenshots':68,'gif_frames':len(frames)}
    (out/'snapshot-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
