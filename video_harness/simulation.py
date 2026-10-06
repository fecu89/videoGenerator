from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ScriptArtifact
from .production_models import SceneTransitionSettings


TemplateName = Literal[
    "sky-orbit-reveal",
    "retrograde-track",
    "moving-observer",
    "sightline-angle",
    "speed-comparison",
    "earth-overtake",
    "projection-proof",
    "return-to-direct",
]
CameraName = Literal[
    "sky-to-orbit",
    "fixed-sky",
    "earth-pullback",
    "orbit-three-quarter",
    "orbit-top",
    "earth-tracking",
    "projection-three-quarter",
    "orbit-to-sky",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OutputSettings(StrictModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: int = Field(ge=1)
    video_codec: Literal["h264"]
    audio_codec: Literal["aac"]
    scene_transition: SceneTransitionSettings = Field(
        default_factory=SceneTransitionSettings
    )


class PhysicsSettings(StrictModel):
    model: Literal["circular-teaching-model"]
    earth_period_days: float = Field(gt=0)
    mars_period_days: float = Field(gt=0)
    earth_orbit_radius: float = Field(gt=0)
    mars_orbit_radius: float = Field(gt=0)
    opposition_day: float


class StyleSettings(StrictModel):
    preset: Literal["hybrid-space-explainer"]
    seed: int
    earth_scale: float = Field(gt=0)
    mars_scale: float = Field(gt=0)
    show_labels: bool


class SimulationScene(StrictModel):
    scene_id: int = Field(ge=1)
    template: TemplateName
    simulation_day_start: float
    simulation_day_end: float
    camera: CameraName


class SimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal["mars-retrograde"]
    output: OutputSettings
    physics: PhysicsSettings
    style: StyleSettings
    scenes: list[SimulationScene] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scene_ids(self) -> "SimulationConfig":
        ids = [scene.scene_id for scene in self.scenes]
        if ids != list(range(1, len(ids) + 1)):
            raise ValueError("simulation scene IDs must be contiguous from 1")
        return self


class SpectralPhysics(StrictModel):
    model: Literal["schematic-stellar-spectra"]


class SpectralStyle(StrictModel):
    seed: int = 20260915


class SpectralScene(StrictModel):
    scene_id: int = Field(ge=1)


class BlenderSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal["stellar-spectra-blender"]
    output: OutputSettings
    physics: SpectralPhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class EclipsePhysics(StrictModel):
    model: Literal['finite-disk-eclipse-teaching-model']


class EclipseSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['sun-earth-moon-blender']
    output: OutputSettings
    physics: EclipsePhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class VorticityPhysics(StrictModel):
    model: Literal['constant-depth-vorticity-teaching-model']


class VorticityStyle(SpectralStyle):
    asset_root: str


class VorticitySimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['vorticity-blender']
    output: OutputSettings
    physics: VorticityPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class BondingPhysics(StrictModel):
    model: Literal['structural-bonding-teaching-model']


class BondingSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['bonding-blender']
    output: OutputSettings
    physics: BondingPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class CoriolisPhysics(StrictModel):
    model: Literal['rotating-frame-teaching-model']


class CoriolisSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['coriolis-blender']
    output: OutputSettings
    physics: CoriolisPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class PhantomJamPhysics(StrictModel):
    model: Literal['optimal-velocity-ring-teaching-model']


class PhantomJamSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['phantom-jam-blender']
    output: OutputSettings
    physics: PhantomJamPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class OpticalDepthPhysics(StrictModel):
    model: Literal['exponential-direct-transmission']


class OpticalDepthSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['optical-depth-blender']
    output: OutputSettings
    physics: OpticalDepthPhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class TransferEquationPhysics(StrictModel):
    model: Literal['discrete-extinction-emission']


class TransferEquationSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['transfer-equation-blender']
    output: OutputSettings
    physics: TransferEquationPhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class VirialGalaxyPhysics(StrictModel):
    model: Literal['virial-mass-teaching-model']


class VirialGalaxySimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['virial-galaxy-blender']
    output: OutputSettings
    physics: VirialGalaxyPhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class AdiabaticPhysics(StrictModel):
    model: Literal['ideal-gas-adiabatic-teaching-model']


class AdiabaticSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['adiabatic-blender']
    output: OutputSettings
    physics: AdiabaticPhysics
    style: SpectralStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class SaturnRingsPhysics(StrictModel):
    model: Literal['kepler-tidal-teaching-model']


class SaturnRingsSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['saturn-rings-blender']
    output: OutputSettings
    physics: SaturnRingsPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


class TyphoonBetaPhysics(StrictModel):
    model: Literal['beta-drift-teaching-model']


class TyphoonBetaSimulationConfig(StrictModel):
    schema_version: Literal[1]
    preset: Literal['typhoon-beta-blender']
    output: OutputSettings
    physics: TyphoonBetaPhysics
    style: VorticityStyle
    scenes: list[SpectralScene] = Field(min_length=1)


def _validate_schema(payload: object) -> None:
    if isinstance(payload, dict) and payload.get('preset') == 'typhoon-beta-blender':
        TyphoonBetaSimulationConfig.model_validate(payload)
        return
    if isinstance(payload, dict) and payload.get('preset') == 'saturn-rings-blender':
        SaturnRingsSimulationConfig.model_validate(payload)
        return
    if isinstance(payload, dict) and payload.get('preset') == 'adiabatic-blender':
        AdiabaticSimulationConfig.model_validate(payload)
        return
    if isinstance(payload, dict) and payload.get('preset') == 'virial-galaxy-blender':
        VirialGalaxySimulationConfig.model_validate(payload)
        return
    if isinstance(payload, dict) and payload.get('preset') == 'transfer-equation-blender':
        TransferEquationSimulationConfig.model_validate(payload)
        return
    if isinstance(payload, dict) and payload.get('preset') == 'optical-depth-blender':
        OpticalDepthSimulationConfig.model_validate(payload)
        return
    if isinstance(payload,dict) and payload.get('preset')=='phantom-jam-blender':
        PhantomJamSimulationConfig.model_validate(payload)
        return
    if isinstance(payload,dict) and payload.get('preset')=='coriolis-blender':
        CoriolisSimulationConfig.model_validate(payload)
        return
    if isinstance(payload,dict) and payload.get('preset')=='bonding-blender':
        BondingSimulationConfig.model_validate(payload)
        return
    if isinstance(payload,dict) and payload.get('preset')=='vorticity-blender':
        VorticitySimulationConfig.model_validate(payload)
        return
    if isinstance(payload,dict) and payload.get('preset')=='sun-earth-moon-blender':
        EclipseSimulationConfig.model_validate(payload)
        return
    filename = (
        "spectral-simulation.schema.json"
        if isinstance(payload, dict) and payload.get("preset") == "stellar-spectra-blender"
        else "simulation.schema.json"
    )
    schema_path = Path(__file__).resolve().parent / "schemas" / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path) or "$"
    raise ValueError(f"simulation.json {location}: {error.message}")


def load_simulation(run_dir: Path, script: ScriptArtifact) -> SimulationConfig | BlenderSimulationConfig | EclipseSimulationConfig | VorticitySimulationConfig:
    path = run_dir.resolve() / "simulation.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"simulation.json을 읽을 수 없습니다: {error}") from error

    _validate_schema(payload)
    if payload.get('preset') == 'typhoon-beta-blender':
        config = TyphoonBetaSimulationConfig.model_validate(payload)
    elif payload.get('preset') == 'saturn-rings-blender':
        config = SaturnRingsSimulationConfig.model_validate(payload)
    elif payload.get('preset') == 'adiabatic-blender':
        config = AdiabaticSimulationConfig.model_validate(payload)
    elif payload.get('preset') == 'virial-galaxy-blender':
        config = VirialGalaxySimulationConfig.model_validate(payload)
    elif payload.get('preset') == 'transfer-equation-blender':
        config = TransferEquationSimulationConfig.model_validate(payload)
    elif payload.get('preset') == 'optical-depth-blender':
        config = OpticalDepthSimulationConfig.model_validate(payload)
    elif payload.get('preset')=='phantom-jam-blender':
        config = PhantomJamSimulationConfig.model_validate(payload)
    elif payload.get('preset')=='coriolis-blender':
        config = CoriolisSimulationConfig.model_validate(payload)
    elif payload.get('preset')=='bonding-blender':
        config = BondingSimulationConfig.model_validate(payload)
    elif payload.get('preset')=='vorticity-blender':
        config = VorticitySimulationConfig.model_validate(payload)
    elif payload.get('preset')=='sun-earth-moon-blender':
        config = EclipseSimulationConfig.model_validate(payload)
    elif payload.get("preset") == "stellar-spectra-blender":
        config = BlenderSimulationConfig.model_validate(payload)
    else:
        config = SimulationConfig.model_validate(payload)
    if [scene.scene_id for scene in config.scenes] != [
        scene.scene_id for scene in script.scenes
    ]:
        raise ValueError("simulation.json scenes must match script.json")
    return config
