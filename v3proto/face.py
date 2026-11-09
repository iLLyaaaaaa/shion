"""Shared brow masks: mouth includes brows in the three-layer rig contract."""
import numpy as np
from PIL import Image,ImageDraw


def reference_face(rig,expression,eye_scale):
    """Compose face and eyes in reference pixels before any display scaling."""
    p=rig.parts['head_skin']
    skin=rig.face_base.copy()
    if expression=='smug':
        a=np.asarray(rig.images['head_skin']).copy();clean=np.asarray(skin)
        yy,xx=np.indices(a.shape[:2]);xx+=p['x'];yy+=p['y']
        mask=(yy<551)&((xx<500)|(xx>560));a[mask]=clean[mask]
        skin=Image.fromarray(a)
    for n in rig.face_parts(expression):
        part=rig.parts[n]
        image=without_brows(rig,n) if part['role']=='mouth' else eye_image(rig,n)
        x,y=part['x']-p['x'],part['y']-p['y']
        if part['role'].startswith('eye') and eye_scale!=1:
            pivot=part['blink_pivot'][1]
            y=round(pivot+(part['y']-pivot)*eye_scale)-p['y']
            image=image.resize((image.width,max(1,round(image.height*eye_scale))),Image.Resampling.LANCZOS)
        skin.alpha_composite(image,(x,y))
    return skin


def plate_face(rig,expression,eye_scale):
    if expression not in rig.expression_plates:
        return _blink_plate(rig,expression,eye_scale)
    opened,origin=rig.expression_plates[expression]
    if getattr(rig,'mirror_sum',None) is not None:
        # The stored open plates still carry the original left bulge. Rebuild
        # them from the mirrored clean plate (fringe tips keep original pixels).
        if expression not in rig._mirror_opened:
            rig._mirror_opened[expression]=_blink_plate(rig,expression,1)[0]
        opened=rig._mirror_opened[expression]
        origin=rig.face_plate[1]
    cache=getattr(rig,'_blink_regions',None)
    if cache is None:cache=rig._blink_regions={}
    if expression not in cache:
        from scipy import ndimage as nd
        rest=np.asarray(_blink_plate(rig,expression,1)[0]).astype(int)
        closed=np.asarray(_blink_plate(rig,expression,.1)[0]).astype(int)
        moving=np.abs(rest-closed).max(-1)>2
        # Only the two moving eye footprints may replace the original plate.
        # Mouth, blush and fringe retain exactly the same source pixels.
        moving=nd.binary_dilation(moving,iterations=8)
        cache[expression]=Image.fromarray(moving.astype(np.uint8)*255)
    if eye_scale==1:return opened.copy(),origin
    blink,_=_blink_plate(rig,expression,eye_scale)
    u=float(np.clip((1-eye_scale)/.25,0,1))
    weight=u*u*(3-2*u)
    result=opened.copy()
    result.paste(Image.blend(opened,blink,weight),(0,0),cache[expression])
    return result,origin


def _blink_plate(rig,expression,eye_scale):
    image,origin=rig.face_plate
    canvas=image.copy()
    for n in rig.face_parts(expression):
        p=rig.parts[n]
        is_eye=p['role'].startswith('eye')
        feature=complete_eye(rig,n) if is_eye else rig.feature_images.get(n,rig.images[n])
        x,y=p['x']-origin[0],p['y']-origin[1]
        if p['role'].startswith('eye') and eye_scale!=1:
            pivot=p['blink_pivot'][1]
            y=round(pivot+(p['y']-pivot)*eye_scale)-origin[1]
            feature=feature.resize((feature.width,max(1,round(feature.height*eye_scale))),Image.Resampling.LANCZOS)
        if is_eye and rig.fringe_mask is not None:
            a=np.asarray(feature).copy()
            box=(x+origin[0],y+origin[1],x+origin[0]+feature.width,y+origin[1]+feature.height)
            a[np.asarray(rig.fringe_mask.crop(box))>0]=0
            feature=Image.fromarray(a)
        canvas.alpha_composite(feature,(x,y))
    if expression in rig.expression_plates and rig.source_fringe_mask is not None:
        opened,_=rig.expression_plates[expression]
        mask=rig.source_fringe_mask.crop((origin[0],origin[1],origin[0]+canvas.width,origin[1]+canvas.height))
        if getattr(rig,'mirror_sum',None) is not None:
            # Original-side fringe pixels would bring back the old right-hand
            # blush and contour on top of the mirrored bulge.
            from PIL import ImageChops
            from .mirror import fringe_keep
            mask=ImageChops.multiply(mask,fringe_keep(rig,canvas.size,origin))
        canvas.paste(opened,(0,0),mask)
    return canvas,origin


