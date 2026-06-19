"""Schema constants — table and column names for the NocoDB layout.

Single source of truth for cross-module string literals. Every other module
imports from here; never duplicates a literal.
"""
from __future__ import annotations

from enum import StrEnum


class Tables:
    """NocoDB table names."""

    STUDIES = "studies"
    EXPERIMENTS = "experiments"
    DATASETS = "datasets"
    EXPERIMENT_SETS = "experiment_sets"   # named groups — supersedes `datasets` (optional until provisioned)
    DIM_POSITIONS = "dim_positions"
    SET_STUDY_CONSTANTS = "set_study_constants"
    SET_EXP_PARAMS = "set_exp_params"
    SET_EXP_FEATURES = "set_exp_features"
    SET_EXP_ATTRIBUTES = "set_exp_attributes"

    # robolab config catalog — the relational lab-config SSOT (optional until provisioned).
    PARAMS = "params"           # tunable-leaf definitions (the config catalog)
    SERVICES = "services"       # capabilities; self-`Requires` dependency graph
    USE_CASES = "use_cases"     # named bundles of services
    UNITS = "units"             # rig assemblies (printer / scanner …) — compositions of hardware
    HARDWARE = "hardware"       # physical device identity (robot / tool / sensor)


class StudyColumns:
    """Columns on the `studies` table."""

    ID = "Id"
    CODE = "code"
    DESCRIPTION = "description"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    SCHEMA = "schema"
    DATASETS = "datasets"  # LinkToAnotherRecord -> datasets (nullable)


class ExperimentColumns:
    """Columns on the `experiments` table."""

    ID = "Id"
    CODE = "code"
    STUDIES = "studies"  # LinkToAnotherRecord -> studies
    DATASET = "dataset"  # LinkToAnotherRecord -> datasets (nullable)
    STATUS = "status"
    STARTED_AT = "started_at"
    ENDED_AT = "ended_at"
    NOTES = "notes"
    DESIGN = "design"          # SingleSelect — per-experiment generative design (Strategy values)
    PROVENANCE = "provenance"  # LongText (JSON) — full generative config snapshot


class DatasetColumns:
    """Columns on the `datasets` table."""

    ID = "Id"
    CODE = "code"
    STUDY = "study"  # LinkToAnotherRecord -> studies
    NAME = "name"
    STRATEGY = "strategy"  # how experiments were generated
    PURPOSE = "purpose"  # how they're used
    DESCRIPTION = "description"


class ExperimentSetColumns:
    """Columns on the `experiment_sets` table — one row per named group.

    Membership is a JSON list in ``MEMBERS`` (experiment codes, in order for ordered sets):
    a denormalised many-to-many (a set lists its members; an experiment can appear in many
    sets), mirroring pred-fab's ``ExperimentSet.to_dict`` 1:1 — no LTAR join table needed.
    """

    ID = "Id"
    CODE = "code"
    ORDERED = "ordered"        # Checkbox — sequential vs batch
    MEMBERS = "members"        # LongText (JSON) — experiment codes, in order
    # Generation (source method, κ) is per-experiment provenance, not a set field.


class ConfigParamColumns:
    """Columns on the `params` config catalog — one row per tunable-leaf *definition*.

    Keyed by ``CODE`` (distinct from `set_exp_params`, which holds per-experiment param
    *values*: this is the catalog of definitions). ``VALUE`` is the runtime SSOT seed
    default (value-preserving upsert never clobbers it). ``TYPE`` is the coercion authority
    for ``VALUE`` (stored as text — a value may be categorical); ``MIN``/``MAX`` are numeric
    safety bounds (Number columns). A param has a **polymorphic owner** — at most one of
    ``SERVICE``/``HARDWARE``/``UNIT`` set (0 = a global param); the client + materialiser
    enforce ≤1 fail-loud since NocoDB can't.
    """

    ID = "Id"
    CODE = "code"              # unique definition key
    LABEL = "label"            # human display name
    TYPE = "type"              # SingleSelect — real/int/bool/categorical/vector/list (coercion authority)
    SCOPE = "scope"            # SingleSelect — knob/editable/constant/safety (editability/nature)
    VALUE = "value"            # text — seed-default value; preserved for knob/editable, re-seeded for constant/safety
    OPTIONS = "options"        # LongText (JSON) — allowed values for categoricals (nullable)
    MIN = "min"                # Number — sanity lower bound (rtde's gate-feeding safety params); nullable
    MAX = "max"                # Number — sanity upper bound; nullable
    UNIT = "unit"              # text — physical unit of measure (nullable; e.g. "mm", "m/s")
    DESCRIPTION = "description"  # text
    # Polymorphic owner — nullable LTARs, AT MOST ONE set (0 = global). See PARAM_OWNER_COLUMNS.
    SERVICE = "service"        # LinkToAnotherRecord -> services (nullable)
    HARDWARE = "hardware"      # LinkToAnotherRecord -> hardware (nullable)
    UNIT_OWNER = "unit_owner"  # LinkToAnotherRecord -> units (nullable; distinct from UNIT = measure)


# The polymorphic-owner link columns on `params`, in resolution order. Single home for "what
# can own a param"; the ≤1-non-null invariant is asserted against this set (0 = global).
PARAM_OWNER_COLUMNS: tuple[str, ...] = (
    ConfigParamColumns.SERVICE,
    ConfigParamColumns.HARDWARE,
    ConfigParamColumns.UNIT_OWNER,
)


