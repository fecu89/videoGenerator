"""Camera-attached keyword callouts: emphasised anchor → colour-matched leader → one big word.

The plan's `labels` are the only text source. Geometry lives in callout_math so the
text gate and previews compute the same rectangles without bpy.
"""
from mathutils import Vector
from callout_math import (hud_scale, project_to_ndc, radius_in_unit, ndc_to_unit, text_box,
    label_rect, leader_points, fade_amount, anchor_amounts, REFERENCE_WIDTH, HUD_DEPTH)

INK=(.92,.95,1); WORD_SIZE=1.56; UNIT_SIZE=.78; LEADER_RADIUS=.018
GLOW_GAIN=1.5; SCALE_GAIN=.25


class CalloutLayer:
    def __init__(self,gallery):
        self.g=gallery;self.items=[];self.last_amounts={}

    def bind(self,labels,objects):
        g=self.g
        for beat_labels,beat in labels:
            for label in beat_labels:
                anchor=objects.get(label['anchor'])
                if anchor is None:raise KeyError(f"callout anchor missing: {label['anchor']}")
                kind=label.get('kind','word');size=UNIT_SIZE*3 if label.get('size')=='xlarge' else UNIT_SIZE if kind=='unit' or label.get('size')=='small' else WORD_SIZE
                text=g.text(label['text'],0,0,size,INK,'LEFT');text.parent=g.camera;text.rotation_euler=(0,0,0)
                text.data.materials[0]=text.data.materials[0].copy()
                strength=next(n for n in text.data.materials[0].node_tree.nodes if n.type=='EMISSION').inputs['Strength']
                leader=g.path(label['text']+' leader',[(0,0,-HUD_DEPTH)]*3,INK,LEADER_RADIUS);leader.parent=g.camera
                leader.data.materials[0]=leader.data.materials[0].copy()
                emphasis=label.get('emphasis','glow');base=None
                if emphasis=='glow':
                    for slot in anchor.material_slots:
                        if slot.material and slot.material.users>1:slot.material=slot.material.copy()
                    base=[self._emission(slot.material).default_value for slot in anchor.material_slots if slot.material and self._emission(slot.material)]
                elif emphasis=='scale':base=tuple(anchor.scale)
                self.items.append(dict(label=label,kind=kind,beat=beat,anchor=anchor,text=text,strength=strength,leader=leader,emphasis=emphasis,base=base,state=None))

    @staticmethod
    def _emission(material):
        if not material or not material.use_nodes:return None
        node=next((n for n in material.node_tree.nodes if n.type=='EMISSION'),None)
        return node.inputs['Strength'] if node else None

    def _camera(self):
        data=self.g.camera.data
        return dict(projection=data.type,ortho_scale=float(data.ortho_scale),sensor_width=float(data.sensor_width),lens=float(data.lens))

    def update(self,frame,amounts=None):
        g=self.g;cam=self._camera();fps=g.job['canonical_fps']
        width=g.job['output']['width'];height=g.job['output']['height'];aspect=width/height
        scale=hud_scale(cam['projection'],cam['ortho_scale'],cam['sensor_width'],cam['lens'])
        for index,item in enumerate(self.items):
            beat=item['beat'];amount=amounts[index] if amounts is not None else fade_amount(frame,beat['start_frame'],beat['end_frame'],fps)
            local=g.camera.matrix_world.inverted()@item['anchor'].matrix_world.translation
            try:ndc=project_to_ndc(list(local),cam['projection'],cam['ortho_scale'],cam['sensor_width'],cam['lens'],aspect)
            except ValueError:amount=0.0;ndc=(0.0,0.0)
            anchor_unit=ndc_to_unit(*ndc)
            radius=max(item['anchor'].dimensions)/2
            r_unit=radius_in_unit(radius,list(local),cam['projection'],cam['ortho_scale'],cam['sensor_width'],cam['lens'],aspect)
            side=item['label'].get('side','right')
            box=text_box(item['label']['text'],item['kind'],width,height,item['label'].get('size','large'))
            rect=label_rect(anchor_unit,r_unit,side,box)
            leader=leader_points(anchor_unit,r_unit,rect,side)
            self._place(item,rect,leader,scale,amount)
            item['amount']=amount
            item['state']=dict(text=item['label']['text'],anchor=item['label']['anchor'],kind=item['kind'],rect=[float(v) for v in rect],leader=[[float(x),float(y)] for x,y in leader],amount=float(amount))

        # One write per anchor per frame, and only while some label is active or just
        # went inactive, so the gallery's own animation of that object is not overridden.
        amounts=anchor_amounts((item['label']['anchor'],item['amount']) for item in self.items)
        for item in self.items:
            name=item['label']['anchor'];amount=amounts[name]
            if amount>0 or self.last_amounts.get(name,0)>0:self._emphasise(item,amount)
        self.last_amounts=amounts

    def _hud(self,unit,scale):
        # Unit screen coords → camera-local HUD plane at depth HUD_DEPTH, width REFERENCE_WIDTH*scale.
        w=REFERENCE_WIDTH*scale;h=w*self.g.job['output']['height']/self.g.job['output']['width']
        return Vector(((unit[0]-.5)*w,(.5-unit[1])*h,-HUD_DEPTH))

    def _place(self,item,rect,leader,scale,amount):
        text=item['text'];origin=self._hud((rect[0],rect[3]),scale)
        text.location=origin;text.scale=(scale,)*3
        hidden=amount<.002
        text.hide_render=text.hide_viewport=hidden;item['strength'].default_value=amount
        for point,xy in zip(item['leader'].data.splines[0].points,leader):
            v=self._hud(xy,scale);point.co=(v.x,v.y,v.z,1)
        item['leader'].data.bevel_depth=LEADER_RADIUS*scale
        item['leader'].hide_render=item['leader'].hide_viewport=hidden

    def _emphasise(self,item,amount):
        anchor=item['anchor']
        if item['emphasis']=='glow':
            sockets=[self._emission(s.material) for s in anchor.material_slots if s.material and self._emission(s.material)]
            for socket,base in zip(sockets,item['base']):socket.default_value=base*(1+GLOW_GAIN*amount)
        elif item['emphasis']=='scale':
            anchor.scale=tuple(b*(1+SCALE_GAIN*amount) for b in item['base'])

    def screen_state(self):
        return [item['state'] for item in self.items if item['state'] is not None]


def labels_from_job(job):
    """[(labels, beat)] for every beat that declares labels."""
    return [(beat['controller_options']['labels'],beat) for beat in job['timeline'] if beat.get('controller_options',{}).get('labels')]
