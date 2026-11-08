"""Import user-provided expression sheets without reslicing protected artwork.

python -m tools.v3_replace_expressions build/v3/replacements --raw <raw-v3-folder>
Input names: neutral-input.png, teary-input.png, angry-input.png.
Only expression assets and their rig metadata are written.
"""
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np
from PIL import Image
from scipy import ndimage as nd
from scipy.optimize import least_squares

from tools import v3_slice as vs
from v3proto.render import Rig


def align_head(reference, source, mask):
    """Fit affine sampling coordinates using unchanged upper-head artwork."""
    yy, xx = np.indices(mask.shape)
    pick = mask & (yy < 425) & (yy > 35) & (xx % 5 == 0) & (yy % 5 == 0)
    x, y = xx[pick].astype(float), yy[pick].astype(float)
    # Parameters use centered coordinates for well-conditioned scale/shear fits.
    x, y = x - 540, y - 250
    p = np.array([source.shape[1] / reference.shape[1], 0., 0.,
                  0., source.shape[0] / reference.shape[0], 0.])
    for sigma in (6, 3, 1):
        src = nd.gaussian_filter(source.astype(np.float32), (sigma, sigma, 0))
        ref = nd.gaussian_filter(reference.astype(np.float32), (sigma, sigma, 0))[pick]
        def residual(a):
            sx = a[0]*x + a[1]*y + 540*a[0] + a[2]
            sy = a[3]*x + a[4]*y + 250*a[4] + a[5]
            v = np.stack([nd.map_coordinates(src[..., c], [sy, sx], order=1, mode='constant', cval=255)
                          for c in range(3)], -1)
            return (v-ref).ravel().astype(float)
        p = least_squares(residual, p, diff_step=0.0002, loss='soft_l1', f_scale=20,
                          bounds=([.8,-.12,-120,-.12,.8,-120],[1.2,.12,120,.12,1.2,120]),
                          max_nfev=100).x
    sy = p[3]*(xx-540)+p[4]*yy+p[5]
    sx = p[0]*xx+p[1]*(yy-250)+p[2]
    aligned = np.stack([nd.map_coordinates(source[..., c], [sy, sx], order=1, mode='constant', cval=255)
                        for c in range(3)], -1).astype(np.uint8)
    return aligned, p


def manual_inputs(folder):
    sources={name:folder/('ref_no_pink.png' if name=='smug' else f'expr_{name}_no_pink.png')
             for name in ('smug',*vs.EXPRESSIONS)}
    missing=[p.name for p in sources.values() if not p.is_file()]
    if missing:raise ValueError('incomplete manual source set: '+', '.join(missing))
    return sources


