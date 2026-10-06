"""Native, editable 3D shots for the approved blackbody storyboard."""
import math, random
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
from scene import SpectralGallery, INK
from blackbody_math import normalized_spectrum, WIEN_NM_K, received_flux_ratio
from animated_materials import fade_material

COOL=(1,.29,.055); HOT=(.30,.68,1); GOLD=(1,.72,.22); WHITE=(.86,.93,1); MUTED=(.34,.49,.66)
def ease(x):
    x=max(0,min(1,x));return x*x*(3-2*x)
def mix(a,b,p):return Vector(a).lerp(Vector(b),p)

class BlackbodyGallery(SpectralGallery):
    def __init__(self,sid,width=1920,height=1080,fps=30,count=360):
        self.sid=sid;self.materials={};self.dynamic=[];self.stars=[];self.fades=[];self.curves=[]
        self.scene=bpy.data.scenes.new('Blackbody %02d'%sid)
        if bpy.context.window:bpy.context.window.scene=self.scene
        self.font=bpy.data.fonts.load('/System/Library/Fonts/Supplemental/AppleGothic.ttf')
        self.job={'output':{'width':width,'height':height},'canonical_fps':fps,'duration_frames':count}
        self.configure();self.camera.data.type='PERSP';self.camera.data.lens=50
        self.camera.data.clip_end=5000;self.camera.location=(0,0,22)
        self.scene.world.use_nodes=True;self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.003,.008,.018,1)
        self.hud=self.link('Camera-facing labels',None);self.hud.parent=self.camera;self.hud.location=(0,0,-5);self.hud.scale=(5/22,)*3
        self.sky();self.build_shot();self.sample(0,0)
    def track(self,obj):
        if obj not in self.dynamic:self.dynamic.append(obj)
        return obj
    def label(self,body,x,y,size=.38,color=WHITE,align='CENTER'):
        obj=self.text(body,0,0,size,color,align);obj.parent=self.hud;obj.location=(x,y,0);self.track(obj);return obj
    def plate(self,x,y,w,h,color=(.005,.016,.035)):
        obj=self.rect('Label backing',x,y,w,h,color,-.05);obj.parent=self.hud;return obj
    def title(self,kicker,title):
        self.plate(0,3.52,15.9,1.35)
        self.label(kicker,-7,3.72,.20,HOT,'LEFT');self.label(title,-7,3.04,.48,WHITE,'LEFT')
    def fade(self,obj,p):
        if 'opacity' not in obj:
            socket=fade_material(obj);obj['opacity']=True;self.fades.append((obj,socket))
        else:socket=next(socket for o,socket in self.fades if o==obj)
        socket.default_value=max(0,min(1,p));return obj
    def star_body(self,name,pos,r,color):
        obj=self.star(name,pos[0],pos[1],r,color);obj.location=pos
        halo=bpy.data.objects.get(name+' glow');self.stars.append((obj,halo,r));self.track(obj)
        if halo:self.track(halo)
        return obj
    def line(self,name,points,color=HOT,r=.025):
        obj=self.path(name,points,color,r);self.track(obj);return obj
    def revealed(self,obj,p):obj.data.bevel_factor_end=ease(p)
    def aim(self,pos,target=(0,0,0)):
        self.camera.location=pos
        forward=(Vector(target)-Vector(pos)).normalized();right=forward.cross(Vector((0,1,0))).normalized();up=right.cross(forward).normalized()
        self.camera.rotation_euler=Matrix((right,up,-forward)).transposed().to_euler()
    def sky(self):
        rng=random.Random(916);verts=[];faces=[]
        for i in range(180):
            x=rng.uniform(-380,380);y=rng.uniform(-210,210);r=rng.uniform(.10,.37);b=len(verts)
            verts.extend([(x-r,y-r,0),(x+r,y-r,0),(x+r,y+r,0),(x-r,y+r,0)]);faces.append((b,b+1,b+2,b+3))
        mesh=bpy.data.meshes.new('Distant sky');mesh.from_pydata(verts,[],faces);mesh.materials.append(self.material((.14,.23,.37)))
        obj=self.link('Distant sky',mesh);obj.parent=self.camera;obj.location=(0,0,-1000)
    def meter(self,x,y,width,color,label):
        self.plate(x+width/2,y,width,.18,(.015,.036,.060))
        o=self.rect('Measured energy',0,0,width,.18,color,0);o.parent=self.hud;o.location=(x+width/2,y,.02);self.track(o)
        self.label(label,x,y-.40,.24,MUTED,'LEFT');return (o,x,width,y)
    def fill(self,m,value):
        o,x,w,y=m;o.scale.x=max(.001,value);o.location.x=x+w*max(.001,value)/2
    def patch(self,name,pos,color):
        n=24;r=4;v=[];uv=[];f=[]
        for j in range(n+1):
            b=-.48+.96*j/n
            for i in range(n+1):
                a=-.48+.96*i/n;v.append((r*math.sin(a)*math.cos(b),r*math.sin(b),r*(math.cos(a)*math.cos(b)-1)));uv.append((.5+a/6.28,.5+b/3.14))
        for j in range(n):
            for i in range(n):
                q=j*(n+1)+i;f.append((q,q+1,q+n+2,q+n+1))
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(v,[],f);layer=mesh.uv_layers.new()
        for face in mesh.polygons:
            face.use_smooth=True
            for li in face.loop_indices:layer.data[li].uv=uv[mesh.loops[li].vertex_index]
        obj=self.link(name,mesh);obj.location=pos
        template=self.star_body(name+' material source',(10000,0,0),1,color);mesh.materials.append(template.data.materials[0]);template.hide_render=True
        self.stars=[entry for entry in self.stars if entry[0]!=template]
        halo=bpy.data.objects.get(name+' material source glow')
        if halo:halo.hide_render=True
        solid=obj.modifiers.new('Physical thickness','SOLIDIFY');solid.thickness=.13
        self.track(obj);return obj
    def build_shot(self):
        s=self.sid
        if s in (1,12):
            self.a=self.star_body('Betelgeuse portrait',(-3.7,0,0),2.4,COOL);self.b=self.star_body('Bellatrix portrait',(3.7,0,0),2.4,HOT)
            self.label('베텔게우스',-3.7,-2.72,.40,COOL);self.label('벨라트릭스',3.7,-2.72,.40,HOT)
            if s==1:
                self.title('01 / 두 별의 수수께끼','더 차가운데, 더 많은 에너지?')
                self.plate(-3.7,2.43,4.2,.52);self.plate(3.7,2.43,4.2,.52)
                self.tag_a=self.label('온도 ↓    광도 ↑',-3.7,2.25,.38,COOL);self.tag_b=self.label('온도 ↑    광도 ↓',3.7,2.25,.38,HOT)
                self.label('서로 다른 확대율의 관측 창',0,-3.70,.23,MUTED)
            else:
                self.title('12 / 빛으로 읽는 별','온도와 광도를 알면, 크기가 보인다')
                self.summary=[self.label(body,0,y,.46,col) for body,y,col in [('복사 분포  →  온도 T',1.6,HOT),('밝기 + 거리  →  광도 L',.25,GOLD),('온도 T + 광도 L  →  반지름 R',-1.2,WHITE)]]
        elif s in (2,3):
            self.title('02 / 빛의 분포' if s==2 else '03 / 빈의 변위 법칙','빛을 펼치면 온도가 드러난다' if s==2 else '최대 파장이 짧을수록, 더 뜨겁다')
            self.a=self.star_body('Cool spectrum source',(-5.3,1.0,0),1.28,COOL);self.b=self.star_body('Hot spectrum source',(-5.3,-1.85,0),1.05,HOT)
            self.label('베텔게우스',-5.3,2.45,.30,COOL);self.label('벨라트릭스',-5.3,-3.18,.30,HOT)
            self.x0=-2.65;self.x1=6.55;self.y0=-1.95
            self.line('Wavelength axis',[(self.x0,self.y0,0),(self.x1,self.y0,0)],MUTED,.014)
            self.line('Relative intensity axis',[(self.x0,self.y0,0),(self.x0,2.0,0)],MUTED,.014)
            for nm in [100,400,700,1000,1400]:
                x=self.wx(nm);self.label(str(nm),x,-2.34,.21,MUTED);self.line('Wavelength tick',[(x,-1.95,0),(x,-2.03,0)],MUTED,.012)
            self.label('파장 (nm)',5.8,-2.78,.23,MUTED);self.label('상대 세기',-1.9,2.25,.23,MUTED)
            # Shape-only illustrative blackbody curves; neither is a fitted observation.
            self.graphs=[]
            for temp,col,name in [(3500,COOL,'Cool normalized shape'),(15000,HOT,'Hot normalized shape')]:
                pts=[(self.wx(nm),self.y0+3.55*normalized_spectrum(nm,temp),.08) for nm in [100+i*1300/300 for i in range(301)]]
                self.graphs.append(self.line(name,pts,col,.028))
            self.label('자외선',self.wx(200),-2.73,.20,HOT);self.label('가시광선',self.wx(550),-2.73,.20,WHITE);self.label('적외선',self.wx(1000),-2.73,.20,COOL)
            self.label('흑체 근사 분포 · 모양 비교를 위해 높이 정규화',1.65,-3.35,.24,MUTED)
            self.rays=[self.line('Single representative stellar ray',[(x,y,0),(-2.85,y*.55,0)],col,.015) for x,y,col in [(-3.9,1,COOL),(-4.15,-1.85,HOT)]]
            self.peak_lines=[]
            for temp,col in [(3500,COOL),(15000,HOT)]:
                x=self.wx(WIEN_NM_K/temp);self.peak_lines.append(self.line('Peak projection',[(x,self.y0,.16),(x,self.y0+3.55,.16)],col,.014))
            self.wien=self.label('λmax × T = 일정',1.8,2.25,.40,GOLD)
            if s==3:
                self.temperature_curve=self.line('Changing temperature demonstration',[(self.wx(100+i*1300/128),self.y0+3.55*normalized_spectrum(100+i*1300/128,3500),.14) for i in range(129)],(.53,.63,.74),.015)
                self.peak_marker=self.star_body('Moving blackbody peak',(self.wx(WIEN_NM_K/3500),self.y0+3.55,.22),.085,WHITE)
            self.definition=self.label('흑체: 들어오는 빛을 모두 흡수하는 이상적인 물체',0,-3.93,.21,MUTED)
        elif s==4:
            self.title('04 / 같은 면적, 같은 시간','온도 두 배 → 방출 에너지 열여섯 배')
            self.patches=[self.patch('Surface patch T',(-3.5,.15,0),COOL),self.patch('Surface patch 2T',(3.5,.15,0),HOT)]
            self.label('온도 T',-3.5,2.05,.44,COOL);self.label('온도 2T',3.5,2.05,.44,HOT)
            self.m1=self.meter(-5.3,-2.38,3.6,COOL,'같은 면적에서 방출한 에너지');self.m2=self.meter(1.7,-2.38,3.6,HOT,'같은 면적에서 방출한 에너지')
            self.label('1',-3.5,-1.94,.52,COOL);self.label('16',3.5,-1.94,.52,HOT)
            self.form=self.label('E = σT⁴',0,-3.55,.48,GOLD)
        elif s==5:
            self.title('05 / 거리와 겉보기 밝기','별은 그대로, 도착하는 빛은 줄어든다')
            self.a=self.star_body('Fixed luminosity star',(-4,0,0),2.0,GOLD)
            self.detector=self.link('Moving observer',None);self.track(self.detector)
            bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.45,depth=1.7,location=(0,0,0),rotation=(0,math.pi/2,0));body=bpy.context.object;body.name='Observer telescope body';body.parent=self.detector;body.data.materials.append(self.material((.10,.26,.4)))
            bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.36,depth=.08,location=(-.9,0,0),rotation=(0,math.pi/2,0));lens=bpy.context.object;lens.name='Telescope lens';lens.parent=self.detector;lens.data.materials.append(self.material(HOT))
            self.ray=self.line('One path to detector',[(-1.98,0,0),(0,0,0)],WHITE,.021)
            self.label('별의 방출량: 일정',-3.8,2.02,.30,GOLD);self.label('관측기',4.5,.9,.28,HOT)
            self.m1=self.meter(1.0,-2.65,5.0,HOT,'관측된 밝기');self.label('거리가 멀어질수록 감소',0,-3.7,.36,WHITE)
        elif s==6:
            self.title('06 / 절대 등급','같은 거리로 환산해서 비교한다')
            self.a=self.star_body('Magnitude comparison left',(-3.6,.1,0),1.8,GOLD);self.b=self.star_body('Magnitude comparison right',(3.6,.1,0),1.8,HOT)
            self.label('10 pc',-3.6,2.12,.42,WHITE);self.label('10 pc',3.6,2.12,.42,WHITE)
            self.label('절대 등급 5',-3.6,-2.02,.42,GOLD);self.label('절대 등급 0',3.6,-2.02,.42,HOT)
            self.m1=self.meter(-5.5,-2.68,3.8,GOLD,'밝기 1');self.m2=self.meter(1.7,-2.68,3.8,HOT,'밝기 100')
            self.label('5등급 차이 = 100배   ·   전 파장 기준',0,-3.76,.32,WHITE)
        elif s==7:
            self.title('07 / 한 조각에서 별 전체로','광도 = 표면적 × 단위 면적의 방출량')
            self.a=self.star_body('Whole stellar surface',(-3.4,0,0),2.7,COOL)
            pts=[];radius=2.72
            for mu in [-.8,-.6,-.4,-.2,0,.2,.4,.6,.8]:
                ring=[(-3.4+radius*math.sqrt(1-mu*mu)*math.cos(a*math.tau/100),radius*mu,radius*math.sqrt(1-mu*mu)*math.sin(a*math.tau/100)) for a in range(101)]
                pts.append(ring)
            for a in range(16):
                theta=a*math.tau/16;pts.append([(-3.4+radius*math.sin(t*math.pi/100)*math.cos(theta),radius*math.cos(t*math.pi/100),radius*math.sin(t*math.pi/100)*math.sin(theta)) for t in range(101)])
            curve=bpy.data.curves.new('Equal area surface grid','CURVE');curve.dimensions='3D';curve.bevel_depth=.009;curve.bevel_resolution=1
            for path in pts:
                sp=curve.splines.new('POLY');sp.points.add(len(path)-1)
                for p,co in zip(sp.points,path):p.co=(*co,1)
            self.grid=self.link('Equal area surface grid',curve);curve.materials.append(self.material(GOLD));self.track(self.grid)
            self.formulas=[self.label(body,3.05,y,size,col) for body,y,size,col in [('표면적',1.6,.32,MUTED),('4πR²',.9,.62,COOL),('×',.03,.5,WHITE),('σT⁴',-.85,.62,HOT),('L = 4πR²σT⁴',-2.22,.48,GOLD)]]
            self.label('같은 면적의 조각을 별 전체에 더한다',0,-3.7,.31,WHITE)
        elif s==8:
            self.title('08 / 광도의 반전','낮은 온도를 넘어서는 거대한 표면적')
            self.a=self.star_body('Large cool star',(-4.5,0,-2),5.1,COOL);self.b=self.star_body('Smaller hot star',(5.3,.1,0),1.65,HOT)
            self.plate(-3.7,2.37,3.35,.63);self.plate(-3.6,-2.22,4.5,.62)
            self.label('베텔게우스',-3.7,2.18,.40,COOL);self.label('벨라트릭스',4.65,1.62,.38,HOT)
            self.label('낮은 온도 · 큰 표면적',-3.6,-2.43,.32,COOL);self.label('높은 온도',4.6,-1.78,.30,HOT)
            self.label('총 방출 에너지, 광도는 베텔게우스가 더 크다',0,-3.60,.34,WHITE)
            self.label('크기 관계 비교',5.5,-3.98,.20,MUTED)
        elif s==9:
            self.title('09 / 거꾸로 추론하기','온도와 광도에서 반지름을 구한다')
            self.a=self.star_body('Radius inference star',(-4.05,-.1,0),2.62,COOL)
            self.radius=self.line('Projected radius',[(-4.05,-.1,2.8),(-1.43,-.1,2.8)],GOLD,.035)
            self.label('R',-2.8,.38,.5,GOLD)
            self.form1=self.label('L = 4πR²σT⁴',2.8,1.42,.62,WHITE)
            self.form2=self.label('R = √(L / 4πσT⁴)',2.8,-.42,.58,GOLD)
            self.label('이미 아는 값: L, T',2.8,-2.01,.35,HOT)
        elif s==10:
            self.title('10 / 계산 예시','온도는 절반, 광도는 백 배')
            self.a=self.star_body('Sun observation portrait',(-3.6,0,0),2,GOLD);self.b=self.star_body('Star A observation portrait',(3.6,0,0),2,COOL)
            self.label('태양',-3.6,2.26,.42,GOLD);self.label('가상 별 A',3.6,2.26,.42,COOL)
            self.label('온도 1    광도 1',-3.6,-2.42,.37,WHITE);self.label('온도 0.5    광도 100',3.6,-2.42,.37,WHITE)
            self.label('반지름은 몇 배일까?',0,-3.55,.44,HOT)
        elif s==11:
            self.title('11 / 계산 예시의 답','표면적은 1600배, 반지름은 40배')
            self.a=self.star_body('Hypothetical star radius 40',(-10,-3,0),40,COOL);self.b=self.star_body('Reference sun radius 1',(38,-3,0),1,GOLD)
            self.formulas=[self.label(body,0,y,.52,col) for body,y,col in [('표면 방출량  (0.5)⁴ = 1/16',1.5,HOT),('표면적  100 ÷ (1/16) = 1600',.2,WHITE),('반지름  √1600 = 40',-1.12,GOLD)]]
            self.answer=self.label('R = 40 R☉',3.1,.55,.63,WHITE)
            self.answer_plate=self.plate(3.4,.88,5.3,1.1)
            self.inset=self.star_body('Magnified Sun inset',(10000,0,0),1,GOLD)
            self.stars=[entry for entry in self.stars if entry[0]!=self.inset]
            bpy.data.objects.get('Magnified Sun inset glow').hide_render=True
            self.inset.parent=self.hud;self.inset.location=(5.3,-1.60,.25);self.inset.scale=(.58,)*3
            self.inset_label=self.label('태양 확대',5.3,-2.55,.24,GOLD)
            self.plate(-2.7,-2.71,2.6,.57);self.label('가상 별 A',-2.7,-2.9,.32,COOL);self.label('태양',3.45,-.72,.25,GOLD)
            self.label('마지막 두 구체의 반지름 비율 40 : 1',0,-3.76,.29,WHITE)
        self.track(self.camera)
    def wx(self,nm):return self.x0+(self.x1-self.x0)*(nm-100)/1300
    def sample(self,p,t):
        s=self.sid;self.aim((.35*math.sin(p*math.pi),.2*math.sin(p*math.pi),22))
        for star,halo,r in self.stars:
            star.rotation_euler=(math.pi/2,.055*t,.08)
        if s==1:
            self.aim((.4*math.sin(p*math.pi),.15,23.5-1.5*ease(p)))
            self.fade(self.tag_a,ease((p-.32)/.24));self.fade(self.tag_b,ease((p-.32)/.24))
        elif s in (2,3):
            self.aim((0,0,22))
            q=ease((p-.10)/.62) if s==2 else 1
            for o in self.graphs:self.revealed(o,q)
            for o in self.rays:self.revealed(o,p/.22 if s==2 else 1)
            for o in self.peak_lines:o.scale=(1,1,1) if s==3 else (0,0,0);self.revealed(o,(p-.10)/.32)
            if s==3:
                temperature=3500+(15000-3500)*ease((p-.10)/.60)
                self.peak_marker.location.x=self.wx(WIEN_NM_K/temperature)
                for i,point in enumerate(self.temperature_curve.data.splines[0].points):
                    nm=100+i*1300/128;point.co=(self.wx(nm),self.y0+3.55*normalized_spectrum(nm,temperature),.14,1)
            self.fade(self.wien,ease((p-.30)/.23) if s==3 else 0);self.fade(self.definition,1 if s==2 else 0)
        elif s==4:
            self.aim((.8*math.sin(p*math.pi),-1.2+1.2*ease(p),22))
            for i,o in enumerate(self.patches):o.rotation_euler=(.15+.09*math.sin(t*.5),(-1 if i else 1)*(.15+.08*math.sin(t*.35)),0)
            q=ease((p-.15)/.55);self.fill(self.m1,q/16);self.fill(self.m2,q)
            self.fade(self.form,ease((p-.48)/.25))
        elif s==5:
            self.aim((1,-3.5,23),(0,0,0));q=ease((p-.12)/.70);x=1+4.8*q;self.detector.location=(x,0,0)
            self.ray.scale.x=(x-.9+1.98)/1.98
            # The path endpoint is updated explicitly, leaving its origin fixed.
            self.ray.scale.x=1;self.ray.data.splines[0].points[1].co=(x-.9,0,0,1)
            self.fill(self.m1,received_flux_ratio((x+4)/5))
        elif s==6:
            self.aim((.3*math.sin(p*math.pi),-.2,22.7));q=ease((p-.25)/.50);self.fill(self.m1,q/100);self.fill(self.m2,q)
        elif s==7:
            q=ease(p/.72);self.aim(mix((-3.4,-.8,6.7),(0,0,23),q),mix((-3.4,0,2.0),(0,0,0),q))
            self.grid.scale=(1,1,1);self.fade(self.grid,ease((p-.17)/.45)*.7)
            for i,o in enumerate(self.formulas):self.fade(o,ease((p-.48-i*.045)/.17))
        elif s==8:
            self.aim(mix((-2,-.3,21),(0,.2,35),ease(p/.80)),mix((-2,0,0),(0,0,0),ease(p/.80)))
        elif s==9:
            self.aim((.25*math.sin(p*math.pi),0,22));self.revealed(self.radius,p/.35)
            self.fade(self.form1,1-.45*ease((p-.45)/.3));self.fade(self.form2,ease((p-.35)/.25))
        elif s==10:
            self.aim((.35*math.sin(p*math.pi),-.12,22.5));
        elif s==11:
            q=ease((p-.60)/.22);self.aim((0,0,250))
            for i,o in enumerate(self.formulas):self.fade(o,ease((p-i*.18)/.13)*(1-q))
            self.fade(self.answer,q);self.fade(self.answer_plate,q);self.fade(self.inset,q);self.fade(self.inset_label,q)
            self.inset.rotation_euler=(math.pi/2,.055*t,0)
            # Fixed radii: reveal by opacity, never by changing the physical ratio.
            for star,halo,r in self.stars:
                self.fade(star,q)
                if halo:self.fade(halo,q)
        elif s==12:
            self.aim((0,0,25+12*ease(p)));self.a.location=(-5.0,0,-5);self.b.location=(5.0,0,-5)
            for i,o in enumerate(self.summary):self.fade(o,ease((p-i*.22)/.16))
        for star,halo,r in self.stars:
            if halo:
                normal=(self.camera.location-star.location).normalized();halo.location=star.location-normal*r*.4;halo.rotation_euler=normal.to_track_quat('Z','Y').to_euler()
        self.scene.view_layers[0].update()
    def bake(self,count,fps):
        for f in range(count):
            self.sample(f/max(1,count-1),f/fps)
            for o in self.dynamic:
                for key in ['location','rotation_euler','scale']:o.keyframe_insert(data_path=key,frame=f+1)
                if o.type=='CURVE':o.data.keyframe_insert(data_path='bevel_factor_end',frame=f+1)
            if self.sid==3:
                for point in self.temperature_curve.data.splines[0].points:point.keyframe_insert(data_path='co',frame=f+1)
            for o,socket in self.fades:socket.keyframe_insert(data_path='default_value',frame=f+1)
        self.scene.frame_set(1)
