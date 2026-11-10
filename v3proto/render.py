"""Rig loading and shared offscreen/window renderer. No shion imports."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter, QTransform

from .animation import Pose, Settings
from .motion import bend_inverse, pivot_matrix, transform_point, translation, rooted_rotation_inverse
from .face import brows_image, without_brows, eye_image
from .lift import root_matrix
from .tickle import in_belly


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RIG = ROOT / "assets" / "sprites" / "v3" / "rig.json"
BENDING = {"side_hair_l", "side_hair_r", "ribbon"}
ROTATING = {"bangs", "ahoge", "flower"}
BODY = {"body", "body_under", "arm_l", "arm_r"}
LEGS = {"leg_l", "leg_r"}


def qimage(image: Image.Image) -> QImage:
    a = np.ascontiguousarray(image.convert("RGBA"))
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_RGBA8888).copy()


def to_pil(image: QImage) -> Image.Image:
    im = image.convertToFormat(QImage.Format.Format_RGBA8888)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())
    return Image.fromarray(a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).copy())


def premultiplied(image: QImage) -> np.ndarray:
    im = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())
    return a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).copy()


def from_premultiplied(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0],
                  QImage.Format.Format_RGBA8888_Premultiplied).copy()


def sample(a: np.ndarray, x, y) -> QImage:
    coords = np.asarray([y, x], dtype=np.float32)
    out = np.empty((*x.shape, 4), np.uint8)
    for c in range(4):
        nd.map_coordinates(a[..., c], coords, output=out[..., c], order=1,
                           mode="constant", cval=0, prefilter=False)
    return from_premultiplied(out)



class Rig:
    def __init__(self, path=DEFAULT_RIG, cheek_side='left'):
        path = Path(path)
        self.mirror_sum = None
        self.data = json.loads(path.read_text(encoding="utf-8"))
        if self.data.get("version") != 2:
            raise ValueError("V3 prototype requires rig version 2")
        self.size = tuple(self.data["canvas"])
        self.parts = self.data["parts"]
        self.pivots = self.data["pivots"]
        self.faces = tuple(self.data["slots"]["face"])
        self.order = sorted(self.parts, key=lambda n: self.data["layers"].index(self.parts[n]["layer"]))
        self.seam=json.loads((path.parent/'slice_map.json').read_text(encoding='utf8'))['splits'][0]['polyline']
        self.images = {}
        for name, p in self.parts.items():
            with Image.open(path.parent / p["file"]) as im:
                self.images[name] = im.convert("RGBA")
            if self.images[name].size != tuple(p["size"]):
                raise ValueError(f"size mismatch: {name}")
        for face in self.faces:
            roles = {self.parts[n].get("role") for n in self.face_parts(face)}
            if roles != {"eye_l", "eye_r", "mouth"}:
                raise ValueError("Run python -m tools.v3_slice split-expressions first")
        self.face_base = self.images['head_skin']
        self.feature_images={}
        for name,file in self.data.get('face_feature_overrides',{}).items():
            with Image.open(path.parent/file) as im:self.feature_images[name]=im.convert('RGBA')
            if self.feature_images[name].size!=self.images[name].size:raise ValueError('feature override size mismatch')
        self.pink_cleanup=None
        if 'pink_cleanup' in self.data:
            with Image.open(path.parent/self.data['pink_cleanup']) as im:self.pink_cleanup=im.convert('RGBA')
        self.face_plate=None
        if 'face_plate' in self.data:
            p=self.data['face_plate']
            with Image.open(path.parent/p['file']) as im:self.face_plate=(im.convert('RGBA'),(p['x'],p['y']))
        self.source_fringe_mask=None
        if 'face_source_fringe_mask' in self.data:
            with Image.open(path.parent/self.data['face_source_fringe_mask']) as im:self.source_fringe_mask=im.convert('L')
        self.expression_plates={}
        for name,p in self.data.get('expression_face_plates',{}).items():
            with Image.open(path.parent/p['open']) as im:
                self.expression_plates[name]=(im.convert('RGBA'),(p['x'],p['y']))
        self.face_hair_images={}
        self.face_contour=None
        if 'face_contour' in self.data:
            with Image.open(path.parent/self.data['face_contour']) as im:self.face_contour=im.convert('RGBA')
        self.fringe_mask=None
        if 'face_fringe_mask' in self.data:
            with Image.open(path.parent/self.data['face_fringe_mask']) as im:
                self.fringe_mask=im.convert('L')
        for name,file in self.data.get('face_hair_clean',{}).items():
            with Image.open(path.parent/file) as im:self.face_hair_images[name]=im.convert('RGBA')
        if 'face_clean_base' in self.data:
            with Image.open(path.parent / self.data['face_clean_base']) as im:
                self.face_base = im.convert('RGBA')

        self.cheek_config=self.data.get('interactions',{}).get('cheek_left')
        self.cheek_images={}
        if self.cheek_config:
            config=self.cheek_config
            box=config['box']
            if (set(config['faces'])!=set(self.faces) or not 0<=config['cap_x']<config['root_x']<=self.size[0]
                    or len(config['vertical'])!=4 or len(box)!=4 or box[0]>=box[2] or box[1]>=box[3]
                    or not all(a<b for a,b in zip(config['vertical'],config['vertical'][1:]))):
                raise ValueError('invalid left cheek interaction metadata')
            for face,entry in self.cheek_config['faces'].items():
                self.cheek_images[face]={}
                for key,file in entry.items():
                    with Image.open(path.parent/file) as im:
                        self.cheek_images[face][key]=im.convert('RGBA' if key=='texture' else 'L')
                for key,image in self.cheek_images[face].items():
                    expected=self.size if key=='protect' else (box[2]-box[0],box[3]-box[1])
                    if image.size!=tuple(expected) or not image.getbbox():
                        raise ValueError('invalid cheek asset: '+face+'/'+key)
        if cheek_side!='left':
            from .mirror import apply_cheek_side
            apply_cheek_side(self,cheek_side)

    def face_parts(self, expression):
        return [n for n in self.order if self.parts[n].get("variant") == expression]

    def active(self, expression, underlays_only=False):
        if expression not in self.faces:
            raise ValueError("unknown expression")
        return [n for n in self.order if
                (not underlays_only or self.parts[n]["source"] == "gpt_underlay") and
                ("variant" not in self.parts[n] or self.parts[n]["variant"] == expression)]

    def rest(self, expression, underlays_only=False, original=False):
        canvas = Image.new("RGBA", self.size)
        for n in self.active(expression, underlays_only):
            p = self.parts[n]
            if expression!='smug' and self.face_plate and p.get('role'):
                continue  # The complete plate draws these once, above bangs.
            image = self.face_base if n=='head_skin' and expression!='smug' else self.images[n]
            if expression!='smug' and n in self.face_hair_images:image=self.face_hair_images[n]
            if p.get('role')=='mouth':image=without_brows(self,n)
            canvas.alpha_composite(image, (p["x"], p["y"]))
            if n=='bangs' and not underlays_only:
                if expression!='smug' and self.face_plate:
                    from .face import plate_face
                    canvas.alpha_composite(*plate_face(self,expression,1))
                    continue
                if expression!='smug' and self.face_contour is not None:canvas.alpha_composite(self.face_contour)
                brow=brows_image(self,expression)
                if brow:canvas.alpha_composite(*brow)
        if expression=='smug' and not underlays_only and not original and self.pink_cleanup is not None:
            # 窗口版会把它换成只存有内容一块的 SparseCanvas（shion/v3_memory.py），带位置叠加
            cleanup = self.pink_cleanup
            canvas.alpha_composite(getattr(cleanup, 'image', cleanup), getattr(cleanup, 'offset', (0, 0)))
        return canvas


class Texture:
    def __init__(self, image, origin, scale, pad=0):
        self.x, self.y = origin[0] - pad, origin[1] - pad
        full = Image.new("RGBA", (image.width + pad * 2, image.height + pad * 2))
        full.paste(image, (pad, pad))
        size = (max(1, round(full.width * scale)), max(1, round(full.height * scale)))
        self.image = qimage(full.resize(size, Image.Resampling.LANCZOS))
        self.array = premultiplied(self.image)
        yy, xx = np.indices(self.array.shape[:2], dtype=np.float32)
        self.gx, self.gy = xx / scale + self.x, yy / scale + self.y


class Renderer:
    def __init__(self, rig: Rig, scale=0.4):
        self.rig = rig
        self.scale = scale
        self.textures = {n: Texture(im, (rig.parts[n]["x"], rig.parts[n]["y"]), scale,
                                    32 if n in BENDING else 2)
                         for n, im in rig.images.items()
                         if n in BODY|LEGS or rig.parts[n]["source"]=="gpt_underlay"}
        self.rest_cache = {}
        self.face_cache = {}
        # Padding covers the largest supported pinch without clipping cheeks.
        p = rig.parts["head_skin"]
        self.face_texture = Texture(rig.images["head_skin"], (p["x"], p["y"]), scale, 205)
        self.blink_faces = {}
        self._clean_leg_noise()
        self.brow_textures={}
        for expression in rig.faces:
            brow=brows_image(rig,expression)
            if brow:self.brow_textures[expression]=Texture(brow[0],brow[1],scale)
        from .surface import HeadSurface
        self.head_surface=HeadSurface(self)

    def _clean_leg_noise(self):
        # Very faint background noise forms a pale thread on gray backgrounds.
        for n in LEGS:
            p=self.rig.parts[n];a=np.asarray(self.rig.images[n]).copy()
            a[(a[...,3]<12)&(a[...,:3].min(-1)>110)]=0
            self.textures[n]=Texture(Image.fromarray(a),(p['x'],p['y']),self.scale,2)

    def matrices(self, pose):
        hip = (np.array(self.rig.pivots["hip_l"]) + np.array(self.rig.pivots["hip_r"])) / 2
        body = pivot_matrix(hip, pose.body_roll, sy=pose.body_scale)
        head = translation(pose.head_x, pose.head_y) @ pivot_matrix(self.rig.pivots["neck"],pose.head_roll)
        matrices = {}
        # Rig parents are not necessarily in drawing order (ribbon precedes flower).
        def calc(n):
            if n in matrices:
                return matrices[n]
            p = self.rig.parts[n]
            if n in LEGS:
                sign = 1 if n == 'leg_l' else -1
                m = pivot_matrix(self.rig.pivots[p['pivot']], sign*pose.leg_degrees)
            elif n in BODY:
                m = body
                if n in ("arm_l", "arm_r"):
                    sign=1 if n=='arm_l' else -1
                    m=body @ pivot_matrix(self.rig.pivots[p['pivot']],sign*pose.arm_degrees)
            elif n == "head_skin":
                m = head
            else:
                parent = p.get("parent")
                m = calc(parent) if parent else np.eye(3)
                if n in ROTATING and n!='bangs':
                    m = m @ pivot_matrix(self.rig.pivots[p["pivot"]], pose.angles.get(n, 0))
            matrices[n] = m
            return m
        for n in self.rig.order:
            calc(n)
        return matrices

    def _draw(self, painter, image, x, y, matrix=None, offset=(0, 0), opacity=1):
        m = np.eye(3) if matrix is None else matrix
        painter.save()
        painter.setOpacity(opacity)
        painter.setTransform(QTransform(m[0, 0], m[1, 0], m[0, 1], m[1, 1],
                                        (m[0, 2] - offset[0]) * self.scale,
                                        (m[1, 2] - offset[1]) * self.scale))
        painter.drawImage(QPointF(x * self.scale, y * self.scale), image)
        painter.restore()

    def _face(self, settings, pose):
        key = (settings.expression, round(pose.eye_scale, 5))
        t = self.face_texture
        if key not in self.face_cache:
            if settings.expression not in self.blink_faces:
                self.blink_faces[settings.expression] = self._prepare_blink(settings.expression)
            open_image, clean_image, eyes = self.blink_faces[settings.expression]
            if pose.eye_scale == 1:
                im = open_image
            else:
                im = clean_image.copy()
                painter = QPainter(im)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                for n, tex in eyes.items():
                    part = self.rig.parts[n]
                    matrix = pivot_matrix(part["blink_pivot"], sy=pose.eye_scale)
                    self._draw(painter, tex.image, tex.x, tex.y, matrix, (t.x, t.y))
                painter.end()
            if len(self.face_cache) > 64:
                self.face_cache.clear()
            self.face_cache[key] = im
        im = self.face_cache[key]
        return im

    def _prepare_blink(self, expression):
        """Compose clean skin + fixed mouth, then add complete eye cutouts.

        Eye whites and antialiasing are part of the cutout. There is no second
        color-key/inpaint pass that can leave an old eyelid behind.
        """
        t=self.face_texture
        size=(self.rig.images['head_skin'].width+410,self.rig.images['head_skin'].height+410)
        background=Image.new('RGBA',size)
        p=self.rig.parts['head_skin']
        skin=self.rig.face_base
        if expression=='smug':
            a=np.asarray(self.rig.images['head_skin']).copy();clean=np.asarray(self.rig.face_base)
            yy,xx=np.indices(a.shape[:2]);xx+=p['x'];yy+=p['y']
            mask=(yy<551)&((xx<500)|(xx>560))
            a[mask]=clean[mask];skin=Image.fromarray(a)
        background.alpha_composite(skin,(p['x']-t.x,p['y']-t.y))
        eyes={}
        for n in self.rig.face_parts(expression):
            part=self.rig.parts[n]
            if part['role']=='mouth':
                image=without_brows(self.rig,n)
                background.alpha_composite(image,(part['x']-t.x,part['y']-t.y))
            else:
                image=eye_image(self.rig,n)
                eyes[n]=Texture(image,(part['x'],part['y']),self.scale,2)
        opened=background.copy()
        for n in self.rig.face_parts(expression):
            part=self.rig.parts[n]
            if part['role'].startswith('eye'):
                # Use the same cropped eye pixels in open and compressed frames.
                image=eye_image(self.rig,n)
                opened.alpha_composite(image,(part['x']-t.x,part['y']-t.y))
        target=(t.image.width(),t.image.height())
        return (qimage(opened.resize(target,Image.Resampling.LANCZOS)),
                qimage(background.resize(target,Image.Resampling.LANCZOS)),eyes)

    def render(self, settings: Settings, pose: Pose, *, padding=(0, 0, 0, 0)) -> QImage:
        image = self._render_rig(settings,pose)
        left, top, right, bottom = padding
        if any(padding) or any(pose.root_offset) or pose.root_roll:
            scene = QImage(round((self.rig.size[0]+left+right)*self.scale),
                           round((self.rig.size[1]+top+bottom)*self.scale), image.format())
            scene.fill(0)
            painter = QPainter(scene)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._draw(painter, image, 0, 0, translation(left,top) @ root_matrix(pose))
            painter.end()
            image = scene
        if pose.star_age is not None and not settings.underlays_only:
            from .stars import paint_stars
            image = paint_stars(image,self.rig,self.scale,pose,offset=(left,top))
        return image

    def _render_rig(self, settings: Settings, pose: Pose) -> QImage:
        if pose.rig_is_rest:
            key = (settings.expression, settings.underlays_only)
            if key not in self.rest_cache:
                im = self.rig.rest(*key)
                size = tuple(round(x * self.scale) for x in im.size)
                if im.size != size:
                    im = im.resize(size, Image.Resampling.LANCZOS)
                self.rest_cache[key] = qimage(im)
            return self.rest_cache[key]
        if (not settings.underlays_only and (any(pose.pinch_delta) or pose.reaction_face is not None)
                and not settings.breath and not settings.blink and not settings.sway
                and self.rig.cheek_config):
            if not hasattr(self,'static_cheek'):
                from .cheek import StaticCheekSurface
                self.static_cheek=StaticCheekSurface(self)
            return self.static_cheek.render(settings,pose)
        if not settings.underlays_only:
            return self._surface_frame(settings,pose)
        im = QImage(round(self.rig.size[0] * self.scale), round(self.rig.size[1] * self.scale),
                    QImage.Format.Format_RGBA8888_Premultiplied)
        im.fill(0)
        painter = QPainter(im)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        matrices = self.matrices(pose)
        for n in self.rig.active(settings.expression, underlays_only=True):
            tex=self.textures[n]
            self._draw(painter,tex.image,tex.x,tex.y,matrices[n])
        painter.end()
        return im

    def _body_frame(self,settings,pose):
        im=QImage(round(self.rig.size[0]*self.scale),round(self.rig.size[1]*self.scale),
                  QImage.Format.Format_RGBA8888_Premultiplied)
        im.fill(0);painter=QPainter(im)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        matrices=self.matrices(pose)
        for n in self.rig.active(settings.expression):
            if n not in BODY|LEGS:continue
            tex=self.textures[n]
            self._draw(painter,tex.image,tex.x,tex.y,matrices[n])
        painter.end()
        return im

    def _surface_frame(self,settings,pose):
        from .sampling import submit_paint
        # QImage painting is reentrant. Body and head own separate buffers;
        # both complete before the UI receives this exact pose's frame.
        body=submit_paint(self._body_frame,settings,pose)
        surface=self.head_surface
        # A translated 1:1 QImage can take Qt's integer blit fast path. Bake the
        # fractional pixel into the inverse map so a 2-pixel breath is smooth.
        px=(surface.x+pose.head_x)*self.scale;py=(surface.y+pose.head_y)*self.scale
        ix,iy=int(np.floor(px)),int(np.floor(py))
        picture=surface.render(settings,pose,(px-ix,py-iy))
        im=body.result()
        painter=QPainter(im)
        painter.drawImage(QPointF(ix,iy),picture)
        painter.end()
        return im

    def hit_test(self, point, settings, pose, *, crown=False, belly=False):
        """Visible face wins over its own eyes; overlying hair wins over face."""
        point = self.rig_point(point, pose)
        if not settings.underlays_only:
            local=self.head_surface.source_point(point,pose)
            if local is not None:
                if self.head_surface.cheek.contains(local,settings,pose):
                    return 'cheek',local
                for n in reversed(self.head_surface.names):
                    p=self.rig.parts[n]
                    if n=='head_skin':
                        image=self.rig.images['head_skin']
                        x,y=round(local[0]-p['x']),round(local[1]-p['y'])
                        if 0<=x<image.width and 0<=y<image.height and image.getpixel((x,y))[3]>64:
                            return 'face',local
                    else:
                        image=self.rig.face_hair_images.get(n,self.rig.images[n])
                        x,y=round(local[0]-p['x']),round(local[1]-p['y'])
                        if 0<=x<image.width and 0<=y<image.height and image.getpixel((x,y))[3]>64:
                            return ('crown' if crown and n in {'hair_top','bangs','ahoge'} else 'head'),local
        matrices = self.matrices(pose)
        for n in reversed(self.rig.active(settings.expression, settings.underlays_only)):
            if not settings.underlays_only and n not in BODY|LEGS:continue
            p = self.rig.parts[n]
            local = transform_point(np.linalg.inv(matrices[n]), point)
            if n == "head_skin" or p.get("role"):
                # The deformed combined face is tested once at head_skin.
                if p.get("role"):
                    continue
                t = self.face_texture
                image = self._face(settings, pose)
                x, y = round((local[0] - t.x) * self.scale), round((local[1] - t.y) * self.scale)
                if 0 <= x < image.width() and 0 <= y < image.height() and image.pixelColor(x, y).alpha() > 64:
                    return "face", local
                continue
            if n=='bangs':
                local=rooted_rotation_inverse(np.array(local[0]),np.array(local[1]),
                    self.rig.pivots[p['pivot']],pose.angles.get(n,0),self.rig.seam)
            elif n in BENDING:
                root = self.rig.pivots[p["pivot"]]
                local = bend_inverse(local[0], local[1], root, max(1, p["y"] + p["size"][1] - root[1]),
                                     pose.angles.get(n, 0))
            x, y = int(local[0] - p["x"]), int(local[1] - p["y"])
            image = self.rig.images[n]
            if 0 <= x < image.width and 0 <= y < image.height and image.getpixel((x, y))[3] > 64:
                if belly and n in {'body','body_under'} and in_belly(local):
                    return 'belly',local
                return ("head" if n not in BODY | LEGS else "body"), local
        return None, point

    def rig_point(self, point, pose):
        """Inverse of the same whole-rig transform used by the scene painter."""
        if not any(pose.root_offset) and not pose.root_roll:
            return point
        return transform_point(np.linalg.inv(root_matrix(pose)), point)
