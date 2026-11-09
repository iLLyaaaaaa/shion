"""Remove only the small pink marks above the eyes, retaining other pixels."""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd


BOXES = {
    'smug': [(388,438,435,461),(563,410,616,440)],
    'neutral': [(387,442,440,463),(568,425,655,448)],
    'happy': [(402,478,465,500),(574,453,616,483)],
    'surprised': [(381,430,439,460),(566,414,616,440)],
    'teary': [(389,439,437,462),(561,421,624,445)],
    'angry': [(391,454,467,483),(566,447,611,476)],
    'sleep': [], 'dizzy': [],
}


def remove_marks(image, expression, affine=None):
    a=np.asarray(image).copy()
    c=a[...,:3].astype(float)
    result=a.copy();mask=np.zeros(a.shape[:2],bool)
    affine=affine or [1,0,0,0,1,0]
    for box in BOXES[expression]:
        x0,y0,x1,y1=box
        points=[]
        for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
            points.append((affine[0]*x+affine[1]*(y-250)+affine[2],
                           affine[3]*(x-540)+affine[4]*y+affine[5]))
        region=Image.new('1',image.size);ImageDraw.Draw(region).polygon(points,fill=1)
        domain=np.asarray(region,dtype=bool)
        near_ink=nd.binary_dilation(c.min(-1)<70,iterations=2)
        seed=domain&(c[...,0]>170)&(c[...,1]>75)&(c[...,1]<215)&(c[...,2]-c[...,1]>-15)&(c[...,0]-c[...,1]>35)&~near_ink
        if not seed.any():continue
        # Include the darker antialias fringe of the pink stroke, while keeping
        # the neighboring brown outline and its immediate perimeter intact.
        local=seed|(nd.binary_dilation(seed,iterations=3)&domain&(c[...,0]>160)&(c.min(-1)>90)&~near_ink)
        yy,xx=np.where(local)
        left,right=max(0,xx.min()-10),min(image.width,xx.max()+11)
        top,bottom=max(0,yy.min()-10),min(image.height,yy.max()+11)
        sl=np.s_[top:bottom,left:right];small=c[sl];hole=local[sl]
        gy,gx=np.indices(hole.shape);gx=gx-hole.shape[1]/2;gy=gy-hole.shape[0]/2
        basis=np.stack((np.ones_like(gx),gx,gy,gx*gy),-1).astype(float)
        distance=nd.distance_transform_edt(~hole)
        skin=(distance>2)&(distance<10)&(small[...,0]>235)&(small[...,1]>205)&(small[...,0]-small[...,1]<40)
        if skin.sum()<8:raise ValueError('insufficient clean skin around '+expression)
        coefficients=np.linalg.lstsq(basis[skin],small[skin],rcond=None)[0]
        fill=np.rint(basis@coefficients).clip(0,255).astype(np.uint8)
        fill[...,1]=np.maximum(fill[...,1],np.maximum(fill[...,0].astype(int)-32,0).astype(np.uint8))
        result[sl][hole,:3]=fill[hole]
        mask|=local
    return Image.fromarray(result),mask


def export(raw, replacements):
    import hashlib,json
    report=json.loads((replacements/'import-report.json').read_text(encoding='utf8'))
    manifest_path=raw/'no_pink_manifest.json'
    previous=json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {}
    manifest={}
    for name in BOXES:
        source=replacements/(name+'-input.png')
        replacement=source.exists()
        if not replacement:source=raw/('ref.png' if name=='smug' else 'expr_'+name+'.png')
        output=raw/('ref_no_pink.png' if name=='smug' else 'expr_'+name+'_no_pink.png')
        if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest()!=previous.get(output.name,{}).get('output_sha256'):
            raise FileExistsError('output modified outside exporter: '+output.name)
        with Image.open(source) as im:original=im.convert('RGBA')
        matrix=report[name]['sampling_affine'] if replacement else None
        clean,mask=remove_marks(original,name,matrix)
        assert np.array_equal(np.asarray(original)[~mask],np.asarray(clean)[~mask])
        clean.save(output)
        manifest[output.name]={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                               'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                               'size':list(clean.size),'edited_pixels':int(mask.sum()),'outside_mask_changed_pixels':0}
    (raw/'no_pink_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return manifest


if __name__=='__main__':
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--replacements',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(export(args.raw,args.replacements),indent=2))