class HardwareColumns:
    """Columns on the `hardware` table — physical device identity (the param link-target).

    One row per physical device; *identity only* — a device's variable physics are `params`
    rows linked to it. Absorbs the former ``robots`` registry. ``NAME`` is the key.
    """

    ID = "Id"
    NAME = "name"              # unique device identity
    TYPE = "type"              # SingleSelect — robot / tool / sensor
    KIND = "kind"              # text — model/class (UR10e / WASPclay / Gocator / …)


class ServiceColumns:
    """Columns on the `services` table — lab capabilities + their dependency graph."""

    ID = "Id"
    NAME = "name"              # unique service identity
    ENABLED = "enabled"        # Checkbox
    KIND = "kind"              # text — service category (e.g. sensor / actuator)
    REQUIRES = "requires"      # LinkToAnotherRecord -> services (SELF m2m — dependencies)
    DASHBOARD = "dashboard"    # LongText (JSON) — dashboard config
    HARDWARE = "hardware"      # LinkToAnotherRecord -> hardware (nullable; a sensor service's device)


class UseCaseColumns:
    """Columns on the `use_cases` table — named bundles of services."""

    ID = "Id"
    NAME = "name"              # unique use-case identity
    DESCRIPTION = "description"
    SERVICES = "services"      # LinkToAnotherRecord -> services (m2m)
    SET = "set"                # LongText (JSON) — per-use-case param overrides (code → value)


class UnitColumns:
    """Columns on the `units` table — rig assemblies (one row per unit), composed of hardware.

    A unit is a named assembly (printer / scanner) referencing its `hardware` devices; the
    devices carry their own physics as linked `params`. ``ROLE`` is the unit key.
    """

    ID = "Id"
    ROLE = "role"              # unique unit role (e.g. printer / scanner)
    ROBOT = "robot"            # LinkToAnotherRecord -> hardware (the unit's robot device)
    TOOL = "tool"              # LinkToAnotherRecord -> hardware (the unit's mounted tool)
    SENSORS = "sensors"        # LinkToAnotherRecord -> hardware (the unit's sensor devices, m2m)


class DimPositionColumns:
    """Columns on the `dim_positions` table."""

    ID = "Id"
    CODE = "code"
    DOMAIN = "domain"
    DEPTH = "depth"
    AXES = "axes"
    CONTAINED_IN = "contained_in"  # self-link to ancestor dim_positions


class StudyConstantColumns:
    """Columns on the `set_study_constants` table."""

    ID = "Id"
    CODE = "code"
    STUDY = "study"  # LinkToAnotherRecord -> studies
    PARAM = "param"  # the constant's identifying code
    VALUE = "value"


class ParamColumns:
    """Columns on the `set_exp_params` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"  # LinkToAnotherRecord -> experiments
    PARAM = "param"  # the parameter's identifying code
    DIM = "dim"  # LinkToAnotherRecord -> dim_positions (nullable)
    VALUE = "value"


class FeatureColumns:
    """Columns on the `set_exp_features` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"
    FEATURE = "feature"  # the feature's identifying code
    DIM = "dim"
    VALUE = "value"


class AttributeColumns:
    """Columns on the `set_exp_attributes` table."""

    ID = "Id"
    CODE = "code"
    EXPERIMENT = "experiment"
    ATTRIBUTE = "attribute"  # the attribute's identifying code
    DIM = "dim"
    VALUE = "value"


class Status(StrEnum):
    """Experiment lifecycle states."""

    DRAFT = "draft"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Strategy(StrEnum):
    """How experiments are generated — the design.

    Used both as the dataset-level strategy and as the per-experiment ``design``
    column (the queryable provenance axis mirroring pred-fab's ``SourceStep``).
    """

    GRID = "grid"
    DISCOVERY = "discovery"
    EXPLORATION = "exploration"
    INFERENCE = "inference"
    ADAPTATION = "adaptation"
    SOBOL = "sobol"


class Purpose(StrEnum):
    """Dataset purposes — *what* the experiments are used for."""

    REFERENCE = "reference"
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class ConfigType(StrEnum):
    """Declared type of a `params` value — the coercion authority for the text-stored value.

    A SingleSelect column on `params`; the one place raw → typed coercion is driven from
    (see `config_params.coerce_value`)."""

    REAL = "real"
    INT = "int"
    BOOL = "bool"
    CATEGORICAL = "categorical"
    VECTOR = "vector"
    LIST = "list"


class ConfigScope(StrEnum):
    """A `params` definition's editability/nature — a SingleSelect column.

    Tunable scopes (`KNOB`/`EDITABLE`) are runtime-authoritative (value-preserving upsert);
    non-tunable (`CONSTANT`/`SAFETY`) are seed-authoritative (re-seed overwrites — they are
    config-as-code, not runtime values). Per-rig hardware is the `units` table, not a scope."""

    KNOB = "knob"            # tunable per experiment
    EDITABLE = "editable"    # user-editable default
    CONSTANT = "constant"    # structural constant (seed-authoritative)
    SAFETY = "safety"        # safety bound (seed-authoritative)


# Scopes whose value the seed owns — re-seed OVERWRITES (vs tunable scopes, preserved). Single
# home for the value-authority split (Refinement A).
SEED_AUTHORITATIVE_SCOPES: frozenset[str] = frozenset({ConfigScope.CONSTANT, ConfigScope.SAFETY})


class HardwareType(StrEnum):
    """The `hardware.type` SingleSelect — what class of physical device a row is."""

    ROBOT = "robot"
    TOOL = "tool"
    SENSOR = "sensor"
