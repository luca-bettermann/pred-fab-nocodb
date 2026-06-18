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
    CONFIG_PARAMS = "config_params"       # single-SSOT config catalog (optional until provisioned)
    SET_STUDY_CONSTANTS = "set_study_constants"
    SET_EXP_PARAMS = "set_exp_params"
    SET_EXP_FEATURES = "set_exp_features"
    SET_EXP_ATTRIBUTES = "set_exp_attributes"


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
    """Columns on the `config_params` table — the single-SSOT config catalog.

    One row per config definition, keyed by ``CODE``. ``VALUE`` is the runtime SSOT
    (value-preserving upsert never clobbers it); the remaining columns are the
    *structure* (refreshed from the repo seed on stack-up). ``TYPE`` is the coercion
    authority for ``VALUE`` (stored as text); ``OPTIONS`` is a JSON list.
    """

    ID = "Id"
    CODE = "code"
    VALUE = "value"            # text — the runtime value (coerced per TYPE by the consumer)
    TYPE = "type"              # SingleSelect — real / int / bool / categorical (coercion authority)
    SCOPE = "scope"            # text — where the param applies (process / per-rig / service / ...)
    DESCRIPTION = "description"  # text
    OPTIONS = "options"        # LongText (JSON) — allowed values for categoricals (nullable)


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
