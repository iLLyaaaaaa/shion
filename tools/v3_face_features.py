"""Shared continuous face plate and feature-only expression extraction."""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd


REGIONS = {
 'neutral': {
  'eye_l': [(302,485),(370,465),(437,463),(483,482),(491,541),(464,560),(341,560),(306,535)],
  'eye_r': [(553,462),(607,448),(681,452),(743,477),(728,529),(681,550),(566,549)],
  'brows': [[(373,438),(435,430),(446,452),(373,458)],[(565,427),(647,422),(664,443),(565,447)]],
  'mouth': [(493,573),(565,573),(565,604),(493,604)]},
 'teary': {
  'eye_l': [(309,505),(436,466),(478,467),(481,538),(409,560),(345,575),(311,559)],
  'eye_r': [(553,444),(719,456),(750,484),(749,533),(697,554),(572,535)],
  'brows': [[(326,450),(372,426),(428,396),(443,411),(403,446),(337,463)],[(562,416),(617,414),(675,423),(680,442),(561,439)]],
  'mouth': [(500,547),(567,547),(567,591),(500,591)]},
 'angry': {
  'eye_l': [(308,482),(476,482),(491,503),(486,553),(462,571),(351,571),(309,537)],
  'eye_r': [(553,477),(696,449),(748,444),(746,515),(698,553),(562,559)],
  'brows': [[(330,420),(447,451),(479,458),(483,476),(447,474),(326,436)],[(552,449),(633,414),(654,404),(663,421),(623,451),(558,469)]],
  'mouth': [(501,545),(566,545),(566,609),(501,609)]},
 'surprised': {
  'eye_l': [(309,481),(358,457),(432,450),(480,472),(491,531),(476,577),(370,591),(314,562)],
  'eye_r': [(556,450),(602,426),(656,431),(701,456),(742,482),(746,523),(684,567),(564,571)],
  'brows': [[(349,430),(425,420),(455,445),(432,459),(350,458)],[(562,412),(641,404),(674,424),(658,439),(560,435)]],
  'mouth': [(504,556),(566,556),(566,622),(504,622)]},
 'happy': {
  'eye_l': [(311,520),(383,482),(448,480),(482,501),(480,555),(324,569)],
  'eye_r': [(562,489),(598,462),(668,452),(735,475),(735,527),(561,535)],
  'brows': [[(363,470),(415,451),(470,466),(477,489),(410,483),(365,488)],[(605,417),(678,421),(727,450),(726,473),(674,451),(606,441)]],
  'mouth': [(483,517),(594,517),(594,627),(483,627)]},
 'sleep': {
  'eye_l': [(315,514),(448,503),(481,506),(481,557),(318,567)],
  'eye_r': [(565,484),(720,483),(743,508),(735,533),(565,539)],
  'brows': [[(362,468),(415,450),(478,467),(482,488),(414,484),(363,489)],[(608,417),(678,419),(716,442),(710,464),(607,444)]],
  'mouth': [(506,547),(568,547),(568,590),(506,590)]},
 'dizzy': {
  'eye_l': [(363,469),(464,469),(480,528),(460,565),(366,564)],
  'eye_r': [(570,445),(666,443),(676,531),(570,536)],
  'brows': [[(407,427),(486,456),(488,484),(410,454)],[(570,391),(711,433),(713,459),(569,419)]],
  'mouth': [(489,548),(570,548),(570,592),(489,592)]},
}
# S6 用 S0 部件拼的表情（tools/v3_s0_faces.py）：新五官都在 neutral 的五官范围内
REGIONS['tired'] = REGIONS['neutral']
REGIONS['bored'] = REGIONS['neutral']
REGIONS['yawn'] = REGIONS['sleep']  # 只有嘴换成放大的张大嘴；捏脸保护区只看眼睛
BROW_PATHS = {
 'neutral': [],
 'teary': [([(332,452),(372,444),(408,429),(435,411),(441,402)],14), ([(568,428),(602,425),(636,430),(665,430)],14)],
 'angry': [([(333,432),(369,445),(417,461),(455,467)],14), ([(559,458),(586,449),(615,435),(645,416)],14)],
 'surprised': [([(358,446),(390,434),(417,443),(437,452)],14), ([(573,426),(601,418),(638,422),(655,431)],14)],
 'happy': [([(410,487),(432,485),(457,491)],16), ([(615,433),(650,439),(688,456),(710,467)],14)],
 'sleep': [([(374,478),(410,468),(443,471),(467,480)],14), ([(615,433),(650,439),(688,451),(700,451)],14)],
 'dizzy': [([(421,442),(449,459),(478,474)],14), ([(580,408),(622,423),(660,439),(697,449)],14)],
}