def run(folder, raw=None, manual=None):
    sources=manual_inputs(manual) if manual else None
    if manual:raw=manual
    if raw is None:
        raise ValueError('--raw is required to rebuild the shared face contour consistently')
    folder.mkdir(parents=True,exist_ok=True)
    rig = Rig()
    ref = Image.new('RGBA', rig.size, 'white')
    ref.alpha_composite(rig.rest('smug',original=True))
    reference = np.asarray(ref.convert('RGB'))
    original_reference=reference.copy()
    from tools.v3_pink_marks import remove_marks
    # Keep protected original slices; the intentional rest-frame change is a
    # sparse patch containing only the user-requested pink-mark removal.
    if sources:
        with Image.open(sources['smug']) as im:clean_ref=im.convert('RGBA')
        if clean_ref.size!=rig.size:raise ValueError('manual reference must match the rig canvas')
        mark_mask=(np.asarray(clean_ref)[...,:3]!=np.asarray(ref)[...,:3]).any(-1)
        mark_mask &= np.asarray(rig.rest('smug',original=True))[...,3]>250
        reference=np.asarray(clean_ref.convert('RGB'))
    else:
        clean_ref,mark_mask=remove_marks(ref,'smug')
    patch=np.asarray(clean_ref).copy();patch[...,3]=mark_mask.astype(np.uint8)*255
    patch_file='expressions/manual_reference_patch.png' if sources else 'expressions/pink_cleanup.png'
    Image.fromarray(patch).save(vs.OUT/patch_file)
    rig.data['pink_cleanup']=patch_file
    rig.data.pop('face_feature_overrides',None)
    if sources:
        rig.data['face_feature_overrides']={}
        for name in ('eye_ref_l','eye_ref_r','mouth_ref'):
            part=rig.parts[name];a=np.asarray(rig.images[name]).copy()
            x,y=part['x'],part['y'];h,w=a.shape[:2]
            color=reference[y:y+h,x:x+w]
            old=original_reference[y:y+h,x:x+w]
            a[...,:3]=color
            c=color.astype(int)
            changed=np.abs(c-old.astype(int)).max(-1)>10
            skin=(c.min(-1)>200)&(c[...,0]-c[...,1]>=15)&(c[...,0]-c[...,1]<=40)
            a[changed&skin,3]=0
            file=f'expressions/manual_{name}.png'
            Image.fromarray(a).save(vs.OUT/file)
            rig.data['face_feature_overrides'][name]=file
    from tools.v3_face_features import clean_face_base, extract_features, clean_hair_face_ink, refined_fringe_mask
    physical=refined_fringe_mask(reference)
    closed_reference=None
    if raw:
        sleep=np.asarray(Image.open(sources['sleep'] if sources else raw/'expr_sleep.png').convert('RGB'))
        if sleep.shape[:2]!=reference.shape[:2]:raise ValueError('closed expression must match the rig canvas')
        from tools.v3_face_features import complete_face_plate
        plate,origin,face_domain=complete_face_plate(sleep)
        plate.save(vs.OUT/'expressions/face_plate.png')
        rig.data['face_plate']={'file':'expressions/face_plate.png','x':origin[0],'y':origin[1]}
        physical=~face_domain
        closed_reference=sleep
        yy,xx=np.indices(reference.shape[:2])
        ref_ink=(reference.min(-1)<160)&(reference[...,0]<220)
        sleep_ink=(sleep.min(-1)<160)&(sleep[...,0]<220)
        persistent=ref_ink&sleep_ink
        domain=((yy>375)&(yy<490)&(xx>310)&(xx<735))|((yy>=560)&(yy<645)&((xx<325)|(xx>715)))
        persistent &= domain
        guard=np.zeros((*reference.shape[:2],4),np.uint8)
        guard[persistent,:3]=reference[persistent];guard[persistent,3]=255
        Image.fromarray(guard).save(vs.OUT/'expressions/face_contour.png')
        rig.data['face_contour']='expressions/face_contour.png'
    head = np.asarray(rig.rest('smug'))[...,3]>128
    clean_face_base(rig,physical).save(vs.OUT/'expressions/face_clean_base.png')
    rig.data['face_clean_base'] = 'expressions/face_clean_base.png'
    Image.fromarray((physical*255).astype(np.uint8)).save(vs.OUT/'expressions/fringe_mask.png')
    rig.data['face_fringe_mask']='expressions/fringe_mask.png'
    report = {}
    aligned_sources={"smug":reference}
    names = vs.EXPRESSIONS if raw else ('neutral','teary','angry')
    for name in names:
        path = sources[name] if sources else folder / f'{name}-input.png'
        replacement = path.exists() and not sources
        if not sources and not replacement:path = raw / f'expr_{name}.png'
        with Image.open(path) as im:
            source = np.asarray(im.convert('RGB'))
        if replacement or (sources and source.shape[:2]!=reference.shape[:2]):
            aligned, matrix = align_head(reference,source,head)
        else:
            aligned, matrix = source, np.array([1.,0.,0.,0.,1.,0.])
        if not sources:aligned=np.asarray(remove_marks(Image.fromarray(aligned),name)[0])
        aligned_sources[name]=aligned
        image,(x,y),regions = extract_features(aligned,name,physical,closed_reference)
        file = f'expressions/expr_{name}.png'
        image.save(vs.OUT/file)
        old = rig.data['expression_sources'][name]
        rig.data['expression_sources'][name] = {**old,'x':x,'y':y,'size':list(image.size),'file':file,'regions':regions}
        report[name] = {'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'input_file':path.name,
                        'source_size':[source.shape[1],source.shape[0]],'sampling_affine':matrix.tolist()}
    if sources:
        report['smug']={'input_sha256':hashlib.sha256(sources['smug'].read_bytes()).hexdigest(),
                        'input_file':sources['smug'].name,'source_size':list(rig.size)}
        rig.data['manual_source_set']={'name':manual.name,'inputs':report,'automatic_pink_cleanup':False}
    else:rig.data.pop('manual_source_set',None)
    if raw:
        corrected,base=clean_hair_face_ink(rig,reference,clean_face_base(rig,physical),physical)
        rig.data['face_hair_clean']={}
        for name,image in corrected.items():
            file=f'expressions/{name}_face_clean.png'
            image.save(vs.OUT/file);rig.data['face_hair_clean'][name]=file
        base.save(vs.OUT/'expressions/face_clean_base.png')
    if sources:
        from tools.v3_face_features import fringe_mask
        fixed_fringe=fringe_mask(reference.shape[:2])
        fixed_fringe[:,:395]=False
        Image.fromarray((fixed_fringe*255).astype(np.uint8)).save(vs.OUT/'expressions/source_fringe_mask.png')
        rig.data['face_source_fringe_mask']='expressions/source_fringe_mask.png'
        rig.data['expression_face_plates']={}
        for name in ('smug','neutral','teary','angry'):
            rgb=aligned_sources[name]
            box=(*origin,origin[0]+plate.width,origin[1]+plate.height)
            opened=Image.fromarray(rgb).convert('RGBA').crop(box)
            opened.putalpha(plate.getchannel('A'))
            file=f'expressions/plate_{name}_open.png';opened.save(vs.OUT/file)
            rig.data['expression_face_plates'][name]={'open':file,'x':origin[0],'y':origin[1]}
    vs.split_rig_expressions(rig.data)
    vs.vx.RIG_FILE.write_text(json.dumps(rig.data,indent=1,ensure_ascii=False)+'\n',encoding='utf-8')
    (folder/'import-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    from tools.v3_cheek import build
    build(vs.vx.RIG_FILE)
    print(json.dumps(report))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--raw',type=Path,help='read-only original expression input folder')
    parser.add_argument('--manual-sources',type=Path,help='complete hand-edited *_no_pink set; bypass replacements and automatic cleanup')
    args=parser.parse_args()
    run(args.folder,args.raw,args.manual_sources)
