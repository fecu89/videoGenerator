"""Camera moves and object handoffs for the native vorticity gallery."""
import math
from mathutils import Matrix,Vector
from animated_materials import fade_all_materials
from scene import CYAN,GOLD
from vorticity_direction_math import framing,smooth,window

PINK=(1.,.23,.42)


class VorticityDirection:
    def __init__(self,gallery):
        self.g=gallery
        self.light=next(o for o in gallery.scene.objects if o.type=='LIGHT')
        gallery.scene.view_layers[0].update()
        self.hud={o:o.matrix_world.copy() for key,objects in gallery.groups.items()
                  if key.startswith('label') for o in objects}
        self.hud.update({o:o.matrix_world.copy() for o in
                         [gallery.bar_f,gallery.bar_z,*gallery.bar_labels]})
        self.ring_thickness={}
        for name,radius,ratio in [('NegativeRotorRing',.85,.85/3.3),('AirParcelRing',.55,.55)]:
            obj=next((o for o in gallery.scene.objects if o.name==name or o.name.startswith(name+'.')),None)
            if obj is None:continue
            obj.shape_key_add(name='Basis')
            key=obj.shape_key_add(name='Matched stroke')
            for vertex in key.data:
                x,y,z=vertex.co
                angle=math.atan2(y,x)
                center=Vector((radius*math.cos(angle),radius*math.sin(angle),.25))
                vertex.co=center+(vertex.co-center)*ratio
            self.ring_thickness[name]=key
        self.opacity={}
        self.colors={}
        for o in gallery.scene.objects:
            if o.type in ('MESH','CURVE','FONT') and o.data.materials:
                self.opacity[o]=fade_all_materials(o)
                for mat in o.data.materials:
                    for node in mat.node_tree.nodes:
                        if node.type=='EMISSION':
                            self.colors[o]=(node.inputs['Color'],tuple(node.inputs['Color'].default_value))
                            break
        self.state={}

    def named(self,name):
        return next(o for o in self.g.scene.objects if o.name==name or o.name.startswith(name+'.'))

    def fade(self,objects,amount):
        for obj in objects:
            for socket in self.opacity.get(obj,[]):socket.default_value=amount

    def tree(self,obj):
        return [obj,*obj.children_recursive]

    def tint(self,objects,color,amount):
        for o in objects:
            if o in self.colors:
                socket,original=self.colors[o]
                socket.default_value=tuple(original[i]*(1-amount)+color[i]*amount for i in range(3))+(1.,)

    def begin(self):
        for o,m in self.hud.items():o.matrix_world=m
        for sockets in self.opacity.values():
            for socket in sockets:socket.default_value=1.
        for socket,color in self.colors.values():socket.default_value=color
        for key in self.ring_thickness.values():key.value=0
        g=self.g
        self.named('NegativeRotorDot').location.z=.1
        self.light.location=(0,3,12)
        self.light.rotation_euler=(0,0,0)
        g.parcel.scale=(1,1,1)
        for parent in [g.neg,g.pos,g.parcel,g.comparison_start,g.comparison_north]:
            for o in parent.children:o.scale=(1,1,1)
        for parent in [g.comparison_start,g.comparison_north]:
            parent.scale=(1,1,1);parent.rotation_euler=(0,0,0)
        if hasattr(g,'air'):
            for o in g.air.children:o.scale=(1,1,1)
        g.flow.data.bevel_factor_end=1.
        for o in [*g.south,*g.north]:o.data.bevel_factor_end=1.

    def apply(self,n,p,t,frame):
        g=self.g;shot=framing(n,p);zoom=shot['zoom'];b=shot['bridge']
        focus=Vector((*shot['focus'],0));rotation=Matrix.Rotation(shot['yaw'],4,'Y')
        self.fade(self.tree(g.comparison_start)+self.tree(g.comparison_north),0)
        if hasattr(g,'wheel_bridge'):
            self.fade([g.wheel_bridge,g.wheel_bridge_dot],0)

        if n==4:
            self.fade([g.flow,*g.dots,*self.tree(g.pos)],1-window(p,.70,.91))
            self.tint([self.named('NegativeRotorRing')],(.82,.82,.78),b)
            self.tint([self.named('NegativeRotorDot')],GOLD,b)
            self.named('NegativeRotorDot').scale=(1-.6575*b,)*3
            self.named('NegativeRotorDot').location.z=.1+.25*b
            self.ring_thickness['NegativeRotorRing'].value=b
            # Carry the clockwise marker into the initial wheel cabin position.
            beat=next(x for x in g.job['timeline'] if x['controller_options']['scene_number']==4)
            end_t=(beat['end_frame']-1)/g.job['canonical_fps']
            target=-.558260+math.tau*math.floor((-end_t*.6+.558260)/math.tau)
            g.neg.rotation_euler.z=-t*.6*(1-b)+target*b
        elif n==5:
            reveal=smooth(p/.085)
            self.fade(g.wheel_meshes+[g.cabin_direction],reveal)
            self.fade([g.wheel_bridge,g.wheel_bridge_dot],1-reveal)
            g.wheel_bridge_dot.location=g.wheel_cabin.matrix_world.translation+Vector((0,0,.25))
        elif n==6:
            # The circular wheel gives way to the globe while the camera rises
            # into the exact northern view used by the following sequence.
            for o in g.groups['earth']:o.hide_render=o.hide_viewport=False
            g.set_earth_pose(dict(physical_angle=0.,observer_angle=0.,angle=0.,
                                 latitude=math.radians(70),tilt=math.radians(80)))
            self.fade(g.groups['earth'],b)
            self.fade(g.wheel_meshes+[g.cabin_direction],1-b)
            target=Matrix.Rotation(math.radians(-50),4,'X')
            rotation=rotation.to_quaternion().slerp(target.to_quaternion(),b).to_matrix().to_4x4()

        if 7<=n<=12:
            pose=g.earth_pose
            view_tilt=pose['tilt']
            if n==12:
                view_tilt=view_tilt+(math.pi/2-view_tilt)*b
                focus=Vector(g.earth_origin).lerp(g.air.matrix_world.translation,b)
                self.fade([o for o,_ in g.earth_meshes]+[g.axis,g.local_axis],1-b)
                self.fade([self.named('AirHeadingSpoke')],1-b)
                self.tint([self.named('AirParcelRing')],GOLD,b)
                self.ring_thickness['AirParcelRing'].value=b
                self.named('AirHeading').scale=(1+(.14*.55/.13-1)*b,)*3
                self.fade([g.bar_f,g.bar_z,*g.bar_labels],1-b)
            # Physical objects retain their motion in one world. The observer
            # follows the ground or changes viewing latitude via the camera.
            rotation=(g.earth_tilt@Matrix.Rotation(pose['observer_angle'],4,'Y')
                      @Matrix.Rotation(-view_tilt,4,'X'))

        if n==14:
            g.comparison_start.location=(-4,0,.2)
            self.fade(self.tree(g.comparison_start),window(p,.85))
        elif n==15:
            g.comparison_north.location=(-4,2,.2)
            self.fade(self.tree(g.comparison_north),max(1-window(p,0,.13),b))
            if b>0:
                g.parcel.location=g.parcel.location.lerp(g.pos.location,b)
                g.parcel.scale=(1-.15*b,)*3
                g.comparison_north.location=Vector((-4,2,.2)).lerp(g.neg.location,b)
                g.comparison_north.scale=(1-.15*b,)*3
                target=t*.6
                target=math.tau+(target-math.tau+math.pi)%math.tau-math.pi
                g.parcel.rotation_euler.z=g.parcel.rotation_euler.z*(1-b)+target*b
                g.comparison_north.rotation_euler.z=-target*b
                for obj in [self.named('ParcelHeading'),self.named('NorthComparisonHeading')]:
                    obj.scale=(1+(.17/(.14*.85)-1)*b,)*3
                self.tint(g.parcel.children,CYAN,b)
                self.tint(g.comparison_north.children,PINK,b)
                g.flow.hide_render=g.flow.hide_viewport=False
                for o in g.dots:o.hide_render=o.hide_viewport=False
                g.flow.data.bevel_factor_end=b;g.flow['animate_curve_reveal']=True
                self.fade(g.dots,b)
                self.fade([g.latitude,g.bar_f,g.bar_z,*g.bar_labels],1-b)
        elif n in (17,18):
            arrows=g.south if n==17 else g.north
            reveal=smooth(p/.14)
            arrows[0].data.bevel_factor_end=reveal
            arrows[0]['animate_curve_reveal']=True
            self.fade([arrows[1]],window(p,.10,.16))

        profile=g.job.get('variant_profile',{}).get('camera_profile','base')
        zoom*=dict(base=1,wide=26/24,close=23.5/24,restrained=24.6/24).get(profile,1)
        g.camera.data.ortho_scale=24*zoom
        g.camera.location=focus+rotation@Vector((4*zoom,0,25))
        g.camera.rotation_euler=rotation.to_euler('XYZ',g.camera.rotation_euler)
        if 6<=n<=12:
            # This is an illuminated teaching model, not a day/night diagram.
            # Keep the key light on the viewed hemisphere during the orbit.
            amount=b if n==6 else 1.
            center=Vector(g.earth_origin)
            destination=center+rotation@Vector((-3,5,12))
            self.light.location=Vector((0,3,12)).lerp(destination,amount)
            target=(center-self.light.location).to_track_quat('-Z','Y')
            self.light.rotation_euler=Matrix.Identity(4).to_quaternion().slerp(target,amount).to_euler()
        # HUD typography stays the same screen size and stays out of the image
        # while the actual 3D camera moves through the scientific scene.
        camera_matrix=Matrix.Translation(g.camera.location)@rotation
        hud_transform=camera_matrix@Matrix.Scale(zoom,4)@Matrix.Translation((0,0,-25))
        g.scene.view_layers[0].update()
        for obj in self.hud:obj.matrix_world=hud_transform@obj.matrix_world
        self.state=dict(scene=n,zoom=zoom,bridge=b,focus=list(focus),
                        color_values={o.name:list(s.default_value) for o,(s,_) in self.colors.items()})

    def bake(self,frame):
        for socket,_ in self.colors.values():socket.keyframe_insert(data_path='default_value',frame=frame)
        for key in self.ring_thickness.values():key.keyframe_insert(data_path='value',frame=frame)