def polygon_mask(shape, points):
    im=Image.new('1',(shape[1],shape[0]))
    ImageDraw.Draw(im).polygon(points,fill=1)
    return np.asarray(im,dtype=bool)


def complete_face_plate(closed):
    """A single continuous face/hair boundary from the existing closed sheet."""
    c=closed.astype(np.int16)
    wall=nd.binary_closing(c.min(-1)<150,iterations=1)
    labels,_=nd.label(~wall)
    face=nd.binary_fill_holes(labels==labels[580,530])
    yy,xx=np.indices(face.shape)
    eyes=((xx>=315)&(xx<=485)&(yy>=506)&(yy<=558))|((xx>=560)&(xx<=738)&(yy>=480)&(yy<=535))
    mouth=(xx>500)&(xx<580)&(yy>540)&(yy<604)
    # Close the narrow slit where the closed left eyelid touches the outer
    # contour, without declaring a rectangular piece of hair to be skin.
    face=nd.binary_fill_holes(nd.binary_closing(face,iterations=18))
    # Blush also has a low green channel. Only erase dark facial ink; treating
    # every saturated pixel as ink cuts rectangular holes out of the blush.
    remove=(eyes|mouth)&(c.min(-1)<130)&face
    remove=nd.binary_dilation(remove,iterations=2)
    source=face&~remove&(c[...,0]>240)&(c[...,1]>210)&(c[...,0]-c[...,1]<40)
    _,nearest=nd.distance_transform_edt(~source,return_indices=True)
    fill=nd.gaussian_filter(closed[tuple(nearest)].astype(np.float32),(5,5,0))
    color=closed.copy()
    blend=np.maximum(remove,nd.gaussian_filter(remove.astype(np.float32),1))
    color=np.rint(color*(1-blend[...,None])+fill*blend[...,None]).astype(np.uint8)
    for cx,cy,rx,ry,top in ((366,593,73,65,561),(674,558,65,57,539)):
        radius=np.sqrt(((xx-cx)/rx)**2+((yy-cy)/ry)**2)
        opacity=np.clip((1-radius)*24,0,1)*np.clip((top-yy)/8,0,1)*face
        color=np.rint(color*(1-opacity[...,None])+np.array([254,174,182])*opacity[...,None]).astype(np.uint8)
    # The outer feather lives in intact hair, away from the facial contour.
    distance=nd.distance_transform_edt(~face)
    alpha=np.clip((30-distance)/12,0,1)
    rgba=np.dstack([color,np.rint(alpha*255).astype(np.uint8)])
    image=Image.fromarray(rgba);box=image.getbbox()
    return image.crop(box),(box[0],box[1]),face


def fringe_mask(shape):
    """Physical fringe silhouette through the eye windows in reference pixels.

    Step-0 eye cutouts also own the two fringe tips. Restore those tips to the
    moving hair; otherwise blinking compresses hair together with the eye.
    """
    central=[(390,330),(548,330),(550,368),(545,394),(544,420),
             (548,451),(552,463),(558,473),(554,479),(532,480),
             (508,477),(487,469),(472,456),(488,474),(494,478),
             (492,483),(478,483),(457,475),(435,462),(418,446),
             (406,427),(398,404),(393,378)]
    right=[(548,330),(672,330),(672,416),(646,432),(626,430),
           (610,426),(588,412),(568,395),(553,380),(544,366)]
    left=[(302,350),(401,350),(400,381),(389,397),(375,419),
          (359,444),(347,468),(340,479),(334,485),(327,489),
          (318,488),(310,471),(302,443)]
    physical=polygon_mask(shape,central)|polygon_mask(shape,right)|polygon_mask(shape,left)
    return nd.binary_dilation(physical,iterations=2)


def refined_fringe_mask(reference):
    """Keep complete reference strokes along the fringe instead of cutting
    their antialiasing at the edge of an approximate polygon.
    """
    mask=fringe_mask(reference.shape[:2])
    corridor=Image.new('1',(reference.shape[1],reference.shape[0]))
    paths=[[(398,374),(391,395),(377,420),(361,447),(348,472),(338,486)],
           [(398,376),(404,404),(416,432),(437,454),(464,473),(488,479)],
           [(468,440),(477,459),(491,478)],
           [(470,443),(491,459),(519,472),(549,476),(553,473),
            (548,462),(544,436),(543,406),(547,365)],
           [(548,370),(570,393),(599,415),(625,430),(645,432)]]
    for points in paths:ImageDraw.Draw(corridor).line(points,fill=1,width=14,joint='curve')
    c=reference.astype(np.int16)
    ink=(c.min(-1)<175)&(c[...,0]-c[...,1]>20)
    mask |= ink&np.asarray(corridor,dtype=bool)
    return mask