def reference_brows(rig):
    """Recover the two original pink brows which step 0 left in skin/eyes."""
    from scipy import ndimage as nd
    if hasattr(rig,'_reference_brows'):return rig._reference_brows
    original=Image.new('RGBA',rig.size)
    for name in rig.active('smug'):
        p=rig.parts[name]
        original.alpha_composite(rig.images[name],(p['x'],p['y']))
    a=np.asarray(original).copy();mask=np.zeros(a.shape[:2],bool)
    for x0,y0,x1,y1 in ((365,430,450,473),(555,405,675,455)):
        c=a[y0:y1,x0:x1,:3].astype(int)
        pink=(c[...,0]>215)&(c[...,0]-c[...,1]>40)&(c[...,1]>90)&(c[...,1]<190)&(c[...,2]>c[...,1])
        labels,count=nd.label(pink,np.ones((3,3)))
        sizes=np.bincount(labels.ravel(),minlength=count+1);sizes[0]=0
        mask[y0:y1,x0:x1]=nd.binary_dilation(labels==sizes.argmax(),iterations=2)
    a[~mask]=0
    image=Image.fromarray(a);box=image.getbbox()
    rig._reference_brows=(image.crop(box),(box[0],box[1]))
    return rig._reference_brows


def complete_eye(rig,name):
    """Fill narrow occlusion notches before blinking; the hair masks them later."""
    from scipy import ndimage as nd
    cache=getattr(rig,'_complete_eyes',None)
    if cache is None:cache=rig._complete_eyes={}
    if name not in cache:
        a=np.asarray(eye_image(rig,name)).copy()
        solid=a[...,3]>128
        # Thin hair remnants can touch an eye through a one-pixel bridge.
        # Classify the substantial strokes, then restore their soft perimeter.
        core=nd.binary_opening(solid,iterations=2)
        labels,count=nd.label(core,np.ones((3,3)))
        sizes=np.bincount(labels.ravel(),minlength=count+1);sizes[0]=0
        keep=sizes>=max(20,int(sizes.max()*.02));keep[0]=False
        support=nd.binary_dilation(keep[labels],iterations=3)
        a[~support]=0
        solid=a[...,3]>128
        closed=nd.binary_closing(np.pad(solid,12),iterations=6)[12:-12,12:-12]
        missing=closed&~solid
        _,near=nd.distance_transform_edt(~solid,return_indices=True)
        a[missing]=a[tuple(near)][missing]
        cache[name]=Image.fromarray(a)
    return cache[name]


def eye_image(rig,name):
    image=rig.feature_images.get(name,rig.images[name])
    part=rig.parts[name]
    if part.get('variant')!='smug' or rig.fringe_mask is None:
        return image
    a=np.asarray(image).copy()
    box=(part['x'],part['y'],part['x']+image.width,part['y']+image.height)
    a[np.asarray(rig.fringe_mask.crop(box))>0]=0
    brow,origin=reference_brows(rig)
    mask=Image.new('L',image.size)
    mask.paste(brow.getchannel('A'),(origin[0]-part['x'],origin[1]-part['y']))
    a[np.asarray(mask)>0]=0
    # Clipping the old fringe out of ref eyes can leave detached specks.
    # They must not collapse into floating lines during a blink.
    from scipy import ndimage as nd
    labels,count=nd.label(a[...,3]>128,np.ones((3,3)))
    sizes=np.bincount(labels.ravel(),minlength=count+1);sizes[0]=0
    keep=sizes>=max(20,int(sizes.max()*.02));keep[0]=False
    a[~nd.binary_dilation(keep[labels],iterations=2)]=0
    return Image.fromarray(a)


def brows_image(rig, expression):
    region=rig.data.get('expression_sources',{}).get(expression,{}).get('regions',{})
    paths=region.get('brow_paths',[])
    if not paths:return None
    name=next(n for n in rig.face_parts(expression) if rig.parts[n]['role']=='mouth')
    p=rig.parts[name];a=np.asarray(rig.images[name]).copy()
    mask=Image.new('L',(a.shape[1],a.shape[0]))
    for points,width in paths:
        ImageDraw.Draw(mask).line([(x-p['x'],y-p['y']) for x,y in points],fill=255,width=width,joint='curve')
    a[...,3]=np.minimum(a[...,3],np.asarray(mask))
    return Image.fromarray(a),(p['x'],p['y'])


def without_brows(rig, name):
    p=rig.parts[name]
    if p.get('role')!='mouth':return rig.images[name]
    brow=brows_image(rig,p['variant'])
    if not brow:return rig.images[name]
    a=np.asarray(rig.images[name]).copy()
    a[...,3]=np.where(np.asarray(brow[0])[...,3]>0,0,a[...,3])
    return Image.fromarray(a)
