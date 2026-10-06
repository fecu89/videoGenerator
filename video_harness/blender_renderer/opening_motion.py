"""Camera/text motion shared across the opening's editorial boundary."""
try:
    from .spectra import smooth
except ImportError:
    from spectra import smooth


def opening_camera_z(elapsed):
    return 22.8 + 1.2 * smooth(elapsed / 7.8)


def opening_text_opacity(elapsed):
    return 1 - smooth((elapsed - 7.65) / 1.1)
