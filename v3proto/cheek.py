"""Local cheek surface, sampled once at full device resolution."""
import math
from collections import OrderedDict
import numpy as np
from PIL import Image
from scipy import ndimage as nd
from .motion import cheek_displacement,cheek_inverse,cheek_weight


class Cheek:
    def __init__(self, rig, scale):
        self.rig,self.scale=rig,scale
        self.config=rig.cheek_config
        self.assets=rig.cheek_images
        self.backgrounds={}
        self.protection={}
        self.eye_windows={}
        self.blink_protection=OrderedDict()
        self.textures={}
        self.texture_planes={}
        self.grids=OrderedDict()
        self.last_deformation = None  # One immutable material frame, not an animation cache.
        if self.config:
            self.x,self.y,self.right,self.bottom=self.config['box']

    def cut(self,image,origin,face):
        if not self.config:return image
        a=np.asarray(image).copy()
        mask=Image.new('L',image.size)
        mask.paste(self.assets[face]['mask'],(self.x-origin[0],self.y-origin[1]))
        clear=np.asarray(mask)>0
        yy,xx=np.indices(clear.shape);xx+=origin[0];yy+=origin[1]
        # Keep a small opaque overlap at pinned seams. Independent alpha
        # resampling on both sides otherwise opens a bright one-pixel line.
        clear &= (xx<self.config['root_x']-4)&(yy>self.config['vertical'][0]+2)&(yy<self.config['vertical'][-1]-2)
        a[clear]=0
        return Image.fromarray(a)

    def source_point(self,point,settings,pose):
        d=cheek_displacement(pose.pinch_delta,settings.pinch_maximum)
        x,y=cheek_inverse(np.asarray(point[0]),np.asarray(point[1]),d,settings.pinch_radius,self.config)
        return np.array([float(x),float(y)])

    def contains(self,point,settings,pose):
        if not self.config or not (settings.pinch or settings.lift):return False
        source=self.source_point(point,settings,pose)
        x,y=round(source[0]-self.x),round(source[1]-self.y)
        hit=self.assets[settings.expression]['hit']
        return 0<=x<hit.width and 0<=y<hit.height and hit.getpixel((x,y))>128

    def prepare(self,surface,settings):
        from .render import premultiplied,qimage
        from .animation import Pose
        face=settings.expression
        if face in self.backgrounds or not self.config:return
        size=(surface.w,surface.h)
        normal=surface._compose_image(settings,Pose())
        cut=surface._compose_image(settings,Pose(),True)
        normal=premultiplied(qimage(normal.resize(size,Image.Resampling.LANCZOS)))
        cut=premultiplied(qimage(cut.resize(size,Image.Resampling.LANCZOS)))
        difference=cut.astype(np.int16)-normal.astype(np.int16)
        rows,cols=np.where(np.any(difference,axis=-1))
        bounds=(cols.min(),rows.min(),cols.max()+1,rows.max()+1)
        x0,y0,x1,y1=bounds
        self.backgrounds[face]=(bounds,difference[y0:y1,x0:x1])
        reference=Image.new('RGBA',surface.reference_size)
        reference.alpha_composite(self.assets[face]['texture'],(self.x-surface.x,self.y-surface.y))
        self.textures[face]=premultiplied(qimage(reference.resize(size,Image.Resampling.LANCZOS)))
        self.texture_planes[face]=np.ascontiguousarray(np.moveaxis(self.textures[face],-1,0))
        mask=self.assets[face]['protect'].crop((surface.x,surface.y,surface.x+surface.reference_size[0],surface.y+surface.reference_size[1]))
        mask=np.asarray(mask.resize(size,Image.Resampling.NEAREST))>0
        yy,xx=np.indices(mask.shape,dtype=np.float32)
        gx=(xx+.5)/(surface.w/surface.reference_size[0])+surface.x-.5
        gy=(yy+.5)/(surface.h/surface.reference_size[1])+surface.y-.5
        mask|=cheek_weight(gx,gy,110,self.config)==0
        self.protection[face]=nd.binary_dilation(mask,iterations=1)
        # The left eye is the only one overlapping this local surface. Keep
        # its actual source window so the guard can follow the blink pivot.
        left=self.assets[face]['protect'].crop((0,0,520,self.rig.size[1]))
        box=left.getbbox()
        name=next(n for n in self.rig.face_parts(face) if self.rig.parts[n]['role']=='eye_l')
        self.eye_windows[face]=(left.crop(box),(box[0],box[1]),self.rig.parts[name]['blink_pivot'][1])

    def protection_for_pose(self,surface,face,eye_scale):
        if eye_scale==1:return self.protection[face]
        key=(face,round(eye_scale,5))
        if key not in self.blink_protection:
            eye,(x,y),pivot=self.eye_windows[face]
            eye=eye.resize((eye.width,max(1,round(eye.height*eye_scale))),Image.Resampling.NEAREST)
            target_y=round(pivot+(y-pivot)*eye_scale)
            mask=Image.new('L',surface.reference_size)
            mask.paste(eye,(x-surface.x,target_y-surface.y))
            mask=np.asarray(mask.resize((surface.w,surface.h),Image.Resampling.NEAREST))>0
            mask=nd.binary_dilation(mask,iterations=1)|self.protection[face]
            self.blink_protection[key]=mask
            if len(self.blink_protection)>32:self.blink_protection.popitem(last=False)
        self.blink_protection.move_to_end(key)
        return self.blink_protection[key]


    def apply(self,surface,settings,pose,original=None):
        key=(settings.expression,round(pose.eye_scale,5))
        self.prepare(surface,settings)
        if original is None:original=surface.frames[key]
        deformation_key = (settings.expression,tuple(pose.pinch_delta),settings.pinch_maximum,
                           settings.pinch_radius,pose.eye_scale)
        cached = self.last_deformation
        if cached is not None and cached[0] is original and cached[1] == deformation_key:
            return cached[2]
        out=original.copy()
        (bx0,by0,bx1,by1),difference=self.backgrounds[settings.expression]
        out[by0:by1,bx0:bx1]=np.clip(original[by0:by1,bx0:bx1].astype(np.int16)+difference,0,255).astype(np.uint8)
        d=cheek_displacement(pose.pinch_delta,settings.pinch_maximum)
        scale_x=surface.w/surface.reference_size[0]
        scale_y=surface.h/surface.reference_size[1]
        x0=max(0,math.floor((self.x+min(0,d[0])-surface.x)*self.scale)-2)
        y0=max(0,math.floor((self.y-24-surface.y)*self.scale)-2)
        x1=min(surface.w,math.ceil((self.right+12-surface.x)*self.scale)+2)
        y1=min(surface.h,math.ceil((self.bottom+24-surface.y)*self.scale)+2)
        grid_key=(x0,y0,x1,y1)
        if grid_key not in self.grids:
            yy,xx=np.indices((y1-y0,x1-x0),dtype=np.float32)
            gx=(xx+x0+.5)/scale_x+surface.x-.5
            gy=(yy+y0+.5)/scale_y+surface.y-.5
            h,w=gx.shape
            mx=np.linspace(gx[0,0],gx[0,-1],max(2,(w+3)//4+1),dtype=np.float32)
            my=np.linspace(gy[0,0],gy[-1,0],max(2,(h+3)//4+1),dtype=np.float32)
            cx,cy=np.meshgrid(mx,my)
            self.grids[grid_key]=(yy,xx,cx,cy)
            if len(self.grids)>128:self.grids.popitem(last=False)
        self.grids.move_to_end(grid_key)
        yy,xx,cx,cy=self.grids[grid_key]
        h,w=yy.shape
        if d[1]==0:
            sx=horizontal_inverse(cx,cy,d[0],settings.pinch_radius,self.config)
            sy=cy
        else:
            sx,sy=cheek_inverse(cx,cy,d,settings.pinch_radius,self.config,iterations=12)
        dx=nd.zoom(cx-sx,(h/cx.shape[0],w/cx.shape[1]),order=1,prefilter=False)
        dy=nd.zoom(cy-sy,(h/cx.shape[0],w/cx.shape[1]),order=1,prefilter=False) if d[1] else 0.
        coords=np.array([yy+y0-dy*scale_y,xx+x0-dx*scale_x],dtype=np.float32)
        from .sampling import sample_rgba
        patch=sample_rgba(self.texture_planes[settings.expression],coords[1],coords[0],planar=True)
        dest=out[y0:y1,x0:x1]
        from .sampling import source_over
        source_over(out,patch,x0,y0)
        protect=self.protection_for_pose(surface,settings.expression,pose.eye_scale)[y0:y1,x0:x1]
        dest[protect]=original[y0:y1,x0:x1][protect]
        # Partitioned alpha has a slightly different rasterization at the old
        # boundary. Fade over two reference pixels so entry/release are C1.
        u=min(1.,float(np.linalg.norm(d))/2)
        if u<1:
            weight=u*u*(3-2*u)
            dest[:]=np.rint(original[y0:y1,x0:x1]*(1-weight)+dest*weight).astype(np.uint8)
        # Callers add faces / motion into their own buffers. Holding the source
        # reference also prevents object-id reuse from producing a false hit.
        out.flags.writeable = False
        self.last_deformation = (original,deformation_key,out)
        return out


def bilinear_rgba(a,x,y):
    """Full-resolution premultiplied bilinear C sampling."""
    from .sampling import sample_rgba
    return sample_rgba(a,x,y)


def horizontal_inverse(x,y,dx,radius,region):
    """Invert monotone row curves on a one-reference-pixel source grid."""
    if dx==0:return x
    left=math.floor(float(x.min())+min(0,-dx))-1
    right=math.ceil(float(x.max())+max(0,-dx))+1
    source=np.arange(left,right+1,dtype=np.float32)
    xx,yy=np.meshgrid(source,y[:,0])
    forward=xx+dx*cheek_weight(xx,yy,radius,region)
    return np.array([np.interp(target,row,source) for target,row in zip(x,forward)],dtype=np.float32)


class StaticCheekSurface:
    """Apply the same local cage to the exact all-animations-off rest frame."""
    def __init__(self,renderer):
        self.renderer=renderer
        self.r=renderer
        self.x=self.y=0
        self.reference_size=renderer.rig.size
        self.w,self.h=(round(v*renderer.scale) for v in self.reference_size)
        self.frames={}
        self.cheek=Cheek(renderer.rig,renderer.scale)
        from .reaction_face import ReactionFace
        self.reaction_face=ReactionFace(self)
        self.motion_weights=None

    def _compose_image(self,settings,pose,cut_cheek=False):
        image=self.renderer.rig.rest(settings.expression)
        if cut_cheek:
            head=self.renderer.head_surface
            background=head._compose_image(settings,pose,True)
            box=self.cheek.config['box']
            local=tuple(v-(head.x if i%2==0 else head.y) for i,v in enumerate(box))
            background=background.crop(local)
            mask=self.cheek.assets[settings.expression]['mask'].point(lambda a:255 if a else 0)
            image.paste(background,(box[0],box[1]),mask)
        return image

    def render(self,settings,pose):
        from .animation import Pose
        from .render import premultiplied,from_premultiplied
        key=(settings.expression,1.)
        self.frames[key]=premultiplied(self.renderer.render(settings,Pose()))
        original=self.frames[key]
        pixels=self.reaction_face.erase(original,settings) if pose.reaction_face is not None else original
        if any(pose.pinch_delta):pixels=self.cheek.apply(self,settings,pose,original=pixels)
        if pose.reaction_face is not None:
            pixels=self.reaction_face.apply(pixels,settings,pose,original=original)
            pixels=self.reaction_motion(pixels,pose)
        return from_premultiplied(pixels)

    def reaction_motion(self,pixels,pose):
        """Move the exact static composite when the ordinary motions are off.

        Only secondary body/arm/head motion is added; local cheek sampling and
        facial overlay are identical to the ordinary animated path.
        """
        from .render import BODY, LEGS
        from .motion import pivot_matrix,translation
        if (pose.body_scale==1 and pose.head_y==0 and pose.arm_degrees==0
                and pose.head_roll==0 and pose.leg_degrees==0 and pose.body_roll==0 and pose.head_x==0):
            return pixels
        rig=self.r.rig
        scale_x=self.w/rig.size[0];scale_y=self.h/rig.size[1]
        if self.motion_weights is None:
            owner=Image.new('L',rig.size)
            for n in rig.active('smug'):
                p=rig.parts[n]
                if p.get('role'):continue
                if p['source']=='gpt_underlay' and n not in BODY:continue
                label=(5 if n=='leg_l' else 6 if n=='leg_r' else
                       3 if n=='arm_l' else 4 if n=='arm_r' else 2 if n in BODY else 1)
                owner.paste(label,(p['x'],p['y'],p['x']+p['size'][0],p['y']+p['size'][1]),rig.images[n].getchannel('A').point(lambda a:255 if a>128 else 0))
            a=np.asarray(owner);alpha=np.asarray(rig.rest('smug'))[...,3]>128
            _,near=nd.distance_transform_edt(~alpha,return_indices=True)
            a=a[tuple(near)]
            self.motion_weights=[nd.gaussian_filter(np.asarray(Image.fromarray((a==i).astype(np.float32)).resize((self.w,self.h),Image.Resampling.NEAREST)),2) for i in range(1,7)]
        xs=np.append(np.arange(0,self.w,24),self.w)
        ys=np.append(np.arange(0,self.h,24),self.h)
        mx,my=np.meshgrid(xs,ys)
        gx=mx/scale_x;gy=my/scale_y
        hip=(np.array(rig.pivots['hip_l'])+rig.pivots['hip_r'])/2
        body=pivot_matrix(hip,pose.body_roll,sy=pose.body_scale)
        head=translation(pose.head_x,pose.head_y) @ pivot_matrix(rig.pivots['neck'],pose.head_roll)
        matrices=(head,body,body @ pivot_matrix(rig.pivots['shoulder_l'],pose.arm_degrees),
                  body @ pivot_matrix(rig.pivots['shoulder_r'],-pose.arm_degrees),
                  pivot_matrix(rig.pivots['hip_l'],pose.leg_degrees),
                  pivot_matrix(rig.pivots['hip_r'],-pose.leg_degrees))
        ox=mx.astype(float);oy=my.astype(float)
        for weight,m in zip(self.motion_weights,matrices):
            inv=np.linalg.inv(m)
            w=nd.map_coordinates(weight,[my,mx],order=1,mode='nearest')
            ox+=(inv[0,0]*gx+inv[0,1]*gy+inv[0,2]-gx)*scale_x*w
            oy+=(inv[1,0]*gx+inv[1,1]*gy+inv[1,2]-gy)*scale_y*w
        boxes=[(int(x0),int(y0),int(x1),int(y1)) for y0,y1 in zip(ys[:-1],ys[1:]) for x0,x1 in zip(xs[:-1],xs[1:])]
        quads=np.stack((ox[:-1,:-1],oy[:-1,:-1],ox[1:,:-1],oy[1:,:-1],ox[1:,1:],oy[1:,1:],ox[:-1,1:],oy[:-1,1:]),axis=-1)
        image=Image.frombytes('RGBa',(self.w,self.h),pixels.tobytes())
        return np.asarray(image.transform(image.size,Image.Transform.MESH,list(zip(boxes,quads.reshape(-1,8).tolist())),Image.Resampling.BILINEAR))
