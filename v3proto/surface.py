"""Continuous head deformation: neighboring cuts share a single surface."""
from collections import OrderedDict
from dataclasses import replace

import numpy as np
from PIL import Image
from scipy import ndimage as nd

from .motion import rooted_rotation_inverse
from .sampling import warp_mesh


class HeadSurface:
    def __init__(self, renderer):
        from .render import BODY, LEGS
        self.r=renderer
        rig=renderer.rig
        self.names=[n for n in rig.active('smug') if n not in BODY|LEGS
                    and rig.parts[n]['source']!='gpt_underlay' and not rig.parts[n].get('role')]
        self.moving=('bangs','ahoge','flower','side_hair_l','side_hair_r','ribbon')
        self.body_names=[n for n in rig.active('smug') if n in BODY|LEGS]
        # At rest these reference slices already reconstruct the exact artwork.
        # Never independently clean their RGB: deform their completed composite.
        alpha=np.zeros(rig.size[::-1],np.uint8)
        owner=np.zeros(rig.size[::-1],np.uint8)
        for n in self.names:
            p=rig.parts[n]
            image=rig.face_hair_images.get(n,rig.images[n])
            a=np.asarray(image)[...,3]
            sl=(slice(p['y'],p['y']+a.shape[0]),slice(p['x'],p['x']+a.shape[1]))
            alpha[sl]=np.maximum(alpha[sl],a)
            owner[sl][a>128]=self.moving.index(n)+1 if n in self.moving else 0
        # Eye/mouth are fixed with the skin. Full fringe texture above them owns
        # the tips which used to be mistakenly included in the eye cutouts.
        ys,xs=np.where(alpha>128)
        scale=renderer.scale
        self.x=max(0,int(xs.min())-32);self.y=max(0,int(ys.min())-32)
        self.w=round((min(rig.size[0],int(xs.max())+33)-self.x)*scale)
        self.h=round((min(rig.size[1],int(ys.max())+33)-self.y)*scale)
        self.reference_size=(min(rig.size[0],int(xs.max())+33)-self.x,
                             min(rig.size[1],int(ys.max())+33)-self.y)
        # The smooth coordinate field uses a third-device-resolution grid;
        # artwork is rasterized at full resolution through a shared 2D mesh.
        self.mesh_w=(self.w+2)//3;self.mesh_h=(self.h+2)//3
        self.step_x=self.w/self.mesh_w;self.step_y=self.h/self.mesh_h
        yy,xx=np.indices((self.mesh_h,self.mesh_w),dtype=np.float32)
        xx=(xx+.5)*self.step_x-.5;yy=(yy+.5)*self.step_y-.5
        self.gx=xx/scale+self.x;self.gy=yy/scale+self.y
        # Extend edge ownership into empty space so the outer contour can move.
        _,nearest=nd.distance_transform_edt(alpha<128,return_indices=True)
        labels=owner[tuple(nearest)]
        ix=np.clip(self.gx.astype(int),0,rig.size[0]-1)
        iy=np.clip(self.gy.astype(int),0,rig.size[1]-1)
        labels=labels[iy,ix]
        # A 28-reference-pixel blend band also keeps opposite 3-degree motions
        # from folding the shared surface at a neighboring part's boundary.
        self.weights={n:nd.gaussian_filter((labels==i+1).astype(np.float32),(max(.5,(22 if n=='ahoge' else 14)*scale*2/self.step_y),max(.5,(22 if n=='ahoge' else 14)*scale*2/self.step_x)))
                      for i,n in enumerate(self.moving)}
        self.fields={n:OrderedDict() for n in self.moving}
        self.frames=OrderedDict()
        self.meshes=OrderedDict()
        self.occupancy=None
        self.mesh_x=np.append(np.arange(0,self.w,24),self.w)
        self.mesh_y=np.append(np.arange(0,self.h,24),self.h)
        self.mx,self.my=np.meshgrid(self.mesh_x,self.mesh_y)
        self.mesh_coordinates=np.array([(self.my+.5)/self.step_y-.5,
                                        (self.mx+.5)/self.step_x-.5],dtype=np.float32)
        self.boxes=[(int(x0),int(y0),int(x1),int(y1))
                    for y0,y1 in zip(self.mesh_y[:-1],self.mesh_y[1:])
                    for x0,x1 in zip(self.mesh_x[:-1],self.mesh_x[1:])]

        from .cheek import Cheek
        self.cheek=Cheek(rig,scale)
        from .reaction_face import ReactionFace
        self.reaction_face=ReactionFace(self)

    def coordinates(self,pose):
        rig=self.r.rig
        dx=np.zeros_like(self.gx);dy=np.zeros_like(self.gy)
        for n in self.moving:
            angle=round(pose.angles.get(n,0)*10)/10
            # Ribbon shares its flower's root rotation, then bends locally.
            flower=round(pose.angles.get('flower',0)*10)/10 if n=='ribbon' else 0
            if not angle and not flower:continue
            key=(angle,flower);cache=self.fields[n]
            if key not in cache:
                p=rig.parts[n];root=rig.pivots[p['pivot']]
                x,y=self.gx,self.gy
                if n=='bangs':
                    sx,sy=rooted_rotation_inverse(x,y,root,angle,rig.seam)
                else:
                    sx,sy=x,y
                    if n in ('ahoge','flower') or flower:
                        pivot=rig.pivots['flower_root'] if flower else root
                        theta=np.deg2rad(-(flower or angle))
                        c,s=np.cos(theta),np.sin(theta)
                        sx=pivot[0]+c*(x-pivot[0])-s*(y-pivot[1])
                        sy=pivot[1]+s*(x-pivot[0])+c*(y-pivot[1])
                    if n in ('side_hair_l','side_hair_r','ribbon'):
                        length=max(1,p['y']+p['size'][1]-root[1])
                        u=np.clip((sy-root[1])/length,0,1)
                        sx=sx-np.tan(np.deg2rad(angle))*length*u*u
                # float32: half the memory of this 6×24-entry cache (S7); sub-1e-4 px difference
                cache[key]=(((sx-x)*self.weights[n]).astype(np.float32),((sy-y)*self.weights[n]).astype(np.float32))
                if len(cache)>24:cache.popitem(last=False)
            cache.move_to_end(key)
            x,y=cache[key];dx+=x;dy+=y
        return (self.gx+dx-self.x)*self.r.scale,(self.gy+dy-self.y)*self.r.scale

    def compose(self,settings,pose):
        from .render import premultiplied,qimage
        # The reaction replaces both original eyes; never build and blink a
        # second, invisible copy of the selected expression underneath it.
        material_pose=replace(pose,eye_scale=1.) if pose.reaction_face is not None else pose
        key=(settings.expression,round(material_pose.eye_scale,5))
        if key not in self.frames:
            full=self._compose_image(settings,material_pose)
            self.frames[key]=premultiplied(qimage(full.resize((self.w,self.h),Image.Resampling.LANCZOS)))
            if len(self.frames)>64:self.frames.popitem(last=False)
        self.frames.move_to_end(key)
        if settings.pinch and self.cheek.config:self.cheek.prepare(self,settings)
        original=self.frames[key]
        pixels=self.reaction_face.erase(original,settings) if pose.reaction_face is not None else original
        if settings.pinch and any(pose.pinch_delta) and self.cheek.config:
            pixels=self.cheek.apply(self,settings,material_pose,original=pixels)
        if pose.reaction_face is not None:
            pixels=self.reaction_face.apply(pixels,settings,pose,original=original)
        return pixels

    def _compose_image(self,settings,pose,cut_cheek=False):
        from .face import reference_face,brows_image,plate_face
        rig=self.r.rig
        full=Image.new('RGBA',self.reference_size)
        mirror=self.cheek.mirror
        if mirror is not None:
            # The old left cheek was removed from the hair slices for good;
            # show the hidden hair there instead of an empty hole.
            left=rig.left_cheek_images[settings.expression]['mask']
            full.alpha_composite(self._hidden_hair(left,rig.cheek_config['box'][:2]))
        if cut_cheek and self.cheek.config:
            # Reveal the existing hidden hair only where the cheek was removed.
            full.alpha_composite(self._hidden_hair(self.cheek.assets[settings.expression]['mask'],
                                                   (self.cheek.x,self.cheek.y),mirrored=mirror is not None))
        first_side_hair=next(n for n in self.names if n in ('side_hair_l','side_hair_r'))
        for n in self.names:
            if n==first_side_hair:
                cover=Image.new('RGBA',full.size)
                for body in self.body_names:
                    p=rig.parts[body]
                    cover.alpha_composite(rig.images[body],(p['x']-self.x,p['y']-self.y))
                alpha=np.asarray(full.getchannel('A')).astype(np.uint16)
                alpha=alpha*(255-np.asarray(cover.getchannel('A')).astype(np.uint16))//255
                full.putalpha(Image.fromarray(alpha.astype(np.uint8)))
            p=rig.parts[n]
            image=((rig.face_base if rig.face_plate else reference_face(rig,settings.expression,pose.eye_scale))
                   if n=='head_skin' else rig.face_hair_images.get(n,rig.images[n]))
            # The source partition assigned parts of the cheek outline to
            # bangs and side hair too. Remove the old contour from every
            # owner before adding its transported copy.
            if cut_cheek:
                image=self.cheek.cut(image,(p['x'],p['y']),settings.expression)
            full.alpha_composite(image,(p['x']-self.x,p['y']-self.y))
            if n=='bangs':
                if rig.face_plate:
                    plate,origin=plate_face(rig,settings.expression,pose.eye_scale)
                    if cut_cheek:plate=self.cheek.cut(plate,origin,settings.expression)
                    full.alpha_composite(plate,(origin[0]-self.x,origin[1]-self.y))
                    continue
                if rig.face_contour is not None:full.alpha_composite(rig.face_contour,(-self.x,-self.y))
                brow=brows_image(rig,settings.expression)
                if brow:full.alpha_composite(brow[0],(brow[1][0]-self.x,brow[1][1]-self.y))
        return full

    def _hidden_hair(self,mask_image,origin,mirrored=False):
        """Underlay hair (skin-colored pixels removed) limited to a cheek mask."""
        rig=self.r.rig
        p=rig.parts['back_hair_under'];image=rig.images['back_hair_under'];x=p['x']
        if mirrored:
            from PIL import ImageOps
            from .mirror import flipped_origin
            image=ImageOps.mirror(image);x=flipped_origin(rig.mirror_sum,x,image.width)
        under=np.asarray(image).copy()
        color=under[...,:3].astype(int)
        under[(color[...,0]-color[...,1]<=12)&(color.max(-1)>80),3]=0
        backing=Image.new('RGBA',self.reference_size)
        backing.alpha_composite(Image.fromarray(under),(x-self.x,p['y']-self.y))
        mask=Image.new('L',self.reference_size)
        mask.paste(mask_image,(origin[0]-self.x,origin[1]-self.y))
        a=np.asarray(backing).copy();a[np.asarray(mask)==0]=0
        return Image.fromarray(a)

    def render(self,settings,pose,fractional=(0.,0.)):
        from .render import from_premultiplied
        a=self.compose(settings,pose)
        moving=any(round(v*10) for v in pose.angles.values()) or bool(pose.head_roll)
        if not moving and not any(fractional):return from_premultiplied(a)
        image=Image.frombytes('RGBa',(self.w,self.h),a)
        fx,fy=fractional
        if moving:
            mesh,_,_=self.mesh(pose)
            if fx or fy:
                quads=np.asarray([quad for _,quad in mesh])-np.tile([fx,fy],4)
                mesh=list(zip(self.boxes,quads.tolist()))
            # Empty source rectangles cannot contribute any visible pixel.
            # Avoid hundreds of Python/Pillow calls for transparent cells.
            if self.occupancy is None:
                occupied=a[...,3]>0
                if self.cheek.config:
                    outward,inward=self.cheek.stretch_extent()
                    x0=max(0,int((self.cheek.x-outward-self.x)*self.r.scale))
                    x1=min(self.w,int((self.cheek.right+inward-self.x)*self.r.scale)+1)
                    y0=max(0,int((self.cheek.y-26-self.y)*self.r.scale))
                    y1=min(self.h,int((self.cheek.bottom+26-self.y)*self.r.scale)+1)
                    occupied[y0:y1,x0:x1]=True
                occupied=nd.binary_dilation(occupied,iterations=2)
                self.occupancy=np.pad(occupied.cumsum(0,dtype=np.int32).cumsum(1,dtype=np.int32),((1,0),(1,0)))
            mesh=self.visible_cells(mesh,a[...,3],self.occupancy)
            warped=warp_mesh(image,mesh)
        else:
            warped=image.transform(image.size,Image.Transform.AFFINE,(1,0,-fx,0,1,-fy),Image.Resampling.BILINEAR)
        return from_premultiplied(np.asarray(warped))

    @staticmethod
    def visible_cells(mesh,alpha,integral=None):
        quads=np.asarray([quad for _,quad in mesh]).reshape(-1,4,2)
        low=np.floor(quads.min(axis=1)).astype(int)-2
        high=np.ceil(quads.max(axis=1)).astype(int)+3
        height,width=alpha.shape
        x0=np.clip(low[:,0],0,width);y0=np.clip(low[:,1],0,height)
        x1=np.clip(high[:,0],0,width);y1=np.clip(high[:,1],0,height)
        if integral is None:integral=np.pad((alpha>0).cumsum(0,dtype=np.int32).cumsum(1,dtype=np.int32),((1,0),(1,0)))
        occupied=integral[y1,x1]-integral[y0,x1]-integral[y1,x0]+integral[y0,x0]
        return [cell for cell,keep in zip(mesh,occupied>0) if keep]

    def mesh(self,pose):
        key=tuple(round(pose.angles.get(n,0)*10) for n in self.moving)+(round(pose.head_roll,4),)
        if key in self.meshes:
            self.meshes.move_to_end(key)
            return self.meshes[key]
        x,y=self.coordinates(pose)
        dx=x-(self.gx-self.x)*self.r.scale
        dy=y-(self.gy-self.y)*self.r.scale
        # Shared corner coordinates make adjacent cells meet exactly. This is
        # a 2D continuous displacement mesh, not independently shifted strips.
        mx,my=self.mx,self.my
        coords=self.mesh_coordinates
        if pose.head_roll:
            root=self.r.rig.pivots['neck']
            rx=(root[0]-self.x)*self.r.scale;ry=(root[1]-self.y)*self.r.scale
            theta=np.deg2rad(-pose.head_roll);c,s=np.cos(theta),np.sin(theta)
            mx=rx+c*(self.mx-rx)-s*(self.my-ry)
            my=ry+s*(self.mx-rx)+c*(self.my-ry)
            coords=np.array([(my+.5)/self.step_y-.5,(mx+.5)/self.step_x-.5],dtype=np.float32)
        ox=mx+nd.map_coordinates(dx,coords,order=1,mode='nearest')
        oy=my+nd.map_coordinates(dy,coords,order=1,mode='nearest')
        quads=np.stack((ox[:-1,:-1],oy[:-1,:-1],ox[1:,:-1],oy[1:,:-1],
                        ox[1:,1:],oy[1:,1:],ox[:-1,1:],oy[:-1,1:]),axis=-1)
        result=(list(zip(self.boxes,quads.reshape(-1,8).tolist())),ox,oy)
        self.meshes[key]=result
        if len(self.meshes)>16:self.meshes.popitem(last=False)
        return result

    def source_point(self,point,pose,allow_outside=False):
        x=(point[0]-pose.head_x-self.x)*self.r.scale
        y=(point[1]-pose.head_y-self.y)*self.r.scale
        if not allow_outside and not (0<=x<self.w and 0<=y<self.h):return None
        raw_x,raw_y=x,y
        x=float(np.clip(x,0,self.w));y=float(np.clip(y,0,self.h))
        _,sx,sy=self.mesh(pose)
        i=min(len(self.mesh_x)-2,np.searchsorted(self.mesh_x,x,side='right')-1)
        j=min(len(self.mesh_y)-2,np.searchsorted(self.mesh_y,y,side='right')-1)
        u=(x-self.mesh_x[i])/(self.mesh_x[i+1]-self.mesh_x[i])
        v=(y-self.mesh_y[j])/(self.mesh_y[j+1]-self.mesh_y[j])
        def at(field):
            return ((1-u)*(1-v)*field[j,i]+u*(1-v)*field[j,i+1]
                    +(1-u)*v*field[j+1,i]+u*v*field[j+1,i+1])
        return np.array([(at(sx)+raw_x-x)/self.r.scale+self.x,(at(sy)+raw_y-y)/self.r.scale+self.y])
