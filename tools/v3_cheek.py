"""Build clean cheek material and separate visibility/feature masks."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd
from scipy.interpolate import PchipInterpolator
from v3proto.render import Rig, DEFAULT_RIG
from v3proto.face import plate_face
from tools.v3_face_features import REGIONS

REGION={'cap_x':375.,'root_x':445.,'vertical':[536.,584.,628.,676.]}
BOX=(270,536,445,676)
SMUG_EYES=[[(299,499),(350,475),(440,450),(478,465),(494,535),(470,553),(350,572),(300,535)],
           [(554,441),(606,428),(669,428),(745,461),(740,513),(695,539),(554,530)]]


def eye_windows(size,face):
    mask=Image.new('L',size);draw=ImageDraw.Draw(mask)
    polygons=SMUG_EYES if face=='smug' else [REGIONS[face]['eye_l'],REGIONS[face]['eye_r']]
    if face=='teary':
        polygons=[[(309,505),(436,466),(478,467),(481,538),(409,560),(345,575),(329,563),(329,547),(310,535)],polygons[1]]
    for points in polygons:draw.polygon(points,fill=255)
    return mask


def clean_material(color,domain,visible,features,upper_anchor):
    """Transport continuous skin, never a hole or a hair wedge under an eye.

    The upper outline follows the skin's left envelope; the broader old ink
    band can contain a touching fringe tip and is unsuitable as material.
    """
    y,x=np.indices(domain.shape);x=x+BOX[0];y=y+BOX[1]
    inside=domain.copy()
    left=[]
    for row in domain:
        indices=np.flatnonzero(row)
        left.append(float(indices[0]+BOX[0]) if len(indices) else BOX[2]-1)
    left=np.asarray(left)
    # The flood can reach a white fringe patch through the eye corner. Its
    # upper envelope is not a cheek contour. Join the fixed skin attachment
    # monotonically to two unoccluded lower-cheek samples instead.
    lower=left[584-BOX[1]]
    middle=max(left[560-BOX[1]],lower+4)
    upper=max(upper_anchor,middle+10)
    curve=PchipInterpolator([536,560,584],[upper,middle,lower])
    rows=np.arange(BOX[1],BOX[3])
    left=np.where(rows<584,curve(np.minimum(rows,584)),left)[:,None]
    lower_ink=(color[...,:3].max(-1)<180)&(visible>0)&(y>=590)&(y<=635)&(x<330)
    ink=np.median(color[...,:3][lower_ink],axis=0) if lower_ink.any() else np.array([83,25,32])
    rgb=color[...,:3].astype(int)
    valid=(inside&(x>=left)&~features&(rgb[...,0]>230)&(rgb[...,1]>140)
           &(rgb[...,2]>rgb[...,1]-8)&(rgb[...,2]<rgb[...,1]+30)&(rgb[...,0]-rgb[...,1]>12))
    if not valid.any():raise ValueError('no cheek skin samples')
    _,near=nd.distance_transform_edt(~valid,return_indices=True)
    fill=nd.gaussian_filter(color[...,:3][tuple(near)].astype(np.float32),(1.2,1.2,0))
    repaired=color[...,:3].copy()
    pink_ink=(rgb[...,0]>210)&(rgb[...,0]-rgb[...,1]>40)&(rgb[...,2]>rgb[...,1]+4)&(rgb[...,1]>90)&(rgb[...,1]<200)
    surface_color=((rgb[...,0]>230)&(rgb[...,1]>140)&(rgb[...,2]>rgb[...,1]-8)&(rgb[...,2]<rgb[...,1]+30)&(rgb[...,0]-rgb[...,1]>12))|pink_ink
    remove=features|((y<584)&(x>=left-.5)&~surface_color)
    repaired[remove]=np.rint(fill[remove]).astype(np.uint8)
    # Reconstruct only the short upper connecting outline, retaining the raw
    # rounded end and its stroke below the transition.
    amount=np.clip((584-y)/14,0,1);amount=amount*amount*(3-2*amount)
    upper_alpha=np.clip(x-(left-11)+.5,0,1)*255
    alpha=np.rint(upper_alpha*amount+visible*(1-amount)).astype(np.uint8)
    upper=repaired.copy()
    upper[x<left-.5]=np.rint(ink).astype(np.uint8)
    repaired=np.rint(upper*amount[...,None]+repaired*(1-amount[...,None])).astype(np.uint8)
    material=np.dstack([repaired,alpha]);material[alpha==0]=0
    return Image.fromarray(material)


def build(path=DEFAULT_RIG):
    path=Path(path);rig=Rig(path);folder=path.parent/'interactions';folder.mkdir(exist_ok=True)
    config={**REGION,'box':list(BOX),'faces':{}}
    skin=rig.parts['head_skin'];skin_alpha=np.asarray(rig.images['head_skin'])[BOX[1]-skin['y'],:,3]
    upper_anchor=float(np.flatnonzero(skin_alpha>128).min()+skin['x'])
    for face in rig.faces:
        plate,origin=plate_face(rig,face,1)
        canvas=Image.new('RGBA',rig.size);canvas.alpha_composite(plate,origin)
        color=np.asarray(canvas.crop(BOX)).copy()
        rgb=np.asarray(canvas)[...,:3].astype(int)
        wall=nd.binary_closing(rgb.min(-1)<150,iterations=1)
        labels,_=nd.label(~wall);seed=labels[640,500]
        if seed==0:raise ValueError('skin seed lies on ink: '+face)
        domain=nd.binary_fill_holes(labels==seed)
        distance=nd.distance_transform_edt(~domain)
        visible=domain|((distance<=15)&(rgb.max(-1)<210))
        visible=(visible[BOX[1]:BOX[3],BOX[0]:BOX[2]]*255).astype(np.uint8)
        protection=eye_windows(rig.size,face)
        features=np.asarray(protection.crop(BOX))>0
        local_domain=domain[BOX[1]:BOX[3],BOX[0]:BOX[2]]
        material=clean_material(color,local_domain,visible,features,upper_anchor)
        # Removal and transported material are different: fixed features stay
        # in the original image, while the moving surface has filled skin.
        alpha=np.minimum(visible,np.asarray(material)[...,3]).copy();alpha[features]=0
        yy,xx=np.indices(alpha.shape);xx+=BOX[0];yy+=BOX[1]
        hit=nd.binary_erosion(alpha>200,iterations=3)&(xx<385)&(yy>=570)&(yy<=650)
        prefix=f'interactions/cheek_{face}'
        Image.fromarray(alpha).save(path.parent/(prefix+'_mask.png'))
        protection.save(path.parent/(prefix+'_protect.png'))
        material.save(path.parent/(prefix+'.png'))
        Image.fromarray((hit*255).astype(np.uint8)).save(path.parent/(prefix+'_hit.png'))
        config['faces'][face]={'mask':prefix+'_mask.png','texture':prefix+'.png','hit':prefix+'_hit.png','protect':prefix+'_protect.png'}
    rig.data.setdefault('interactions',{})['cheek_left']=config
    path.write_text(json.dumps(rig.data,indent=1,ensure_ascii=False)+'\n',encoding='utf-8')
    print('built cheek assets for',len(config['faces']),'expressions')


if __name__=='__main__':build()
