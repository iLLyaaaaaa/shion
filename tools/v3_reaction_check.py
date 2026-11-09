"""Offscreen reaction screenshots, normal/combo demos and stage trace."""
import json
import os
from pathlib import Path
from PIL import Image,ImageDraw
from v3proto.animation import Animator,Pose,Settings
from v3proto.render import Rig,Renderer,to_pil
from tools.v3_proto_check import contact


def on_background(rgba):
    im=Image.new('RGBA',rgba.size,'#eee9e5');im.alpha_composite(rgba)
    return im.convert('RGB')


def main():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    out=Path('build/v3/reaction');out.mkdir(parents=True,exist_ok=True)
    rig=Rig();r=Renderer(rig,.6);tiles=[]
    stages=[('surprise','surprised',(0,0),1),('struggle','dizzy',(-75,0),1),
            ('cry','teary',(-120,0),1),('maximum','teary',(-200,-24),.1),
            ('rebound','angry',(-30,0),.55)]
    for face in rig.faces:
        s=Settings(expression=face,pinch_maximum=200)
        for label,expression,delta,eyes in stages:
            pose=Pose(head_y=-2,pinch_delta=delta,eye_scale=eyes,reaction_face=expression,reaction_base=face)
            im=on_background(to_pil(r.render(s,pose)))
            im.save(out/f'{face}-{label}.png')
            tiles.append((face+' / '+label,im.crop(tuple(round(v*.6) for v in (60,385,780,705)))))
    contact(tiles,out/'all-faces-contact.png',columns=5)
    trace=[]
    r=Renderer(rig,.4)
    for combo in (False,True):
        s=Settings(expression='happy');a=Animator(s)
        if combo:
            for _ in range(2):
                a.press((325,610));a.advance(.08);a.release();a.advance(.22)
        frames=[];last_stage=None
        for i in range(300):
            if i==15:a.press((325,610))
            if 15<=i<60:
                u=min(1,(i-15)/45);u=u*u*(3-2*u)
                a.drag((325-72*u,610))
            if i==105:a.drag((205,610))
            if i==130:a.release()
            pose=a.advance(1/30)
            stage=a.reaction.stage
            if stage!=last_stage:
                trace.append({'combo':combo,'time':round(i/30,3),'stage':stage,'face':pose.reaction_face,'count':a.reaction.count})
                last_stage=stage
            im=on_background(to_pil(r.render(s,pose)))
            ImageDraw.Draw(im).text((8,8),f'{i/30:.2f}s / {stage}'+(' / combo' if combo else ''),fill='#302020')
            frames.append(im)
        label='combo' if combo else 'normal'
        palette=frames[60].quantize(colors=256)
        gif=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in frames]
        gif[0].save(out/f'{label}.gif',save_all=True,append_images=gif[1:],duration=33,loop=0)
        contact([(str(i/30),frames[i]) for i in (14,18,40,90,130,136,210,299)],out/f'{label}-contact.png',columns=4)
    (out/'stage-trace.json').write_text(json.dumps(trace,indent=2)+'\n',encoding='utf-8')
    from v3proto.window import Preview
    w=Preview(rig,Settings(expression='happy'))
    w.canvas.timer.stop();w.stats_timer.stop()
    w.show();app.processEvents()
    w.canvas.animator.press((325,610))
    w.canvas.animator.drag((205,610));w.canvas.animator.advance(.4)
    w.update_reaction();w.canvas.update();app.processEvents()
    w.grab().save(str(out/'preview-controls.png'))
    w.close();app.processEvents()
    # Also inspect the exact-static path with regular animations disabled.
    static_tiles=[]
    for face in rig.faces:
        s=Settings(expression=face,breath=False,blink=False,sway=False)
        a=Animator(s);a.press((325,610));a.drag((205,610));a.advance(.4)
        im=on_background(to_pil(r.render(s,a.pose)))
        im.save(out/f'{face}-static-reaction.png')
        static_tiles.append((face,im))
    contact(static_tiles,out/'static-contact.png',columns=4)
    print('48 character screenshots, panel screenshot and two 300-frame demos generated')


if __name__=='__main__':main()
