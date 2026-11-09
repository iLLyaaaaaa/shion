"""Parallel rasterization must preserve the accepted mesh pixel for pixel."""
import numpy as np
import pytest
from PIL import Image
from v3proto.sampling import warp_mesh


@pytest.mark.parametrize('size',[(31,27),(241,217),(378,333),(701,601)])
def test_parallel_mesh_matches_pillow_including_cell_boundaries(size):
    rng=np.random.default_rng(8)
    w,h=size
    rgba=rng.integers(0,256,(h,w,4),dtype=np.uint8)
    rgba[...,:3]=np.minimum(rgba[...,:3],rgba[...,3,None])
    image=Image.frombytes('RGBa',size,rgba.tobytes())
    xs=np.append(np.arange(0,w,24),w);ys=np.append(np.arange(0,h,24),h)
    mx,my=np.meshgrid(xs,ys)
    mx=mx+rng.normal(0,2,mx.shape);my=my+rng.normal(0,2,my.shape)
    mesh=[]
    for j in range(len(ys)-1):
        for i in range(len(xs)-1):
            box=(int(xs[i]),int(ys[j]),int(xs[i+1]),int(ys[j+1]))
            quad=(mx[j,i],my[j,i],mx[j+1,i],my[j+1,i],mx[j+1,i+1],my[j+1,i+1],mx[j,i+1],my[j,i+1])
            mesh.append((box,quad))
    original=image.transform(size,Image.Transform.MESH,mesh,Image.Resampling.BILINEAR)
    assert warp_mesh(image,mesh).tobytes()==original.tobytes()
    # Occupancy pruning may leave destination rows entirely empty.
    pruned=[cell for cell in mesh if cell[0][1]!=48 and cell[0][0]!=48]
    original=image.transform(size,Image.Transform.MESH,pruned,Image.Resampling.BILINEAR)
    assert warp_mesh(image,pruned).tobytes()==original.tobytes()


def test_erased_frame_cache_follows_source_identity():
    from v3proto.render import Renderer,Rig
    from v3proto.animation import Settings,Pose
    surface=Renderer(Rig(),.4).head_surface
    face=surface.reaction_face;settings=Settings()
    source=surface.compose(settings,Pose())
    first=face.erase(source,settings)
    assert face.erase(source,settings) is first
    replacement=source.copy();replacement[0,0]=[1,1,1,1]
    second=face.erase(replacement,settings)
    assert second is not first and np.array_equal(second[0,0],replacement[0,0])
    assert not np.shares_memory(source,first)


def test_native_source_over_mutates_owned_buffer_and_matches_integer_blend():
    from v3proto.sampling import source_over
    rng=np.random.default_rng(10)
    dst=rng.integers(0,256,(100,150,4),dtype=np.uint8)
    src=rng.integers(0,256,(50,80,4),dtype=np.uint8)
    for array in (dst,src):array[...,:3]=np.minimum(array[...,:3],array[...,3,None])
    expected=dst.copy();roi=expected[20:70,30:110]
    alpha=src[...,3,None].astype(np.uint16)
    roi[:]=np.minimum(255,src.astype(np.uint16)+(roi.astype(np.uint16)*(255-alpha)+127)//255).astype(np.uint8)
    source_over(dst,src,30,20)
    assert np.array_equal(dst,expected)
