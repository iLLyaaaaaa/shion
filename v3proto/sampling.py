"""Parallel CPU sampling of disjoint mesh rows, with identical source pixels."""
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import numpy as np
from scipy import ndimage as nd

_POOL = ThreadPoolExecutor(max_workers=3,thread_name_prefix='v3-sampling')


def warp_mesh(image,mesh):
    """Pillow releases the GIL while sampling. Each job owns its output image.

    All jobs use the original quads and full-resolution premultiplied source.
    Splitting only at a destination cell boundary introduces no extra resample.
    """
    if len(mesh)<80:
        return image.transform(image.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
    rows=sorted({box[1] for box,_ in mesh})
    if len(rows)<2:
        return image.transform(image.size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
    # Three background workers plus the calling thread. Regions meet only
    # at existing cell boundaries, so there is no independent strip motion.
    # Small preview frames benefit from two jobs; four add more scheduling
    # overhead than they save. Larger device-resolution frames use four.
    jobs=2 if image.width*image.height<200000 else 4
    boundaries=[rows[len(rows)*i//jobs] for i in range(1,jobs)]
    boundaries=sorted(set([0,*boundaries,image.height]))
    groups=[[cell for cell in mesh if low<=cell[0][1]<high]
            for low,high in zip(boundaries[:-1],boundaries[1:])]
    futures=[_POOL.submit(image.transform,image.size,Image.Transform.MESH,g,Image.Resampling.BILINEAR) for g in groups[:-1]]
    last=image.transform(image.size,Image.Transform.MESH,groups[-1],Image.Resampling.BILINEAR)
    images=[f.result() for f in futures]+[last]
    result=images[0]
    for low,high,part in zip(boundaries[1:-1],boundaries[2:],images[1:]):
        result.paste(part.crop((0,low,image.width,high)),(0,low))
    return result


def sample_rgba(pixels,x,y,planar=False):
    """Independent C samplers write disjoint channels of one output buffer."""
    coords=np.array([y,x],dtype=np.float32)
    out=np.empty((4,*x.shape),dtype=np.uint8)
    planes=pixels if planar else np.ascontiguousarray(np.moveaxis(pixels,-1,0))
    def channel(c):
        nd.map_coordinates(planes[c],coords,output=out[c],order=1,
                           mode='constant',cval=0,prefilter=False)
    if x.size<2048:
        for c in range(4):channel(c)
    else:
        futures=[_POOL.submit(channel,c) for c in range(3)]
        channel(3)
        for f in futures:f.result()
    return np.ascontiguousarray(np.moveaxis(out,0,-1))


def submit_paint(function,*args):
    """Joined within the same frame; no asynchronous UI or pose queue."""
    return _POOL.submit(function,*args)


def source_over(destination,source,x,y):
    """Qt's integer SIMD blend writes the owned NumPy backing store."""
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtCore import QPoint
    height,width=destination.shape[:2]
    image=QImage(destination.data,width,height,destination.strides[0],QImage.Format.Format_RGBA8888_Premultiplied)
    h,w=source.shape[:2]
    patch=QImage(source.data,w,h,source.strides[0],QImage.Format.Format_RGBA8888_Premultiplied)
    painter=QPainter(image)
    painter.drawImage(QPoint(x,y),patch)
    painter.end()