def feature_rgba(rgb, polygon, kind):
    """Unmatte anti-aliased ink from skin; preserve eye interiors and tears."""
    domain=polygon if isinstance(polygon,np.ndarray) else polygon_mask(rgb.shape[:2],polygon)
    c=rgb.astype(np.float32)
    if kind=='brow':
        ink=(c.min(-1)<190)&(c[...,0]-c[...,1]>12)
    else:
        ink=((c.min(-1)<160) | ((c[...,0]-c[...,1]>45)&(c[...,1]-c[...,2]>25))
             | ((c[...,2]-c[...,0]>3)&(c.min(-1)<235)))
    ink &= domain
    lab,n=nd.label(ink,np.ones((3,3)))
    sizes=np.bincount(lab.ravel(),minlength=n+1)
    keep=sizes>=15;keep[0]=False
    ink=keep[lab]
    ink=nd.binary_fill_holes(nd.binary_closing(ink,iterations=1)) & domain
    # Include eye whites attached to their contour, not nearby skin rectangles.
    if kind=='eye':
        whites=((c.min(-1)>238)|((c[...,2]-c[...,1]>4)&(abs(c[...,0]-c[...,2])<18)&(c.min(-1)>150)))&domain
        ink=nd.binary_fill_holes(nd.binary_closing(ink|whites,iterations=1))&domain
    dist=nd.distance_transform_edt(~ink)
    support=(dist<=2.5)&domain
    # Soft outer alpha only; opaque feature interiors remain pixel-exact.
    alpha=np.where(ink,1.,np.exp(-dist*dist/0.7)) * support
    rgba=np.dstack([rgb,np.rint(alpha*255)]).astype(np.uint8)
    rgba[alpha==0]=0
    return Image.fromarray(rgba)


def extract_features(rgb, variant, physical=None, closed_reference=None):
    regions=REGIONS[variant]
    regions['brow_paths']=BROW_PATHS[variant]
    canvas=Image.new('RGBA',(rgb.shape[1],rgb.shape[0]))
    for role in ('eye_l','eye_r'):
        eye=np.asarray(feature_rgba(rgb,regions[role],'eye')).copy()
        eye[fringe_mask(rgb.shape[:2]) if physical is None else physical]=0
        labels,count=nd.label(eye[...,3]>128,np.ones((3,3)))
        sizes=np.bincount(labels.ravel(),minlength=count+1);sizes[0]=0
        keep=sizes>=max(20,int(sizes.max()*.02));keep[0]=False
        eye[~nd.binary_dilation(keep[labels],iterations=2)]=0
        canvas.alpha_composite(Image.fromarray(eye))
    for points,width in BROW_PATHS[variant]:
        mask=Image.new('1',canvas.size)
        ImageDraw.Draw(mask).line(points,fill=1,width=width,joint='curve')
        domain=np.asarray(mask,dtype=bool).copy()
        if closed_reference is not None:
            changed=np.abs(rgb.astype(np.int16)-closed_reference.astype(np.int16)).max(-1)>45
            # A brow can cross an unchanged hair stroke. Select connected ink
            # using changed pixels as seeds, rather than cutting out each
            # unchanged intersection and breaking the brow into fragments.
            c=rgb.astype(np.int16)
            ink=domain&(c.min(-1)<190)&(c[...,0]-c[...,1]>12)
            labels,count=nd.label(ink,np.ones((3,3)))
            hits=np.bincount(labels[changed&ink],minlength=count+1)
            keep=hits>=5;keep[0]=False
            domain &= nd.binary_dilation(keep[labels],iterations=2)
        canvas.alpha_composite(feature_rgba(rgb,domain,'brow'))
    canvas.alpha_composite(feature_rgba(rgb,regions['mouth'],'mouth'))
    bb=canvas.getbbox()
    if bb is None:raise ValueError('empty expression')
    return canvas.crop(bb),(bb[0],bb[1]),regions


