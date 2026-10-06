"""Presentation layout: unboxed type, reserved text areas, native animated 3D."""
import math
import bpy
from blackbody_gallery import BlackbodyGallery, COOL, HOT, GOLD, WHITE, MUTED, ease
from blackbody_math import normalized_spectrum, WIEN_NM_K, received_flux_ratio


class PresentationGallery(BlackbodyGallery):
    def sky(self):
        # A quiet, uniform slide background makes large type legible without plates.
        self.scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.003,.008,.018,1)

    def title(self, body):
        return self.label(body,-7.05,3.12,.98,WHITE,'LEFT')

    def caption(self,body,x,y,size=.78,color=WHITE,align='CENTER'):
        return self.label(body,x,y,size,color,align)

    def small(self,body,x,y,color=MUTED):
        return self.label(body,x,y,.46,color)

    def ui_line(self,name,x0,y0,x1,y1,color=WHITE,r=.018):
        o=self.line(name,[(x0,y0,0),(x1,y1,0)],color,r)
        o.parent=self.hud
        return o

    def bar(self,x,y,width,color):
        # These bars encode values; they are never behind text.
        o=self.rect('Energy bar',0,0,width,.18,color,0)
        o.parent=self.hud;o.location=(x+width/2,y,0);self.track(o)
        return o,x,width,y

    def opacity_group(self,objects,value):
        for o in objects:self.fade(o,value)

    def star_opacity(self,star,value):
        self.fade(star,value)
        halo=next((h for o,h,r in self.stars if o==star),None)
        if halo:self.fade(halo,value)

    def build_shot(self):
        s=self.sid
        if s==1:
            self.title('차가운데, 에너지는 더 많다')
            self.a=self.star_body('Betelgeuse portrait',(-3.65,.25,0),1.95,COOL)
            self.b=self.star_body('Bellatrix portrait',(3.65,.25,0),1.95,HOT)
            self.caption('베텔게우스',-3.65,-2.40,.90,COOL)
            self.caption('벨라트릭스',3.65,-2.40,.90,HOT)
            self.tags=[self.caption('온도 ↓  광도 ↑',-3.65,-3.58,.94,COOL),self.caption('온도 ↑  광도 ↓',3.65,-3.58,.94,HOT)]
        elif s in (2,3):
            self.title('빛의 분포로 읽는 온도' if s==2 else '짧은 최대 파장, 높은 온도')
            self.a=self.star_body('Cool spectrum source',(-5.6,1.15,0),1.1,COOL)
            self.b=self.star_body('Hot spectrum source',(-5.6,-1.75,0),1.1,HOT)
            self.caption('베텔게우스',-5.6,-.43,.64,COOL)
            self.caption('벨라트릭스',-5.6,-3.33,.64,HOT)
            self.x0=-2.7;self.x1=6.8;self.y0=-2.22;self.height=3.17
            self.line('Wavelength axis',[(self.x0,self.y0,0),(self.x1,self.y0,0)],MUTED,.020)
            self.line('Relative intensity axis',[(self.x0,self.y0,0),(self.x0,1.1,0)],MUTED,.020)
            for nm in (100,400,700,1000,1400):
                x=self.wx(nm);self.small(str(nm),x,-2.80)
            self.small('파장 (nm)',5.9,-3.49)
            self.small('정규화 세기',-1.6,1.35)
            self.graphs=[];self.peak_lines=[]
            for temp,col in ((3500,COOL),(15000,HOT)):
                self.graphs.append(self.line('Normalized blackbody shape',[(self.wx(100+i*1300/300),self.y0+self.height*normalized_spectrum(100+i*1300/300,temp),.08) for i in range(301)],col,.032))
                x=self.wx(WIEN_NM_K/temp)
                self.peak_lines.append(self.line('Peak projection',[(x,self.y0,.16),(x,self.y0+self.height,.16)],col,.018))
            self.small('자외선',self.wx(200),-3.49,HOT)
            self.small('가시광선',self.wx(550),-3.49,WHITE)
            self.small('적외선',self.wx(950),-3.49,COOL)
            self.wien=self.caption('λmax T = 일정',3.8,1.58,.87,GOLD)
            if s==2:
                self.definition=self.caption('흑체 모형으로 근사',3.0,1.60,.72,WHITE)
            else:
                self.temperature_curve=self.line('Changing temperature demonstration',[(self.wx(100+i*1300/128),self.y0+self.height*normalized_spectrum(100+i*1300/128,3500),.14) for i in range(129)],(.53,.63,.74),.02)
                self.peak_marker=self.star_body('Moving blackbody peak',(self.wx(WIEN_NM_K/3500),self.y0+self.height,.22),.09,WHITE)
        elif s==4:
            self.title('같은 면적, 같은 시간')
            self.patches=[self.patch('Surface patch T',(-4.85,.28,0),COOL),self.patch('Surface patch 2T',(-1.25,.28,0),HOT)]
            for o in self.patches:o.scale=(.75,)*3
            self.caption('T',-4.85,2.01,1.02,COOL);self.caption('2T',-1.25,2.01,1.02,HOT)
            self.caption('1',-4.85,-2.10,1.20,COOL);self.caption('16',-1.25,-2.10,1.20,HOT)
            self.m1=self.bar(-6.15,-2.65,2.6,COOL);self.m2=self.bar(-2.55,-2.65,2.6,HOT)
            self.caption('E = σT⁴',3.60,.7,1.40,GOLD)
            self.result=[self.caption('온도 2배',3.6,-.87,.87,HOT),self.caption('방출량 16배',3.6,-2.05,.87,WHITE)]
        elif s==5:
            self.title('거리 때문에 달라지는 밝기')
            self.a=self.star_body('Fixed luminosity star',(-5.3,.5,0),1.48,GOLD)
            self.detector=self.link('Moving observer',None);self.track(self.detector)
            bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.30,depth=.9,rotation=(0,math.pi/2,0))
            body=bpy.context.object;body.name='Observer telescope body';body.parent=self.detector;body.data.materials.append(self.material((.10,.26,.4)))
            bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.27,depth=.05,location=(-.47,0,0),rotation=(0,math.pi/2,0))
            lens=bpy.context.object;lens.name='Telescope lens';lens.parent=self.detector;lens.data.materials.append(self.material(HOT))
            self.ray=self.line('One path to detector',[(-3.99,.5,0),(-2.1,.5,0)],WHITE,.023)
            self.caption('방출량 일정',-4.9,-1.80,.82,GOLD)
            self.caption('멀어지는 관측기',-3.7,-2.65,.63,HOT)
            self.caption('거리 ↑',3.25,1.0,1.40,WHITE)
            self.caption('도착하는 빛 ↓',3.25,-.65,1.10,HOT)
            self.m1=self.bar(.70,-1.65,5.2,HOT)
            self.caption('관측된 밝기',3.3,-2.62,.75,HOT)
        elif s==6:
            self.title('같은 거리로 환산하면')
            self.a=self.star_body('Magnitude comparison left',(-4.85,.3,0),1.18,GOLD)
            self.b=self.star_body('Magnitude comparison right',(-1.50,.3,0),1.18,HOT)
            self.caption('10 pc',-3.2,1.92,1.03,WHITE)
            self.caption('5등급',-4.85,-1.65,.84,GOLD);self.caption('0등급',-1.50,-1.65,.84,HOT)
            self.m1=self.bar(-6.05,-2.17,2.4,GOLD);self.m2=self.bar(-2.70,-2.17,2.4,HOT)
            self.caption('1',-4.85,-3.05,1.12,GOLD);self.caption('100',-1.50,-3.05,1.12,HOT)
            self.caption('절대 등급',3.58,1.1,1.15,WHITE)
            self.caption('5등급 차이',3.58,-.45,.93,HOT)
            self.caption('밝기 100배',3.58,-1.82,1.00,GOLD)
        elif s==7:
            self.title('한 조각에서 별 전체로')
            self.a=self.star_body('Whole stellar surface',(-4.35,-.12,0),2.45,COOL)
            self.patch_obj=self.patch('One stellar surface patch',(-4.35,-.05,0),COOL)
            paths=[];radius=2.47
            for mu in (-.8,-.6,-.4,-.2,0,.2,.4,.6,.8):
                paths.append([(-4.35+radius*math.sqrt(1-mu*mu)*math.cos(a*math.tau/100),-.12+radius*mu,radius*math.sqrt(1-mu*mu)*math.sin(a*math.tau/100)) for a in range(101)])
            for a in range(16):
                theta=a*math.tau/16
                paths.append([(-4.35+radius*math.sin(t*math.pi/100)*math.cos(theta),-.12+radius*math.cos(t*math.pi/100),radius*math.sin(t*math.pi/100)*math.sin(theta)) for t in range(101)])
            curve=bpy.data.curves.new('Equal area surface grid','CURVE');curve.dimensions='3D';curve.bevel_depth=.012;curve.bevel_resolution=1
            for path in paths:
                sp=curve.splines.new('POLY');sp.points.add(len(path)-1)
                for point,co in zip(sp.points,path):point.co=(*co,1)
            self.grid=self.link('Equal area surface grid',curve);curve.materials.append(self.material(GOLD));self.track(self.grid)
            self.caption('별의 표면',-4.35,-3.45,.87,COOL)
            self.flabels=[self.caption('전체 표면적',2.8,1.53,.65,MUTED),self.caption('4πR²',2.8,.3,1.48,COOL),self.caption('× σT⁴',2.8,-1.22,1.48,HOT)]
            self.result=self.caption('L = 4πR²σT⁴',2.65,-3.02,1.02,GOLD)
        elif s==8:
            self.title('낮은 온도를 이기는 표면적')
            self.a=self.star_body('Large cool star',(-4.8,0,-1),2.30,COOL)
            self.b=self.star_body('Smaller hot star',(-1.25,0,0),.83,HOT)
            self.caption('베텔게우스',-4.8,-3.16,.77,COOL)
            self.caption('벨라트릭스',-1.15,-1.75,.63,HOT)
            self.caption('온도는 낮아도',3.2,1.20,.98,WHITE)
            self.caption('표면적이 크면',3.2,-.25,1.04,COOL)
            self.result=self.caption('광도는 더 크다',3.2,-1.77,1.04,GOLD)
        elif s==9:
            self.title('온도와 광도 → 반지름')
            self.a=self.star_body('Radius inference star',(-4.5,-.1,0),2.45,COOL)
            self.radius=self.line('Projected radius',[(-4.5,-.1,2.55),(-2.05,-.1,2.55)],GOLD,.04)
            # Place the radius label outside the stellar disk.
            self.caption('반지름 R',-4.5,-3.42,1.0,GOLD)
            self.caption('L = 4πR²σT⁴',2.8,1.2,1.24,WHITE)
            self.derived=[self.caption('R =',.65,-.78,1.22,GOLD),self.caption('L',4.25,-.03,1.20,GOLD),self.caption('4πσT⁴',4.25,-1.55,1.16,GOLD)]
            self.derived.append(self.ui_line('Fraction rule',2.65,-.28,6.02,-.28,GOLD,.021))
            self.derived.append(self.ui_line('Radical left',2.02,-.66,2.22,-.96,GOLD,.025))
            self.derived.append(self.ui_line('Radical rising',2.22,-.96,2.57,.74,GOLD,.025))
            self.derived.append(self.ui_line('Radical vinculum',2.57,.74,6.25,.74,GOLD,.025))
        elif s==10:
            self.title('온도 ½배, 광도 100배')
            self.a=self.star_body('Sun observation portrait',(-5.25,.85,0),1.29,GOLD)
            self.b=self.star_body('Star A observation portrait',(-5.25,-2.0,0),1.29,COOL)
            self.caption('태양',-2.70,1.27,.78,GOLD,'LEFT')
            self.caption('T = 1   L = 1',-2.70,.20,1.04,WHITE,'LEFT')
            self.caption('가상 별 A',-2.70,-1.39,.78,COOL,'LEFT')
            self.caption('T = ½   L = 100',-2.70,-2.48,1.04,WHITE,'LEFT')
            self.question=self.caption('R = ?',5.25,-.35,1.55,HOT)
        elif s==11:
            self.title('표면적 1600배 → 반지름 40배')
            # A fixed orthographic-like perspective at z=330 keeps the 40:1 pair in the left field.
            self.a=self.star_body('Hypothetical star radius 40',(-70,-1,0),40,COOL)
            self.b=self.star_body('Reference sun radius 1',(-17,-1,0),1,GOLD)
            self.working=[self.caption('(½)⁴ = 1/16',0,1.0,1.20,HOT),self.caption('100 ÷ (1/16) = 1600',0,-.68,1.05,WHITE),self.caption('√1600 = 40',0,-2.36,1.32,GOLD)]
            self.final_labels=[self.caption('가상 별 A',-4.65,-3.13,.68,COOL),self.caption('태양',-1.10,-.89,.50,GOLD),self.caption('R = 40R☉',3.1,1.14,1.24,WHITE),self.caption('같은 축척 40 : 1',3.1,-.1,.65,WHITE)]
            self.inset=self.star_body('Magnified Sun inset',(10000,0,0),1,GOLD)
            self.stars=[entry for entry in self.stars if entry[0]!=self.inset]
            bpy.data.objects.get('Magnified Sun inset glow').hide_render=True
            self.inset.parent=self.hud;self.inset.location=(3.1,-1.55,.25);self.inset.scale=(.63,)*3
            self.final_labels.append(self.caption('태양 확대',3.1,-2.90,.65,GOLD))
        elif s==12:
            self.title('빛으로 알아내는 별의 물리량')
            self.a=self.star_body('Cool closing star',(-5.55,1.20,0),1.28,COOL)
            self.b=self.star_body('Hot closing star',(-5.55,-1.75,0),1.28,HOT)
            self.summary=[self.caption('복사 분포 → 온도 T',1.85,1.3,1.00,HOT),self.caption('밝기 + 거리 → 광도 L',1.85,-.30,1.00,GOLD),self.caption('T + L → 반지름 R',1.85,-1.95,1.16,WHITE)]
        self.track(self.camera)

    def sample(self,p,t):
        s=self.sid;self.aim((0,0,22))
        for star,halo,r in self.stars:star.rotation_euler=(math.pi/2,.055*t,.08)
        if s==1:
            self.opacity_group(self.tags,ease((p-.30)/.20))
        elif s in (2,3):
            for o in self.graphs:self.revealed(o,(p-.08)/.66 if s==2 else 1)
            for o in self.peak_lines:
                o.scale=(1,1,1) if s==3 else (0,0,0)
                self.revealed(o,(p-.10)/.32)
            self.fade(self.wien,ease((p-.22)/.20) if s==3 else 0)
            if s==3:
                temperature=3500+(15000-3500)*ease((p-.10)/.60)
                self.peak_marker.location.x=self.wx(WIEN_NM_K/temperature)
                for i,point in enumerate(self.temperature_curve.data.splines[0].points):
                    nm=100+i*1300/128;point.co=(self.wx(nm),self.y0+self.height*normalized_spectrum(nm,temperature),.14,1)
        elif s==4:
            for i,o in enumerate(self.patches):o.rotation_euler=(.14+.08*math.sin(t*.5),(-1 if i else 1)*(.15+.07*math.sin(t*.35)),0)
            q=ease((p-.10)/.56);self.fill(self.m1,q/16);self.fill(self.m2,q)
            self.opacity_group(self.result,ease((p-.33)/.22))
        elif s==5:
            x=-2.8+1.9*ease((p-.12)/.70);self.detector.location=(x,.5,0)
            self.ray.data.splines[0].points[1].co=(x-.47,.5,0,1)
            self.fill(self.m1,received_flux_ratio((x+5.3)/2.5))
        elif s==6:
            q=ease((p-.25)/.50);self.fill(self.m1,q/100);self.fill(self.m2,q)
        elif s==7:
            q=ease((p-.16)/.24);self.star_opacity(self.a,q);self.fade(self.patch_obj,1-q)
            self.patch_obj.rotation_euler=(.10+.12*math.sin(t*.4),-.15,0)
            self.fade(self.grid,ease((p-.27)/.42)*.8)
            for i,o in enumerate(self.flabels):self.fade(o,ease((p-.32-i*.08)/.15))
            self.fade(self.result,ease((p-.68)/.16))
        elif s==8:
            self.camera.data.lens=50 # Radius comparison stays fixed while the surfaces rotate.
            self.fade(self.result,ease((p-.44)/.22))
        elif s==9:
            self.revealed(self.radius,p/.35);self.opacity_group(self.derived,ease((p-.32)/.22))
        elif s==10:
            self.fade(self.question,ease((p-.55)/.18))
        elif s==11:
            self.aim((0,0,330));q=ease((p-.70)/.12)
            for i,o in enumerate(self.working):self.fade(o,ease((p-i*.17)/.13)*(1-ease((p-.59)/.10)))
            self.opacity_group(self.final_labels,q);self.fade(self.inset,q)
            self.inset.rotation_euler=(math.pi/2,.055*t,0)
            for star,halo,r in self.stars:
                self.fade(star,q)
                if halo:self.fade(halo,q)
        elif s==12:
            for i,o in enumerate(self.summary):self.fade(o,ease((p-i*.23)/.16))
        for star,halo,r in self.stars:
            if halo:
                normal=(self.camera.location-star.location).normalized();halo.location=star.location-normal*r*.4;halo.rotation_euler=normal.to_track_quat('Z','Y').to_euler()
        self.scene.view_layers[0].update()
