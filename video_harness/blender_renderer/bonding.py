"""Native Blender gallery using supplied GLBs and editable teaching geometry."""
import math
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
from scene import SpectralGallery, INK, CYAN, GOLD
from bonding_math import tetrahedron, dna_point, complementary

CORAL=(1,.24,.23); BLUE=(.18,.42,1); GREEN=(.13,.8,.53)
BASE_COLORS={'A':GREEN,'T':CORAL,'G':GOLD,'C':BLUE}

def ease(p):
 p=max(0,min(1,p));return p*p*(3-2*p)

class BondingGallery(SpectralGallery):
 def __init__(self,job):
  self.groups={};self.roots={};self.anim=[];self.sphere_mesh=None
  super().__init__(job)
  self.scene.name='Bonding '+job['sequence_id'];self.camera.name='BondingCamera'
  self.camera.data.ortho_scale=24
  self.scene.world.use_nodes=True
  bg=self.scene.world.node_tree.nodes['Background'];bg.inputs[0].default_value=(.012,.019,.034,1);bg.inputs[1].default_value=.7
  self.scene.eevee.taa_render_samples=16
  for pos,power in [((-7,-2,10),1300),((7,4,8),1700)]:
   data=bpy.data.lights.new('Molecular softbox','AREA');data.energy=power;data.size=9
   obj=self.link('Molecular softbox',data);obj.location=pos

 def solid(self,color):
  key=('solid',*color)
  if key not in self.materials:
   mat=bpy.data.materials.new('Teaching surface');mat.diffuse_color=(*color,1);mat.use_nodes=True
   bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Base Color'].default_value=(*color,1);bsdf.inputs['Roughness'].default_value=.34
   self.materials[key]=mat
  return self.materials[key]

 def ball(self,name,pos,r,color,parent=None):
  if self.sphere_mesh is None:
   bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,radius=1)
   temp=bpy.context.object;self.sphere_mesh=temp.data.copy();bpy.data.objects.remove(temp,do_unlink=True)
   for p in self.sphere_mesh.polygons:p.use_smooth=True
  mesh=self.sphere_mesh.copy();mesh.materials.clear();mesh.materials.append(self.solid(color))
  obj=self.link(name,mesh);obj.parent=parent;obj.location=pos;obj.scale=(r,r,r);return obj

 def line(self,name,a,b,color=INK,r=.07,parent=None):
  obj=self.path(name,[a,b],color,r);obj.parent=parent;return obj

 def group(self,key,builder):
  before=set(self.scene.objects);builder();self.groups[key]=list(set(self.scene.objects)-before)

 def imported(self,name,filename,pos,size,rotation=None):
  before=set(self.scene.objects)
  bpy.ops.import_scene.gltf(filepath=str(Path(self.job['style']['asset_root'])/filename))
  self.scene.view_layers[0].update()
  imported=list(set(self.scene.objects)-before);meshes=[o for o in imported if o.type=='MESH']
  # Apply imported transforms before removing hierarchy. Merge only afterwards.
  world=[(o,o.matrix_world.copy()) for o in meshes]
  for o,m in world:o.parent=None;o.matrix_world=m;o.animation_data_clear()
  for o in imported:
   if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
  bpy.ops.object.select_all(action='DESELECT')
  for o in meshes:o.select_set(True)
  bpy.context.view_layer.objects.active=meshes[0];bpy.ops.object.join();obj=bpy.context.object
  obj.name=name+'Mesh';bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
  pts=[Vector(v) for v in obj.bound_box]
  lo=Vector([min(v[i] for v in pts) for i in range(3)]);hi=Vector([max(v[i] for v in pts) for i in range(3)])
  norm=Matrix.Scale(size/max(hi-lo),4)@Matrix.Translation(-(lo+hi)/2)
  if rotation:norm=rotation@norm
  obj.data.transform(norm);obj.matrix_world=Matrix.Identity(4)
  # Simplify dense scans for a teaching video while retaining their materials.
  if len(obj.data.polygons)>120000:
   mod=obj.modifiers.new('Preview mesh density','DECIMATE');mod.ratio=120000/len(obj.data.polygons)
   bpy.ops.object.modifier_apply(modifier=mod.name)
  root=self.link(name,None);obj.parent=root;root.location=pos;self.roots[name]=root
  return root,obj

 def caption(self,title,subtitle=None,x=6):
  self.text(title,x,1.3,1.18)
  if subtitle:self.text(subtitle,x,-.8,1.0,CYAN)

 def make_minerals(self):
  self.text('흑운모',-5,4.6,1.12);self.text('석영',5,4.6,1.12)
  mica,mesh=self.imported('Biotite','biotite.glb',(-5,0,0),7,Matrix.Rotation(.30,4,'X'))
  self.mica_layers=[]
  # Layer separation model derived from the scan footprint; layers are schematic.
  for i in range(4):
   obj=mesh.copy();obj.data=mesh.data;self.scene.collection.objects.link(obj);obj.parent=mica
   obj.name='BiotiteLayer'+str(i);obj.scale=(1,1,.20);obj.location=(0,0,i*.25)
   self.mica_layers.append(obj)
  bpy.data.objects.remove(mesh,do_unlink=True)
  quartz,obj=self.imported('Quartz','Quartz crystal .glb',(5,0,0),7,Matrix.Rotation(-math.pi/2,4,'X'))
  # A real plane cut of the mesh creates separate fragments, not duplicate crystals.
  import bmesh
  self.fragments=[]
  for sign in [1,-1]:
   part=obj.copy();part.data=obj.data.copy();self.scene.collection.objects.link(part);part.parent=quartz
   bm=bmesh.new();bm.from_mesh(part.data)
   bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.00001,plane_co=(0,0,0),plane_no=(1,.32,.16),clear_inner=sign==1,clear_outer=sign==-1)
   bm.to_mesh(part.data);bm.free();part.name='QuartzFragment'+str(sign);self.fragments.append((part,sign))
  bpy.data.objects.remove(obj,do_unlink=True)

 def make_tetra(self):
  root=self.link('SilicateUnit',None);root.location=(-4,0,0);root.rotation_euler=(.35,.25,.15);self.tetra=root
  self.silicon=self.ball('Silicon',(0,0,0),.48,GOLD,root);self.oxygens=[]
  for i,p in enumerate(tetrahedron(3)):
   o=self.ball('Oxygen'+str(i),p,.48,CORAL,root);self.oxygens.append((o,Vector(p)))
   self.line('SiOBond'+str(i),(0,0,0),p,GOLD,.09,root)
  for i,a in enumerate(tetrahedron(3)):
   for b in tetrahedron(3)[i+1:]:self.line('TetrahedronEdge',a,b,(.18,.34,.43),.025,root)
  self.caption('규산염 사면체','규소 1 + 산소 4')

 def make_sheet(self):
  self.text('판상 구조',-5,4.7,1.12);self.text('망상 구조',5,4.7,1.12)
  self.sheet_layers=[]
  # Corner-sharing triangular bases form a honeycomb sheet; no duplicated oxygen.
  for layer in range(3):
   root=self.link('SilicateSheet'+str(layer),None);root.location=(-5,-.5,0);root.rotation_euler=(.70,.2,.2)
   points={};d=1.20
   centers=[]
   for row in range(2):
    for col in range(3):
     x=math.sqrt(3)*d*(col+row/2)-2.8;y=1.5*d*row-1.7
     centers += [(x,y,0),(x,y+d,1)]
   for cx,cy,kind in centers:
    dirs=[(0,d),(-math.sqrt(3)*d/2,-d/2),(math.sqrt(3)*d/2,-d/2)]
    if kind:dirs=[(-x,-y) for x,y in dirs]
    verts=[(cx+x/2,cy+y/2,layer*.65) for x,y in dirs]
    verts.append((cx,cy,layer*.65+.85));center=(cx,cy,layer*.65+.2125)
    self.ball('SheetSi',center,.13,GOLD,root)
    for v in verts:
     key=tuple(round(x,4) for x in v)
     if key not in points:points[key]=self.ball('SheetO',v,.11,CORAL,root)
     self.line('SheetSiO',center,v,GOLD,.03,root)
   self.sheet_layers.append(root)
  self.imported('QuartzNetwork','Quartz Supercell.glb',(5,0,0),7,Matrix.Rotation(.5,4,'X'))

 def make_carbon(self):
  self.carbons=[];self.carbon_edges=[]
  layouts=[('사슬',[(-8+i*1.25,2,0) for i in range(5)],[(i,i+1) for i in range(4)]),('고리',[(-6+1.8*math.cos(i*math.tau/6),-2+1.8*math.sin(i*math.tau/6),0) for i in range(6)],[(i,(i+1)%6) for i in range(6)]),('가지',[(-1,1,0),(0,0,0),(-1,-1,0),(1,1,0),(1,-1,0)],[(0,1),(1,2),(1,3),(1,4)])]
  for name,pts,edges in layouts:
   for p in pts:self.carbons.append(self.ball('Carbon',p,.28,(.3,.38,.45)))
   for a,b in edges:
    line=self.line('CarbonBond',pts[a],pts[b],INK,.08);line['animate_curve_reveal']=True;self.carbon_edges.append(line)
  self.caption('탄소 골격','사슬 · 고리 · 가지')

 def make_amino(self):
  self.imported('Glycine','Glycine.glb',(-6,0,0),4.4,Matrix.Rotation(-.6,4,'X'))
  self.imported('Alanine','Alanine.glb',(-.8,0,0),4.4,Matrix.Rotation(-.6,4,'X'))
  self.text('글리신',-6,-3.6,.75);self.text('알라닌',-.8,-3.6,.75)
  self.caption('아미노산','20종\n다양한 조합')

 def make_protein(self):
  self.protein_beads=[];self.protein_bonds=[]
  colors=[CYAN,CORAL,GOLD,GREEN,BLUE]
  for i in range(16):self.protein_beads.append(self.ball('Residue%02d'%i,(-9+i*.65,0,0),.23,colors[i%5]))
  for i in range(15):
   line=self.line('PeptideLink%02d'%i,(-9+i*.65,0,0),(-9+(i+1)*.65,0,0),INK,.065);line['animate_points']=True;self.protein_bonds.append(line)
  self.imported('Myoglobin','Myoglobin.glb',(5,0,0),6.3,Matrix.Rotation(-.35,4,'X'))
  self.text('배열 → 접힘',-5,4.6,1.04);self.text('단백질의 입체 구조',5,4.6,.96)

 def make_dna_asset(self):
  self.imported('HumanDNA','Human DNA.glb',(-4.5,0,0),8.5,Matrix.Rotation(-math.pi/2,4,'X'))
  self.scan=self.ring('SequenceScan',-4.5,0,2.8,GOLD)
  self.caption('순서는 어디에?','DNA 염기 서열')

 def make_nucleotide(self):
  self.nucleotide_parts=[]
  for name,pos,color,r in [('인산',(-8,0,0),GOLD,.62),('당',(-4.4,0,0),CYAN,.8),('염기',(-.8,0,0),GREEN,.75)]:
   if name=='당':
    verts=[(math.cos(i*math.tau/5)*r,math.sin(i*math.tau/5)*r,0) for i in range(5)]
    mesh=bpy.data.meshes.new('Deoxyribose');mesh.from_pydata(verts,[],[tuple(range(5))]);mesh.materials.append(self.solid(color));obj=self.link('Sugar',mesh);obj.location=pos
    mod=obj.modifiers.new('Thickness','SOLIDIFY');mod.thickness=.25
   else:obj=self.ball(name,pos,r,color)
   self.nucleotide_parts.append((obj,Vector(pos)))
   self.text(name,pos[0],-3.4,.9,color)
  self.nt_links=[self.line('PhosphateSugar',(-8,0,0),(-4.4,0,0),INK,.085),self.line('SugarBase',(-4.4,0,0),(-.8,0,0),INK,.085)]
  self.caption('뉴클레오타이드','인산 + 당 + 염기')

 def make_sequences(self):
  self.base_tiles=[]
  for row,seq in enumerate(['ATGCCGTA','TACGATCG']):
   for i,base in enumerate(seq):
    x=-9+i*1.15;y=1.5-row*3
    o=self.ball('SequenceBase', (x,y,0),.50,BASE_COLORS[base]);self.base_tiles.append(o)
    self.text(base,x,y-.22,.90,(.01,.025,.04)).location.z=1
   self.line('SugarPhosphateBackbone',(-9.6,y-.8,0),(-.3,y-.8,0),CYAN,.065)
  self.caption('종류는 4개','배열 순서 = 정보')

 def make_helix(self):
  self.dna_atoms=[];self.dna_links=[];self.dna_pairlinks=[];self.dna_letters=[];self.dna_hb=[]
  seq='ATGCCGTATACGGCAT'
  for strand in range(2):
   for i,base in enumerate(seq if strand==0 else complementary(seq)):
    p=Vector(dna_point(i,strand));p.x-=4.5
    o=self.ball(f'DNABackbone{strand}_{i}',p,.17,CYAN if strand==0 else GOLD)
    self.dna_atoms.append((o,i,strand))
   path=self.path('DNAStrand'+str(strand),[tuple(Vector(dna_point(i,strand))+Vector((-4.5,0,0))) for i in range(16)],CYAN if strand==0 else GOLD,.08)
   path['animate_points']=True;self.dna_links.append((path,strand))
  for i,base in enumerate(seq):
   a=Vector(dna_point(i,0))+Vector((-4.5,0,0));b=Vector(dna_point(i,1))+Vector((-4.5,0,0));mid=(a+b)/2
   for side,(v,col) in enumerate([(a,BASE_COLORS[base]),(b,BASE_COLORS[complementary(base)])]):
    line=self.line('BasePairHalf',v,mid,col,.10);line['animate_points']=True;self.dna_pairlinks.append((line,i,side))
   count=2 if base in 'AT' else 3
   for j in range(count):
    line=self.line('HydrogenBond',tuple(mid+Vector((-.12,(j-(count-1)/2)*.065,0))),tuple(mid+Vector((.12,(j-(count-1)/2)*.065,0))),INK,.018)
    line['animate_points']=True;self.dna_hb.append((line,i,j,count))
  self.caption('A ↔ T   G ↔ C','연결 → 구조와 기능')
  for label,i,strand in [('5′',0,0),('3′',0,1),('3′',15,0),('5′',15,1)]:
   self.dna_letters.append((self.text(label,0,0,.60,CYAN if strand==0 else GOLD),i,strand))

 def build(self):
  wanted={b['controller_options']['scene_number'] for b in self.job['timeline']}
  builders={1:self.make_minerals,2:self.make_tetra,3:self.make_sheet,4:self.make_carbon,5:self.make_amino,6:self.make_protein,7:self.make_dna_asset,8:self.make_nucleotide,9:self.make_sequences,10:self.make_helix}
  for n in sorted(wanted):self.group(n,builders[n])
  self.track=list(self.scene.objects)

 def sample(self,frame):
  entry=self.job['canonical_state_cache'][frame]
  beat=max((b for b in self.job['timeline'] if b['beat_id'] in entry['active_beat_ids']),key=lambda b:b.get('priority',0))
  n=beat['controller_options']['scene_number'];same=[b for b in self.job['timeline'] if b['controller_options']['scene_number']==n]
  start=min(b['start_frame'] for b in same);end=max(b['end_frame'] for b in same)
  q=(frame-start)/max(1,end-start-1);t=entry['simulation_time'];p=ease(q)
  for key,objects in self.groups.items():
   for o in objects:o.hide_render=o.hide_viewport=key!=n
  self.camera.location=(0,0,30);self.camera.rotation_euler=(0,0,0);self.camera.data.ortho_scale=24
  if n==1:
   for i,o in enumerate(self.mica_layers):o.location=(.18*i*p,.4*i*p,i*.25+.6*i*p)
   for o,sign in self.fragments:o.location=(sign*.48*p,sign*.15*p,0)
  elif n==2:
   self.tetra.rotation_euler=(.35,.25+.65*p,.15)
   for i,(o,v) in enumerate(self.oxygens):o.scale=(.48,)*3
  elif n==3:
   for i,root in enumerate(self.sheet_layers):root.location=(-5,-.5+i*.5*p,i*.7*p)
   self.roots['QuartzNetwork'].rotation_euler.y=.20*p
  elif n==4:
   for i,o in enumerate(self.carbons):o.scale=(max(.01,.28*ease(q*2-i/len(self.carbons)*.8)),)*3
   for i,o in enumerate(self.carbon_edges):o.data.bevel_factor_end=ease(q*2-i/len(self.carbon_edges)*.8)
  elif n==5:
   for key in ['Glycine','Alanine']:self.roots[key].rotation_euler.y=.5*p
  elif n==6:
   fold=ease((q-.25)/.75)
   for i,o in enumerate(self.protein_beads):
    straight=Vector((-9+i*.57,0,0));a=i*.83
    folded=Vector((-5+2.25*math.cos(a),1.65*math.sin(a),.8*math.sin(a*.5)))
    o.location=straight.lerp(folded,fold)
   for i,o in enumerate(self.protein_bonds):
    for pt,v in zip(o.data.splines[0].points,[self.protein_beads[i].location,self.protein_beads[i+1].location]):pt.co=(*v,1)
   self.roots['Myoglobin'].rotation_euler.y=.3*p
  elif n==7:
   self.roots['HumanDNA'].rotation_euler.y=.35*p;self.scan.location.y=-3.6+7.2*p
  elif n==8:
   for i,(o,orig) in enumerate(self.nucleotide_parts):o.location=orig+Vector((0,(1-p)*(1 if i%2==0 else -1)*2,0))
   positions=[o.location for o,_ in self.nucleotide_parts]
   for i,o in enumerate(self.nt_links):
    o['animate_points']=True
    for pt,v in zip(o.data.splines[0].points,positions[i:i+2]):pt.co=(*v,1)
  elif n==9:
   scan=q*8
   for i,o in enumerate(self.base_tiles):o.scale=(.50*(1+.15*max(0,1-abs(i%8-scan))),)*3
  elif n==10:
   twist=.08+.92*p
   for o,i,strand in self.dna_atoms:o.location=Vector(dna_point(i,strand,twist))+Vector((-4.5,0,0))
   for o,strand in self.dna_links:
    for i,pt in enumerate(o.data.splines[0].points):pt.co=(*tuple(Vector(dna_point(i,strand,twist))+Vector((-4.5,0,0))),1)
   for o,i,side in self.dna_pairlinks:
    a=Vector(dna_point(i,side,twist))+Vector((-4.5,0,0));mid=Vector((-4.5,a.y,0))
    near=mid+(a-mid).normalized()*.14
    for pt,v in zip(o.data.splines[0].points,[a,near]):pt.co=(*v,1)
   for o,i,j,count in self.dna_hb:
    a=Vector(dna_point(i,0,twist));axis=Vector((a.x,0,a.z)).normalized()
    mid=Vector((-4.5,a.y+(j-(count-1)/2)*.065,0))
    for pt,v in zip(o.data.splines[0].points,[mid-axis*.12,mid+axis*.12]):pt.co=(*v,1)
   for o,i,strand in self.dna_letters:
    loc=Vector(dna_point(i,strand,twist))+Vector((-4.5, (-.55-.48*strand) if i==0 else (.55+.48*strand), 1.1));o.location=loc
  return entry,self.track

 def bake(self):
  # Sampling itself is authoritative for renders; native keys make the blend editable.
  keyframes=set(range(0,self.job['duration_frames'],3)) | {self.job['duration_frames']-1}
  for b in self.job['timeline']:keyframes.update([b['start_frame'],b['end_frame']-1])
  for frame in sorted(keyframes):
   _,objects=self.sample(frame)
   for obj in objects:
    if obj.type in {'LIGHT','CAMERA'}:continue
    for prop in ('location','rotation_euler','scale','hide_render','hide_viewport'):obj.keyframe_insert(data_path=prop,frame=frame+1)
    if obj.get('animate_curve_reveal'):obj.data.keyframe_insert(data_path='bevel_factor_end',frame=frame+1)
    if obj.get('animate_points'):
     for spl in obj.data.splines:
      for point in spl.points:point.keyframe_insert(data_path='co',frame=frame+1)
  self.scene.frame_set(1);self.font.pack();bpy.ops.file.pack_all()

 def extra_state(self):
  return {'visible':[o.name for o in self.track if not o.hide_render]}
