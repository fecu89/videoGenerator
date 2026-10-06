"""One continuous native Blender scene for the user's mineral-to-DNA revision.

Global time owns every transform: narration boundaries never rebuild objects.
Atomic assembly is a teaching diagram, not a molecular dynamics simulation.
"""
import math
import random
import bpy
import bmesh
from mathutils import Vector, Matrix, Euler
from bonding import BondingGallery, CORAL, GREEN, BLUE, BASE_COLORS
from scene import INK, CYAN, GOLD
from bonding_math import dna_point, complementary
from animated_materials import fade_material


def progress(t, start, end):
    x=max(0.,min(1.,(t-start)/max(.0001,end-start)))
    return x*x*x*(x*(x*6-15)+10)


def lerp(a,b,p):
    return Vector(a).lerp(Vector(b),p)


class BondingFlowGallery(BondingGallery):
    def root(self,name):
        o=self.link(name,None);self.dynamic.append(o);return o

    def segment(self,name,a,b,color=INK,r=.06,parent=None):
        o=self.line(name,a,b,color,r,parent);o['animate_points']=True;self.dynamic.append(o);return o

    def setline(self,obj,a,b):
        for point,pos in zip(obj.data.splines[0].points,(a,b)):point.co=(*pos,1)

    def pose(self,root,position,scale=1,rotation=(0,0,0)):
        root.location=position;root.scale=(max(.00001,scale),)*3;root.rotation_euler=rotation

    def visibility(self,root,visible):
        for obj in self.families[root.name]:obj.hide_render=obj.hide_viewport=not visible

    def textgroup(self,n,items):
        root=self.root('FlowCaption%02d'%n);self.caption_opacity[n]=[]
        for body,x,y,size,color in items:
            obj=self.text(body,x,y,size*1.5,color);obj.parent=root
            self.caption_opacity[n].append(fade_material(obj))
        self.captions[n]=root

    def build(self):
        self.dynamic=[];self.captions={};self.caption_opacity={};self.times=[b['start_frame']/self.job['canonical_fps'] for b in self.job['timeline']]
        self.times.append(self.job['duration_frames']/self.job['canonical_fps'])
        self.build_rocks();self.build_silicates();self.build_carbons();self.build_amino_chain();self.build_dna();self.build_letters()
        for n,title,subtitle in [(2,'규산염 사면체','규소 1 + 산소 4'),(4,'탄소 골격','사슬 · 고리 · 가지'),(5,'아미노산','20종 → 다양한 조합'),(6,'아미노산 사슬','배열 → 접힘'),(7,'순서는 어디에?','DNA 염기 서열'),(8,'뉴클레오타이드','인산 + 당 + 염기'),(9,'염기는 네 종류','A · T · G · C'),(10,'배열 순서 = 정보','A ↔ T   G ↔ C')]:
            self.textgroup(n,[(title,6,1.65,1.13,INK),(subtitle,6,-1.1,.92,CYAN)])
        self.textgroup(1,[('흑운모',-5.5,5.4,1.1,INK),('석영',5.5,5.4,1.1,INK)])
        self.textgroup(3,[('판상 구조',-5.5,5.4,1.1,INK),('망상 구조',5.5,5.4,1.1,INK)])
        self.families={o.name:[o,*o.children_recursive] for o in self.scene.objects if o.parent is None}
        self.track=list(self.scene.objects)
        # A shared screen-space transform enlarges whole connected structures,
        # including independently tracked atoms and their bond endpoints.
        # It runs after the physical animation, so object identity and timing
        # stay continuous and arbitrary frame sampling remains deterministic.
        self.presentation_roots=[o for o in self.track if o.parent is None
            and o.type in {'EMPTY','MESH','CURVE','FONT'}
            and o not in self.captions.values()]
        self.defaults={o:(o.location.copy(),o.rotation_euler.copy(),o.scale.copy()) for o in self.track}
        # Only moving transforms and curve geometry need editable animation keys.
        self.dynamic=list(dict.fromkeys(self.dynamic))

    def build_rocks(self):
        self.mica,obj=self.imported('Biotite','biotite.glb',(-5,0,0),6.4,Matrix.Rotation(.3,4,'X'))
        self.dynamic.append(self.mica);self.mica_layers=[]
        for i in range(5):
            part=obj.copy();part.data=obj.data;self.scene.collection.objects.link(part);part.parent=self.mica
            part.name='BiotiteLayer'+str(i);part.scale=(1,1,.13);part.location=(0,0,i*.22)
            self.mica_layers.append(part);self.dynamic.append(part)
        bpy.data.objects.remove(obj,do_unlink=True)
        self.quartz,obj=self.imported('Quartz','Quartz crystal .glb',(5,0,0),6.5,Matrix.Rotation(-math.pi/2,4,'X'))
        self.dynamic.append(self.quartz)
        # Many unequal convex cells, capped and triangulated: no two-half plane cut.
        rng=random.Random(921);seeds=[Vector((rng.uniform(-1.3,1.3),rng.uniform(-2.6,2.6),rng.uniform(-.85,.85))) for _ in range(16)]
        material=self.solid((.54,.56,.45));obj.data.materials.append(material);cap_index=len(obj.data.materials)-1
        self.shards=[]
        for i,seed in enumerate(seeds):
            mesh=obj.data.copy();bm=bmesh.new();bm.from_mesh(mesh)
            for j,other in enumerate(seeds):
                if i==j or not bm.verts:continue
                result=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.0001,plane_co=(seed+other)/2,plane_no=other-seed,clear_outer=True)
                edges=[e for e in result['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
                if edges:
                    filled=bmesh.ops.holes_fill(bm,edges=edges,sides=0)
                    for face in filled['faces']:face.material_index=cap_index
            if bm.faces:
                bmesh.ops.triangulate(bm,faces=[f for f in bm.faces if f.material_index==cap_index])
                bm.to_mesh(mesh);part=self.link('QuartzShard%02d'%i,mesh);part.parent=self.quartz
                direction=Vector((seed.x*.5,seed.y*.30,seed.z*.7))
                spin=Vector((rng.uniform(-.45,.45),rng.uniform(-.55,.55),rng.uniform(-.55,.55)))
                self.shards.append((part,direction,spin));self.dynamic.append(part)
            else:bpy.data.meshes.remove(mesh)
            bm.free()
        bpy.data.objects.remove(obj,do_unlink=True)

    def unit(self,name,center,up=True):
        root=self.root(name);root.location=center
        d=1.2;sign=1 if up else -1
        points=[(0,d*sign,0),(-math.sqrt(3)*d/2,-d*.5*sign,0),(math.sqrt(3)*d/2,-d*.5*sign,0),(0,0,math.sqrt(2)*d)]
        si=self.ball('FlowSi'+name[-2:],(0,0,math.sqrt(2)*d/4),.21,GOLD,root)
        oxy=[]
        for k,p in enumerate(points):
            oxy.append(self.ball(name+'O'+str(k),p,.20,CORAL,root))
            self.line(name+'SiO',si.location,p,GOLD,.046,root)
        for a,b in [(0,1),(1,2),(2,0),(0,3),(1,3),(2,3)]:self.line(name+'Edge',points[a],points[b],(.15,.32,.40),.018,root)
        return root,si,oxy

    def build_silicates(self):
        self.sheet=self.root('AssembledSheet');self.units=[];self.shared=[]
        centers=[];d=1.2
        for row in range(2):
            for col in range(3):
                x=math.sqrt(3)*d*(col+row/2);y=1.5*d*row
                centers.extend([(x,y,True),(x,y+d,False)])
        for i,(x,y,up) in enumerate(centers):
            root,si,ox=self.unit('Tetra%02d'%i,(x,y,0),up);root.parent=self.sheet
            self.units.append((root,Vector((x,y,0)),ox))
        # Correct corner-sharing positions: local triangle bases have half the
        # center-spacing radius. Scale each completed unit accordingly.
        self.unit_size=.5
        seen={}
        for root,c,oxy in self.units:
            for o in oxy:
                world=c+o.location*self.unit_size;key=tuple(round(v,5) for v in world)
                if key in seen:self.shared.append(o)
                else:seen[key]=o
        # The rapid dive first resolves stacked atomic sheets. The foreground
        # sheet's original Tetra00 is extracted, then reused for the later assembly.
        self.mica_atomic_layers=[]
        for layer in range(2):
            group=self.root('MicaAtomicLayer%d'%layer);group.parent=self.sheet
            for i,(_,target,_) in enumerate(self.units):
                unit,_,_=self.unit('MicaLayer%dUnit%02d'%(layer,i),target,centers[i][2])
                unit.parent=group;unit.scale=(self.unit_size,)*3
            # Background sheets move as rigid layers. Join their static pieces
            # so baking/rendering does not evaluate hundreds of redundant tracks.
            self.scene.view_layers[0].update()
            parts=[o for o in group.children_recursive if o.type in {'MESH','CURVE'}]
            empties=[o for o in group.children_recursive if o.type=='EMPTY']
            bpy.ops.object.select_all(action='DESELECT')
            for obj in parts:obj.select_set(True)
            bpy.context.view_layer.objects.active=parts[0]
            bpy.ops.object.convert(target='MESH');bpy.ops.object.join()
            obj=bpy.context.view_layer.objects.active;world=obj.matrix_world.copy()
            obj.parent=group;obj.matrix_world=world;obj.name='MicaAtomicSheet%d'%layer
            for empty in empties:
                self.dynamic.remove(empty);bpy.data.objects.remove(empty,do_unlink=True)
            self.mica_atomic_layers.append(group)
        self.network,obj=self.imported('QuartzNetwork','Quartz Supercell.glb',(5,0,0),6.7,Matrix.Rotation(.5,4,'X'))
        self.dynamic.append(self.network)
        # Axis gizmo is a disconnected component on the far left of this GLB.
        # Remove only geometry belonging to the colored X/Y/Z axes before render.
        bm=bmesh.new();bm.from_mesh(obj.data);components=[];remaining=set(bm.verts)
        while remaining:
            seed=remaining.pop();stack=[seed];component=[seed]
            while stack:
                v=stack.pop()
                for e in v.link_edges:
                    u=e.other_vert(v)
                    if u in remaining:remaining.remove(u);stack.append(u);component.append(u)
            components.append(component)
        drop=[]
        for c in components:
            center=sum((v.co for v in c),Vector())/len(c)
            if center.x < -2.05:drop.extend(c)
        bmesh.ops.delete(bm,geom=drop,context='VERTS');bm.to_mesh(obj.data);bm.free()
        self.axis_removed_vertices=len(drop)

    def build_carbons(self):
        self.carbon_root=self.root('CarbonSkeleton');self.carbons=[];self.carbon_targets=[];self.carbon_bonds=[]
        chain=[(-8+1.3*i,2,0) for i in range(5)]
        ring=[(-6+1.65*math.cos(i*math.tau/6),-2+1.65*math.sin(i*math.tau/6),0) for i in range(6)]
        branch=[(-2.5,1,0),(-1.5,0,0),(-2.5,-1,0),(-.5,1,0),(-.5,-1,0)]
        for i,p in enumerate(chain+ring+branch):
            o=self.ball('FlowCarbon%02d'%i,p,.30,(.27,.35,.42),self.carbon_root)
            self.carbons.append(o);self.carbon_targets.append(Vector(p));self.dynamic.append(o)
        edges=[(i,i+1) for i in range(4)]+[(5+i,5+(i+1)%6) for i in range(6)]+[(11,12),(12,13),(12,14),(12,15)]
        for a,b in edges:self.carbon_bonds.append((self.segment('CarbonBond',chain[0],chain[0],INK,.075,self.carbon_root),a,b))

    def amino(self,n):
        root=self.root('Amino%02d'%n);atoms={};links=[]
        data=[('CA',(0,0,0),(.27,.35,.42),.30),('N',(-1.3,.4,0),BLUE,.32),('C',(1.3,.4,0),(.27,.35,.42),.30),('O',(1.8,1.55,0),CORAL,.33),('OH',(2.05,-.65,0),CORAL,.33),('HO',(2.95,-.5,0),INK,.19),('H1',(-.05,-1,.6),INK,.19),('H2',(-.05,-.5,-.95),INK,.19),('HN1',(-1.7,1.25,.4),INK,.19),('HN2',(-1.95,-.3,-.4),INK,.19)]
        for name,p,color,r in data:
            if n==0 and name in {'CA','C'}:continue
            obj=self.ball(f'Amino{n:02d}_{name}',p,r,color,root);atoms[name]=(obj,Vector(p));self.dynamic.append(obj)
        for a,b in [('CA','N'),('CA','C'),('C','O'),('C','OH'),('OH','HO'),('CA','H1'),('CA','H2'),('N','HN1'),('N','HN2')]:
            line=self.segment(f'Amino{n:02d}_{a}_{b}',(0,0,0),(0,0,0),INK,.07,root);links.append((line,a,b,0))
            if b=='O':links.append((self.segment(f'Amino{n:02d}_DoubleO',(0,0,0),(0,0,0),INK,.052,root),a,b,1))
        return root,atoms,links

    def build_amino_chain(self):
        self.aminos=[self.amino(i) for i in range(7)];self.peptide=[]
        for i in range(6):self.peptide.append(self.segment('PeptideBond%02d'%i,(0,0,0),(0,0,0),GOLD,.075))

    def build_dna(self):
        self.dna,obj=self.imported('HumanDNA','Human DNA.glb',(-4.5,0,0),8.5,Matrix.Rotation(-math.pi/2,4,'X'))
        self.dynamic.append(self.dna)
        self.nt=self.root('Nucleotide');self.nt_parts=[]
        for name,pos,color,r in [('Phosphate',(-3.2,0,0),GOLD,.60),('Sugar',(0,0,0),CYAN,.78),('NucleotideBase',(3.2,0,0),GREEN,.68)]:
            if name=='Sugar':
                vertices=[(math.cos(i*math.tau/5)*r,math.sin(i*math.tau/5)*r,0) for i in range(5)]
                mesh=bpy.data.meshes.new('SugarPentagon');mesh.from_pydata(vertices,[],[tuple(range(5))]);mesh.materials.append(self.solid(color));o=self.link(name,mesh);o.location=pos;o.parent=self.nt
                o.modifiers.new('SugarThickness','SOLIDIFY').thickness=.25
            else:o=self.ball(name,pos,r,color,self.nt)
            self.nt_parts.append(o);self.dynamic.append(o)
        self.nt_links=[self.segment('PhosphateSugar',(-3.2,0,0),(0,0,0),INK,.08,self.nt),self.segment('SugarBase',(0,0,0),(3.2,0,0),INK,.08,self.nt)]
        self.nt_labels=[]
        for name,x,color in [('인산',-3.2,GOLD),('당',0,CYAN),('염기',3.2,GREEN)]:
            o=self.text(name,x,-1.6,.77,color);o.parent=self.nt;self.nt_labels.append(o);self.dynamic.append(o)

    def build_letters(self):
        self.seq='ATGCCGTATACG';self.bases=[];self.complements=[];self.base_labels=[];self.backbone=[];self.pairlinks=[]
        for i,base in enumerate(self.seq):
            o=self.nt_parts[2] if i==0 else self.ball('SequenceBase%02d'%i,(0,0,0),.36,BASE_COLORS[base])
            if i!=0:self.dynamic.append(o)
            label=self.text(base,0,0,.62,(.01,.025,.04));self.dynamic.append(label)
            self.bases.append(o);self.base_labels.append(label)
            c=complementary(base);obj=self.ball('ComplementBase%02d'%i,(0,0,0),.32,BASE_COLORS[c]);self.dynamic.append(obj)
            lab=self.text(c,0,0,.50,(.01,.025,.04));self.dynamic.append(lab);self.complements.append((obj,lab))
            self.pairlinks.append(self.segment('PairHydrogen%02d'%i,(0,0,0),(0,0,0),INK,.035))
        for strand in range(2):
            for i in range(11):self.backbone.append((self.segment(f'Backbone{strand}_{i}',(0,0,0),(0,0,0),CYAN if strand==0 else GOLD,.07),strand,i))
        self.termini=[]
        for text,i,strand in [('5′',0,0),('3′',11,0),('3′',0,1),('5′',11,1)]:
            o=self.text(text,0,0,.56,CYAN if strand==0 else GOLD);self.dynamic.append(o);self.termini.append((o,i,strand))

    def sample(self,frame):
        t=frame/self.job['canonical_fps'];B=self.times;p=lambda a,b:progress(t,a,b)
        # Reset transforms, making arbitrary frame access deterministic.
        for o in self.track:
            loc,rot,scale=self.defaults[o];o.location=loc;o.rotation_euler=rot;o.scale=scale;o.hide_render=o.hide_viewport=False
        self.camera.location=(0,0,30);self.camera.rotation_euler=(0,0,0);self.camera.data.ortho_scale=24
        for n,root in self.captions.items():
            delay=4.5 if n==2 else 1.7
            appear=1 if n==1 else p(B[n-1]+delay,B[n-1]+delay+.8)
            disappear=p(B[n]-.95,B[n]+.05) if n<10 else 0
            value=appear*(1-disappear)
            for socket in self.caption_opacity[n]:socket.default_value=value
            self.visibility(root,value>.002)
        # 1–2. A sub-second exponential dive resolves atomic sheets, THEN a
        # tetrahedron detaches. Surface layers pass beyond the frame in the dive.
        fracture=p(.9,6.8);zoom=p(B[1]-1.45,B[1]-.50)
        self.pose(self.mica,(-5+zoom*.5,0,0),math.exp(math.log(95)*zoom))
        for i,o in enumerate(self.mica_layers):
            o.location=(i*.10*fracture,(i-2)*(.18+.23*fracture)+(1 if i>=2 else -1)*zoom*4.5,i*.22)
        self.visibility(self.mica,zoom<.999)
        self.pose(self.quartz,(5+15*zoom,-1.3*fracture,0),1-.2*zoom)
        for o,dr,spin in self.shards:o.location=dr*fracture;o.rotation_euler=spin*fracture
        self.visibility(self.quartz,zoom<.999)
        # 2–3. The SAME Si/O tetrahedron recedes; neighbors gather into its sheet.
        pull=p(B[2]-1.1,B[2]+4.4);withdraw=p(B[3]-1.1,B[3]+3.2)
        extract=p(B[1]+2.0,B[1]+4.4)
        start=lerp((-7,-1,0),(-4.5,0,0),extract)
        intro=p(B[1]-1.13,B[1]-.45)
        self.pose(self.sheet,start.lerp(Vector((-7,-1,0)),pull)+Vector((-12*withdraw,0,-8*withdraw)),max(.00001,intro*(1+.35*(1-extract))*(1-.82*withdraw)),(.62,.18+.18*p(B[1],B[3]),.08))
        for i,(root,target,oxygen) in enumerate(self.units):
            arrive=p(B[2]-.1+i*.09,B[2]+3+i*.09)
            origin=target+Vector((13,9,-5))*extract
            root.location=target if i==0 else origin.lerp(target,arrive)
            size=((self.unit_size+(2.05-self.unit_size)*extract)*(1-pull)+self.unit_size*pull) if i==0 else self.unit_size
            root.scale=(max(.00001,size),)*3
            root.hide_render=False
            for o in root.children_recursive:o.hide_render=o.hide_viewport=intro<.002 or withdraw>.998
        for o in self.shared:
            if pull>.999 or extract<.002:o.hide_render=o.hide_viewport=True
        for layer,root in enumerate(self.mica_atomic_layers):
            root.location=(13*extract,9*extract,-(layer+1)*1.5-5*extract)
            for obj in root.children_recursive:obj.hide_render=obj.hide_viewport=intro<.002 or extract>.998
        netintro=p(B[2]+.5,B[2]+3.8)
        self.pose(self.network,(5+15*withdraw,0,-7*withdraw),max(.00001,netintro*(1-.85*withdraw)),(0,.22*p(B[2],B[3]),0));self.visibility(self.network,netintro>.002 and withdraw<.998)
        # 4–5. The first TWO chain carbons and their bond are retained as glycine.
        emerge=p(B[3]-1.5,B[3]+1.4);assemble=p(B[3]+1,B[3]+6.3);isolate=p(B[4]-1,B[4]+2)
        for i,(o,target) in enumerate(zip(self.carbons,self.carbon_targets)):
            if i==0:
                o.location=lerp((-4.5,0,2),target,assemble);o.scale=(.42*emerge,)*3
            else:
                a=i*2.399;start=Vector((-4.5+12*math.cos(a),8*math.sin(a),2*math.sin(a)))
                arrival=p(B[3]+.8+i*.07,B[3]+4.8+i*.07)
                retreat=isolate if i>1 else 0
                o.location=start.lerp(target,arrival)*(1-.55*retreat)+Vector((-14*retreat,-7*retreat,0));o.scale=(.30*arrival*(1-.7*retreat),)*3
            o.hide_render=o.hide_viewport=emerge<.002 or (i>1 and isolate>.998)
        for line,a,b in self.carbon_bonds:
            self.setline(line,self.carbons[a].location,self.carbons[b].location)
            retained=(a,b)==(0,1)
            line.data.bevel_factor_end=p(B[3]+3.6,B[3]+7.8)*(1 if retained else 1-p(B[4]-1.1,B[4]-.3));line.hide_render=line.hide_viewport=emerge<.002 or (not retained and t>B[4]-.3)
        # 5–7. Actual glycine atoms assemble; OH/H leave when peptide links form.
        collect=p(B[5]-1.2,B[5]+3.5);fold=p(B[5]+4,B[6]-.7);exit_chain=p(B[6]-.7,B[6]+2.7)
        amino_scale=1.25*(1-collect)+.40*collect;connect=p(B[5]+2,B[5]+4.5)
        chain_positions=[Vector((-8,0,0))];chain_rotations=[Euler((.3*fold*math.sin(i*.7),.25*fold*math.sin(i*.9),1.5*fold*math.sin(i*1.05-.8))) for i in range(7)]
        for i in range(1,7):
            prev=chain_positions[-1]+chain_rotations[i-1].to_matrix()@Vector((1.3,.4,0))*.4
            direction=chain_rotations[i-1].to_matrix()@Vector((.52,0,0))
            chain_positions.append(prev+direction-chain_rotations[i].to_matrix()@Vector((-1.3,.4,0))*.4)
        for i,(root,atoms,links) in enumerate(self.aminos):
            dest=chain_positions[i]
            if i==0:pos=Vector((-4.5,0,0)).lerp(dest,collect)
            else:
                start=Vector((-4+12*math.cos(i*2.4),8*math.sin(i*2.4),2))
                arrive=p(B[5]-.4+i*.14,B[5]+2.6+i*.14);pos=start.lerp(dest,arrive)
            pos.x-=21*exit_chain
            rotation=chain_rotations[i].copy();rotation.y+=.12*math.sin(t*.6)*(1-collect)
            self.pose(root,pos,amino_scale if i==0 else .40,rotation)
            for name,(obj,local) in atoms.items():
                assembly=p(B[4]+2.2,B[4]+6.0)
                if i==0:
                    k=list(atoms).index(name);angle=k*2.4;obj.location=local+Vector((math.cos(angle)*7,math.sin(angle)*6,1))*(1-assembly)
                else:obj.location=local
                leaving=(name in {'OH','HO'} and i<6) or (name=='HN2' and i>0)
                if leaving:obj.location+=Vector((0,-8*connect,0));obj.scale*=1-.9*connect
                obj.hide_render=obj.hide_viewport=(t<B[4]+2.2 if i==0 else t<B[5]-.5) or exit_chain>.998 or (leaving and connect>.998)
            positions={k:o.location for k,(o,_) in atoms.items()};positions['CA']=Vector((0,0,0))
            if i==0:positions['C']=Vector((1.3,.4,0))
            for line,a,b,double in links:
                off=Vector((.10,-.06,0)) if double else Vector()
                self.setline(line,positions[a]+off,positions[b]+off)
                line.data.bevel_factor_end=p(B[4]+4,B[4]+6.8) if i==0 else 1
                leaving=(b in {'OH','HO'} and i<6) or (b=='HN2' and i>0)
                line.hide_render=line.hide_viewport=(t<B[4]+2.2 if i==0 else t<B[5]-.5) or exit_chain>.998 or (leaving and connect>.02) or (i==0 and (a,b)==('CA','C'))
            if i==0:
                for index,local in enumerate((Vector(),Vector((1.3,.4,0)))):
                    carbon=self.carbons[index];dest=pos+rotation.to_matrix()@local*amino_scale
                    carbon.location=carbon.location.lerp(dest,isolate)
                    radius=(.42*emerge if index==0 else carbon.scale.x)*(1-isolate)+.30*amino_scale*isolate
                    carbon.scale=(radius,)*3;carbon.hide_render=carbon.hide_viewport=emerge<.002 or exit_chain>.998
                retained=self.carbon_bonds[0][0]
                self.setline(retained,self.carbons[0].location,self.carbons[1].location)
                retained.hide_render=retained.hide_viewport=emerge<.002 or exit_chain>.998
        # Transform peptide bond endpoints without depending on depsgraph order.
        for i,line in enumerate(self.peptide):
            a=self.aminos[i][0];b=self.aminos[i+1][0]
            self.setline(line,a.location+a.rotation_euler.to_matrix()@Vector((1.3,.4,0))*a.scale.x,b.location+b.rotation_euler.to_matrix()@Vector((-1.3,.4,0))*b.scale.x)
            line.data.bevel_factor_end=connect;line.hide_render=line.hide_viewport=connect<.002 or exit_chain>.998
        # 7–8. The chain exits left while the DNA enters from the right, then zooms.
        arrive=p(B[6]-.7,B[6]+2.7);dna_zoom=p(B[7]-.5,B[7]+3.5)
        self.pose(self.dna,(18-22.5*arrive-25*dna_zoom,0,-2),1+3.1*dna_zoom,(0,.13*math.sin(t*.4),0))
        self.visibility(self.dna,t>B[6]-.8 and dna_zoom<.998)
        nt_intro=p(B[7]+.15,B[7]+3.8);base_focus=p(B[8]-.6,B[8]+2.3)
        nt_turn=p(B[7]+3.8,B[8]-.6)*(1-base_focus)
        self.pose(self.nt,(-4.5,0,3),max(.00001,nt_intro),(0,.18*nt_turn,.10*nt_turn))
        for i,o in enumerate(self.nt_parts[:2]):o.location.x=(-3.2 if i==0 else 0)-14*base_focus;o.hide_render=o.hide_viewport=nt_intro<.002 or base_focus>.998
        for i,o in enumerate(self.nt_labels):o.scale=(max(.00001,1-base_focus),)*3;o.hide_render=o.hide_viewport=nt_intro<.002 or base_focus>.998
        # 9–10. A base symbol unfolds into four kinds, then a ordered strand.
        spread=p(B[8]+1,B[8]+4);row=p(B[8]+5,B[9]+1.5);pair=p(B[9]+1.5,B[9]+4.5);wind=p(B[9]+4.5,B[9]+7.8);helix=p(B[9]+6.5,B[10]-.1)
        for i,(base,o,label) in enumerate(zip(self.seq,self.bases,self.base_labels)):
            kind='ATGC'.index(base);typepos=Vector((-8+2.2*kind,0,3))
            rowpos=Vector((-8.7+.74*i,1.35,3))
            initial=Vector((-.8-3.7*base_focus,0,3))
            pos=initial.lerp(typepos,spread).lerp(rowpos,row)
            if i>=4:pos.y-=math.sin(math.pi*row)*(1.8+.4*(i%3))
            final=Vector(dna_point(i+2,0,.06+.94*helix,rise=.65))+Vector((-4.5,0,3))
            pos=pos.lerp(final,wind)
            size=(.68*(1-spread)+.42*spread)*(1-row)+(.34*(1-pair)+.25*pair)*row
            if i==0:
                # Keep the original base object and its parent throughout.
                o.location=(pos-self.nt.location)/max(.00001,nt_intro);o.scale=(size/max(.00001,nt_intro),)*3
            else:o.location=pos;o.scale=(size,)*3
            visible=nt_intro>.002 and (i==0 or (i<4 and spread>.005) or (i>=4 and row>.005))
            o.hide_render=o.hide_viewport=not visible
            label.location=pos+Vector((0,-.17*(1-pair)-.12*pair,.65));label.scale=(1-.25*pair,)*3;label.hide_render=label.hide_viewport=not visible or spread<.08
            obj,lab=self.complements[i];target=Vector(dna_point(i+2,1,.06+.94*helix,rise=.65))+Vector((-4.5,0,3))
            comp_row=Vector((-8.7+.74*i,-1.35,3))
            obj.location=Vector((-8+2.2*'ATGC'.index(complementary(base)),-4,3)).lerp(comp_row,pair).lerp(target,wind);obj.scale=(.25*pair,)*3
            obj.hide_render=obj.hide_viewport=pair<.003;lab.location=obj.location+Vector((0,-.12,.65));lab.hide_render=lab.hide_viewport=pair<.003
            self.setline(self.pairlinks[i],pos,obj.location);self.pairlinks[i].data.bevel_factor_end=pair;self.pairlinks[i].hide_render=self.pairlinks[i].hide_viewport=pair<.003
        for i,line in enumerate(self.nt_links):
            a=self.nt_parts[i].location;b=self.nt_parts[i+1].location;self.setline(line,a,b)
            line.hide_render=line.hide_viewport=nt_intro<.002 or base_focus>.05
        for line,strand,i in self.backbone:
            source=self.bases if strand==0 else [o for o,_ in self.complements]
            def world(o):return self.nt.location+o.location*nt_intro if o is self.bases[0] else o.location
            self.setline(line,world(source[i]),world(source[i+1]));line.hide_render=line.hide_viewport=(row<.98 if strand==0 else pair<.98)
        for o,i,strand in self.termini:
            obj=self.bases[i] if strand==0 else self.complements[i][0]
            pos=self.nt.location+obj.location*nt_intro if obj is self.bases[0] else obj.location
            offset=-.44 if i==0 else .30
            o.location=pos+Vector((-.25 if strand==0 else .25,offset,.8));o.hide_render=o.hide_viewport=pair<.98
        for obj in self.presentation_roots:
            pivot=Vector((-4.5,0,0));shift=Vector()
            if obj is self.mica:pivot=Vector((-5,0,0));shift.x=-.5
            elif obj in (self.quartz,self.network):
                pivot=Vector((5,0,0));shift.x=.5
                if obj is self.quartz:shift.y=.75*fracture
            if obj is self.sheet:shift.y=-2.2*(1-extract)*(1-pull)
            if obj is self.carbon_root or obj in self.peptide or any(obj is a[0] for a in self.aminos):
                # Lay the extended peptide diagonally, then unwind that layout
                # rotation as its own molecular fold takes over. All retained
                # carbons and bond curves receive the identical transform.
                center=Vector(((min(v.x for v in chain_positions)+max(v.x for v in chain_positions))/2,
                               (min(v.y for v in chain_positions)+max(v.y for v in chain_positions))/2,0))
                source=pivot.lerp(center,collect)
                transform=(Matrix.Translation(pivot)@Matrix.Rotation(.80*collect*(1-fold),4,'Z')
                           @Matrix.Scale(1.5,4)@Matrix.Translation(-source))
            else:
                transform=Matrix.Translation(pivot+shift)@Matrix.Scale(1.5,4)@Matrix.Translation(-pivot)
            obj.matrix_basis=transform@obj.matrix_basis
        return self.job['canonical_state_cache'][frame],self.track

    def bake(self):
        keys=set(range(0,self.job['duration_frames'],6))|{self.job['duration_frames']-1}
        for b in self.job['timeline']:keys.update((b['start_frame'],b['end_frame']-1))
        for f in sorted(keys):
            self.sample(f)
            for o in self.dynamic:
                for prop in ('location','rotation_euler','scale'):o.keyframe_insert(data_path=prop,frame=f+1)
                if o.type=='CURVE' and o.get('animate_points'):
                    for spline in o.data.splines:
                        for point in spline.points:point.keyframe_insert(data_path='co',frame=f+1)
                    o.data.keyframe_insert(data_path='bevel_factor_end',frame=f+1)
            for sockets in self.caption_opacity.values():
                for socket in sockets:socket.keyframe_insert(data_path='default_value',frame=f+1)
            for o in self.track:
                o.keyframe_insert(data_path='hide_render',frame=f+1);o.keyframe_insert(data_path='hide_viewport',frame=f+1)
        self.scene.frame_set(1);self.sample(0);self.font.pack();bpy.ops.file.pack_all()
