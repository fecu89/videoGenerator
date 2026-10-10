"""Apply and attest render-affecting Blender settings to the actual Scene."""


def apply_blender_settings(scene, settings):
    if scene.render.engine != 'BLENDER_EEVEE':
        raise RuntimeError('Expected BLENDER_EEVEE before applying Shadow Pool')
    requested = str(settings['shadow_pool_mb'])
    try:
        eevee = scene.eevee
        # RNA enums reject some unsupported values silently on some versions.
        if hasattr(eevee, 'bl_rna'):
            values = {item.identifier for item in eevee.bl_rna.properties['shadow_pool_size'].enum_items}
            if requested not in values:
                raise ValueError(f'{requested} MB is unsupported (available: {sorted(values)})')
        eevee.shadow_pool_size = requested
        actual = eevee.shadow_pool_size
        if actual != requested:
            raise ValueError(f'requested {requested} MB, got {actual} MB')
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f'Cannot apply EEVEE Shadow Pool {requested} MB: {error}') from error
    return {'shadow_pool_mb': int(actual)}