def clean_face_base(rig, physical=None):
    """Remove residual old face ink without altering contour or cheek colors."""
    p=rig.parts['head_skin'];a=np.asarray(rig.images['head_skin']).copy()
    yy,xx=np.indices(a.shape[:2]);xx+=p['x'];yy+=p['y']
    c=a[...,:3].astype(np.int16)
    interior=nd.distance_transform_edt(a[...,3]>128)>1
    remove=np.zeros(a.shape[:2],bool)
    feature_mask=np.zeros(a.shape[:2],bool)
    for name in ('eye_ref_l','eye_ref_r','mouth_ref'):
        part=rig.parts[name]
        mask=Image.new('L',(a.shape[1],a.shape[0]))
        mask.paste(rig.images[name].getchannel('A'),(part['x']-p['x'],part['y']-p['y']))
        feature_mask |= np.asarray(mask)>4
        # The old plate already contains inpainted eye shadows outside the
        # cutout's alpha. Clear the entire window, not only visible eye ink.
        remove |= ((xx>=part['x'])&(xx<part['x']+part['size'][0])
                   &(yy>=part['y'])&(yy<part['y']+part['size'][1]))
    remove=nd.binary_dilation(remove,iterations=7)&interior
    remove |= (xx>320)&(xx<745)&(yy>415)&(yy<557)&interior
    remove |= ((c[...,0]-c[...,1]>30)&(c[...,1]<195)&(c.min(-1)>100)
               &(xx>350)&(xx<725)&(yy>398)&(yy<485)&interior)
    # Blush belongs to the fixed face plate, including its small darker strokes.
    pink=(c[...,0]>220)&(c[...,0]-c[...,1]>32)&(c[...,2]-c[...,1]>3)&(c[...,1]>125)&(yy>528)
    blush=nd.binary_fill_holes(nd.binary_closing(pink,iterations=3))
    remove &= ~nd.binary_dilation(blush,iterations=3)
    src=((c[...,0]>245)&(c[...,1]>216)&(c[...,1]<240)&(c[...,0]-c[...,1]>=16)
         &(c[...,0]-c[...,2]>18)&(c[...,2]<=c[...,1]+1)&(a[...,3]>250)&~remove&~blush)
    _,ix=nd.distance_transform_edt(~src,return_indices=True)
    fill=nd.gaussian_filter(a[...,:3][tuple(ix)].astype(np.float32),(18,18,0))
    blend=np.maximum(remove,nd.gaussian_filter(remove.astype(np.float32),2))
    blend[nd.binary_dilation(blush,iterations=2)]=0
    # Some fringe antialias pixels belong to the skin slice in the original
    # partition. Keep their color so cleaning the eye window cannot cut hair.
    fringe=Image.new('L',(a.shape[1],a.shape[0]))
    bp=rig.parts['bangs']
    fringe.paste(rig.images['bangs'].getchannel('A'),(bp['x']-p['x'],bp['y']-p['y']))
    near_fringe=nd.distance_transform_edt(np.asarray(fringe)<128)<4
    hair=(c.min(-1)<130)&~nd.binary_dilation(feature_mask,iterations=2)
    # Pink brows are facial ink; the dark contours on either side of the face
    # remain original even when the step-0 partition put them in head_skin.
    hair &= ~((c[...,0]>220)&(c.min(-1)>95))
    # Shared reference contours are restored by face_contour after composition.
    # Do not retain unidentified dark pixels here: many are old eyelid fragments.
    if physical is None:physical=refined_fringe_mask(np.asarray(rig.rest('smug').convert('RGB')))
    physical=physical[p['y']:p['y']+a.shape[0],p['x']:p['x']+a.shape[1]]
    # Hair now has its own complete texture; leave no stationary duplicate
    # outline in the skin beneath the swinging tips.
    blend[physical&(yy>=400)]=1
    # Geometry inferred from another expression must not erase the reference
    # cheek edge when the two outlines differ by a few pixels.
    blend[pink&(yy>560)]=0
    a[...,:3]=np.rint(a[...,:3]*(1-blend[...,None])+fill*blend[...,None]).clip(0,255)
    # Extend the occluded top of each blush oval. Existing visible blush and
    # its three pen strokes remain untouched; no old eye-shaped notch remains.
    for cx,cy,rx,ry,top in ((366,593,73,65,555),(674,558,65,57,537)):
        distance=np.sqrt(((xx-cx)/rx)**2+((yy-cy)/ry)**2)
        opacity=np.clip((1-distance)*35,0,1)
        opacity*=((yy<top)&interior&~blush&~hair)
        a[...,:3]=np.rint(a[...,:3]*(1-opacity[...,None])
                         +np.array([254,174,182])*opacity[...,None]).clip(0,255)
    return Image.fromarray(a)


def clean_hair_face_ink(rig, reference, base, physical=None):
    """Reassign the fringe/eye intersection from the exact reference pixels."""
    yy,xx=np.indices(reference.shape[:2])
    if physical is None:physical=refined_fringe_mask(reference)
    p=rig.parts['bangs'];a=np.asarray(rig.images['bangs']).copy()
    sl=(slice(p['y'],p['y']+a.shape[0]),slice(p['x'],p['x']+a.shape[1]))
    window=(xx>=302)&(xx<675)&(yy>=400)&(yy<505)
    a[window[sl]]=0
    restore=(physical&window)[sl]
    a[restore,:3]=reference[sl][restore];a[restore,3]=255
    return {'bangs':Image.fromarray(a)},base
