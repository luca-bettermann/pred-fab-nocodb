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
    UNITS = "units"             # per-rig hardware (printer / scanner …)


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
    safety bounds (Number columns). ``SERVICE`` links the service a service-param configures.
    """

    ID = "Id"
    CODE = "code"              # unique definition key
    LABEL = "label"            # human display name
    TYPE = "type"              # SingleSelect — real/int/bool/categorical/vector/list (coercion authority)
    SCOPE = "scope"            # SingleSelect — knob/editable/constant/safety (editability/nature)
    VALUE = "value"            # text — the seed-default runtime value (coerced per TYPE by the consumer)
    OPTIONS = "options"        # LongText (JSON) — allowed values for categoricals (nullable)
    MIN = "min"                # Number — sanity lower bound (rtde's gate-feeding safety params); nullable
    MAX = "max"                # Number — sanity upper bound; nullable
    UNIT = "unit"              # text — physical unit (nullable)
    DESCRIPTION = "description"  # text
    SERVICE = "service"        # LinkToAnotherRecord -> services (nullable; set for service params)


class ServiceColumns:
    """Columns on the `services` table — lab capabilities + their dependency graph."""

    ID = "Id"
    NAME = "name"              # unique service identity
    ENABLED = "enabled"        # Checkbox
    KIND = "kind"              # text — service category (e.g. sensor / actuator)
    REQUIRES = "requires"      # LinkToAnotherRecord -> services (SELF m2m — dependencies)
    DASHBOARD = "dashboard"    # LongText (JSON) — dashboard config


class UseCaseColumns:
    """Columns on the `use_cases` table — named bundles of services."""

    ID = "Id"
    NAME = "name"              # unique use-case identity
    DESCRIPTION = "description"
    SERVICES = "services"      # LinkToAnotherRecord -> services (m2m)


class UnitColumns:
    """Columns on the `units` table — this rig's hardware units (one row per unit).

    Per-rig hardware param *values* (home_joints, tool_offset, …) live in `params`, not
    here; a unit row is the hardware identity + its sensors. ``ROLE`` is the unit key.
    """

    ID = "Id"
    ROLE = "role"              # unique unit role (e.g. printer / scanner)
    ROBOT = "robot"            # text — robot model/identity
    TOOL = "tool"              # text — mounted tool
    SENSORS = "sensors"        # LinkToAnotherRecord -> services (the unit's sensor services)


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

    Per-rig hardware is the `units` table, not a scope value."""

    KNOB = "knob"            # tunable per experiment
    EDITABLE = "editable"    # user-editable default
    CONSTANT = "constant"    # read-only
    SAFETY = "safety"        # safety bound (gate-feeding)
