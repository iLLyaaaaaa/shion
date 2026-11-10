"""Erase the source expression before deforming, then paint reaction glyphs."""
from collections import OrderedDict
import numpy as np
from PIL import Image
from scipy import ndimage as nd

from .face import plate_face, complete_eye

MASK_CACHE = 8


class ReactionFace:
    def __init__(self, surface):
        self.surface = surface
        self.cache = OrderedDict()
        self.masks = {}
        self.erased = {}

    def feature_mask(self, face, eye_scale):
        """Only current reaction glyphs; never include the old cheek contour."""
        key = (face, round(eye_scale, 5))
        if key in self.masks:
            return self.masks[key]
        rig = self.surface.r.rig
        blank, origin = rig.face_plate
        mask = Image.new('L', blank.size)
        mouth_mask = Image.new('L', blank.size)
        for name in rig.face_parts(face):
            p = rig.parts[name]
            eye = p['role'].startswith('eye')
            image = complete_eye(rig, name) if eye else rig.feature_images.get(name, rig.images[name])
            x, y = p['x'], p['y']
            if eye and eye_scale != 1:
                pivot = p['blink_pivot'][1]
                y = round(pivot + (y - pivot) * eye_scale)
                image = image.resize((image.width, max(1, round(image.height * eye_scale))), Image.Resampling.LANCZOS)
            alpha = Image.new('L', blank.size)
            alpha.paste(image.getchannel('A'), (x-origin[0], y-origin[1]))
            if eye:mask = Image.fromarray(np.maximum(np.asarray(mask), np.asarray(alpha)))
            else:mouth_mask = Image.fromarray(np.maximum(np.asarray(mouth_mask), np.asarray(alpha)))
        a = nd.binary_dilation(np.asarray(mask) > 2, iterations=2)
        if rig.fringe_mask is not None:
            box = (origin[0],origin[1],origin[0]+blank.width,origin[1]+blank.height)
            a &= np.asarray(rig.fringe_mask.crop(box)) == 0
        # Brows deliberately cross the hair and must not be clipped as eyes.
        a |= nd.binary_dilation(np.asarray(mouth_mask)>2,iterations=2)
        result = Image.fromarray(a.astype(np.uint8) * 255)
        self.masks[key] = result
        # Masks are only inputs to cached patches (S7: 64 -> 8 entries, ~0.2MB each).
        if len(self.masks) > MASK_CACHE:self.masks.pop(next(iter(self.masks)))
        return result

    def erasure_mask(self, face):
        """Source eye windows include ink/shadows missing from blink cutouts.

        Source fringe ownership keeps real hair; the common blink fringe mask
        misclassifies a strip of the original smug eyelid as hair.
        """
        key = (face, 'erase')
        if key not in self.masks:
            rig = self.surface.r.rig
            blank, origin = rig.face_plate
            mask = Image.new('L', blank.size)
            mouth_mask = Image.new('L',blank.size)
            if rig.cheek_config and face=='smug':
                box = (*origin,origin[0]+blank.width,origin[1]+blank.height)
                mask = rig.cheek_images[face]['protect'].crop(box)
            for name in rig.face_parts(face):
                p = rig.parts[name]
                image = rig.feature_images.get(name,rig.images[name])
                alpha = Image.new('L',blank.size)
                alpha.paste(image.getchannel('A'),(p['x']-origin[0],p['y']-origin[1]))
                if p['role'].startswith('eye'):
                    mask = Image.fromarray(np.maximum(np.asarray(mask),np.asarray(alpha)))
                else:mouth_mask = Image.fromarray(np.maximum(np.asarray(mouth_mask),np.asarray(alpha)))
            a = nd.binary_dilation(np.asarray(mask)>2,iterations=2)
            physical = rig.source_fringe_mask if face=='smug' else rig.fringe_mask
            if physical is not None:
                box = (*origin,origin[0]+blank.width,origin[1]+blank.height)
                a &= np.asarray(physical.crop(box)) == 0
            a |= nd.binary_dilation(np.asarray(mouth_mask)>2,iterations=2)
            source=np.asarray(plate_face(rig,face,1)[0]).astype(int)
            yy,xx=np.indices(a.shape);xx+=origin[0];yy+=origin[1]
            orange=(source[...,0]>230)&(source[...,0]-source[...,1]>65)&(source[...,1]>90)&(source[...,1]<200)&(source[...,2]<160)
            a &= ~(orange&(xx<390)&(yy<490))
            result = Image.fromarray(a.astype(np.uint8)*255)
            self.masks[key] = result
            if len(self.masks) > MASK_CACHE:self.masks.pop(next(iter(self.masks)))
            return result
        return self.masks[key]

    def patch(self, face, eye_scale=1., erase=False):
        from .render import premultiplied,qimage
        key = (face,round(eye_scale,5),erase)
        if key not in self.cache:
            surface = self.surface
            rig = surface.r.rig
            blank, origin = rig.face_plate
            mask = self.erasure_mask(face) if erase else self.feature_mask(face,eye_scale)
            plate = blank if erase else plate_face(rig,face,eye_scale)[0]
            if erase and face=='smug' and rig.fringe_mask is not None and rig.source_fringe_mask is not None:
                # The shared closed-eye plate has a longer hair tip here than
                # the user's smug source. It cannot serve as skin under the
                # removed original eyelid: borrow nearby clean skin instead.
                box=(*origin,origin[0]+blank.width,origin[1]+blank.height)
                common=np.asarray(rig.fringe_mask.crop(box))>0
                physical=np.asarray(rig.source_fringe_mask.crop(box))>0
                repair=common&~physical&(np.asarray(mask)>0)
                a=np.asarray(plate).copy();c=a[...,:3].astype(int)
                skin=(c[...,0]>245)&(c[...,1]>210)&(c[...,2]>200)&(c[...,0]-c[...,1]>12)&(c[...,0]-c[...,1]<45)&~physical&~repair
                _,nearest=nd.distance_transform_edt(~skin,return_indices=True)
                fill=nd.gaussian_filter(a[...,:3][tuple(nearest)].astype(np.float32),(1.5,1.5,0))
                a[repair,:3]=np.rint(fill[repair]).astype(np.uint8)
                plate=Image.fromarray(a)
            replacement = Image.new('RGBA',surface.reference_size)
            replacement.alpha_composite(plate,(origin[0]-surface.x,origin[1]-surface.y))
            full_mask = Image.new('L',surface.reference_size)
            full_mask.paste(mask,(origin[0]-surface.x,origin[1]-surface.y))
            device_mask = np.asarray(full_mask.resize((surface.w,surface.h),Image.Resampling.LANCZOS),dtype=np.float32)/255.
            image = premultiplied(qimage(replacement.resize((surface.w,surface.h),Image.Resampling.LANCZOS)))
            ys,xs = np.where(device_mask>0)
            box = (xs.min(),ys.min(),xs.max()+1,ys.max()+1)
            x0,y0,x1,y1 = box
            mask=device_mask[y0:y1,x0:x1,None]
            replacement=image[y0:y1,x0:x1]
            alpha=mask*replacement[...,3,None].astype(np.float32)/255.
            self.cache[key] = (box,1-alpha,replacement*mask)
            if len(self.cache)>40:self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    @staticmethod
    def paint(pixels, patch):
        (x0,y0,x1,y1),remaining,source = patch
        out = pixels.copy()
        dest = out[y0:y1,x0:x1]
        # A plate feathers into hair. Masked replacement would punch its
        # partial alpha into an opaque head and make pale checkerboard holes.
        dest[:] = np.minimum(255,np.rint(dest*remaining+source)).astype(np.uint8)
        return out

    def erase(self,pixels,settings):
        face=settings.expression
        cached=self.erased.get(face)
        if cached is None or cached[0] is not pixels:
            cached=(pixels,self.paint(pixels,self.patch(face,erase=True)))
            self.erased[face]=cached
        return cached[1]

    def apply(self,pixels,settings,pose,original=None):
        target = self.patch(pose.reaction_face,pose.eye_scale)
        out = self.paint(pixels,target)
        if pose.reaction_fade and original is not None:
            base = self.patch(settings.expression,erase=True)
            a,b = base[0],target[0]
            x0,y0,x1,y1 = min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])
            dest = out[y0:y1,x0:x1]
            fade = pose.reaction_fade
            dest[:] = np.rint(dest*(1-fade)+original[y0:y1,x0:x1]*fade).astype(np.uint8)
        return out
